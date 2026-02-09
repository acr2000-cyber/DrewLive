import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import List, Optional

import aiohttp
from playwright.async_api import async_playwright, Page, Route, Request

# -----------------------
# Configuration
# -----------------------
API_URL = "https://ppv.to/api/streams"

REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:143.0) Gecko/20100101 Firefox/143.0",
    "Origin": "https://ppv.to",
    "Referer": "https://ppv.to/",
}

CUSTOM_HEADERS = [
    "#EXTVLCOPT:http-origin=https://ppv.to",
    "#EXTVLCOPT:http-referrer=https://ppv.to/",
    "#EXTVLCOPT:http-user-agent=Mozilla/5.0",
]

# -----------------------
# Data models
# -----------------------
@dataclass
class NetworkEvent:
    ts: float
    url: str
    method: str
    resource_type: str
    status: Optional[int] = None

@dataclass
class StreamObservation:
    stream_id: str
    embed_url: str
    requests: List[NetworkEvent] = field(default_factory=list)
    verdict: str = "unknown"

# -----------------------
# API helpers
# -----------------------
async def fetch_streams(session: aiohttp.ClientSession) -> List[dict]:
    try:
        async with session.get(API_URL, headers=REQUEST_HEADERS) as resp:
            if resp.status != 200:
                logging.error(f"API failed with status {resp.status}")
                return []
            return await resp.json()
    except Exception as e:
        logging.error(f"Error fetching streams: {e}")
        return []

def normalize_streams(raw: List) -> List[dict]:
    normalized = []
    for item in raw:
        if isinstance(item, dict) and "id" in item:
            normalized.append(item)
        elif isinstance(item, (str, int)):
            normalized.append({"id": str(item)})
        else:
            logging.warning(f"Unknown stream entry: {item}")
    return normalized

async def get_embed_url(session: aiohttp.ClientSession, stream_id: str) -> Optional[str]:
    url = f"https://ppv.to/embed/{stream_id}"
    try:
        async with session.head(url, headers=REQUEST_HEADERS, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 200:
                return url
    except Exception as e:
        logging.debug(f"Embed URL check failed: {e}")
    return None

# -----------------------
# Scraping helpers
# -----------------------
async def intercept_m3u8_requests(page: Page, observation: StreamObservation):
    """Intercept network requests for .m3u8 and record them"""

    async def handle_request(route: Route, request: Request):
        url = request.url
        if ".m3u8" in url:
            observation.requests.append(NetworkEvent(time.time(), url, request.method, request.resource_type, None))
            observation.verdict = "hls_observed"
        await route.continue_()

    await page.route("**/*", handle_request)

async def scrape_embed(page: Page, embed_url: str, observation: StreamObservation) -> List[str]:
    """Visit embed URL and capture HLS requests via network interception"""
    try:
        await intercept_m3u8_requests(page, observation)
        await page.goto(embed_url, wait_until="domcontentloaded", timeout=30_000)
        await asyncio.sleep(3)  # wait for network requests
        return [req.url for req in observation.requests]
    except Exception as e:
        logging.warning(f"Scrape failed for {embed_url}: {e}")
        return []

# -----------------------
# Playlist builder
# -----------------------
def build_safe_playlist(observations: List[StreamObservation]) -> str:
    playlist = "#EXTM3U\n"
    for obs in observations:
        if obs.verdict != "hls_observed" or not obs.requests:
            continue
        url = obs.requests[0].url
        headers = "|".join(CUSTOM_HEADERS)
        playlist += f'#EXTINF:-1 tvg-name="{obs.stream_id}",{obs.stream_id}\n{url}|{headers}\n'
    return playlist

# -----------------------
# Main
# -----------------------
async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    async with aiohttp.ClientSession() as session:
        raw_streams = await fetch_streams(session)
        streams = normalize_streams(raw_streams)
        logging.info(f"Found {len(streams)} streams after normalization")

        async with async_playwright() as p:
            browser = await p.firefox.launch(headless=True)
            context = await browser.new_context()
            page = await context.new_page()

            observations: List[StreamObservation] = []

            for s in streams:
                stream_id = str(s["id"])
                embed_url = await get_embed_url(session, stream_id)
                if not embed_url:
                    continue

                obs = StreamObservation(stream_id=stream_id, embed_url=embed_url)
                await scrape_embed(page, embed_url, obs)
                observations.append(obs)

                await asyncio.sleep(1)  # rate limit

            playlist = build_safe_playlist(observations)
            with open("ppv_streams.m3u", "w", encoding="utf-8") as f:
                f.write(playlist)

            logging.info(f"Saved playlist with {len([o for o in observations if o.verdict=='hls_observed'])} streams")
            await page.close()
            await context.close()
            await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
