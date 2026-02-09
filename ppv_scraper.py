import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import List, Optional, Dict

import aiohttp
from playwright.async_api import async_playwright, Page, Route, Request

# -----------------------
# Configuration
# -----------------------
API_URL = "https://ppv.to/api/streams"

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:143.0) Gecko/20100101 Firefox/143.0",
    "Origin": "https://ppv.to",
    "Referer": "https://ppv.to/",
}

# -----------------------
# Data models
# -----------------------
@dataclass
class NetworkEvent:
    ts: float
    url: str
    method: str
    resource_type: str
    headers: Dict[str, str] = field(default_factory=dict)

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
        async with session.get(API_URL, headers=DEFAULT_HEADERS) as resp:
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
        async with session.head(url, headers=DEFAULT_HEADERS, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 200:
                return url
    except Exception as e:
        logging.debug(f"Embed URL check failed: {e}")
    return None

# -----------------------
# Scraping helpers
# -----------------------
async def intercept_m3u8_requests(page: Page, observation: StreamObservation):
    """Intercept network requests for .m3u8 and record them with headers"""
    async def handle_request(route: Route, request: Request):
        url = request.url
        if ".m3u8" in url:
            headers = dict(request.headers)
            observation.requests.append(NetworkEvent(time.time(), url, request.method, request.resource_type, headers))
            observation.verdict = "hls_observed"
            logging.info(f"[HLS DETECTED] {url}")
        await route.continue_()
    await page.route("**/*", handle_request)

async def scrape_embed(page: Page, embed_url: str, observation: StreamObservation):
    """Visit embed URL and capture HLS requests via network interception and JS inspection"""
    try:
        await intercept_m3u8_requests(page, observation)
        await page.goto(embed_url, wait_until="domcontentloaded", timeout=60_000)

        # Wait for dynamic JS loading
        for _ in range(5):
            # Check video elements for HLS
            urls = await page.evaluate(
                """() => Array.from(document.querySelectorAll('video, video source'))
                        .map(v => v.src || v.currentSrc)
                        .filter(u => u && u.includes('.m3u8'))"""
            )
            for u in urls:
                if u not in [r.url for r in observation.requests]:
                    observation.requests.append(NetworkEvent(time.time(), u, "GET", "media", DEFAULT_HEADERS))
                    observation.verdict = "hls_observed"
                    logging.info(f"[HLS VIDEO SRC] {u}")
            await asyncio.sleep(2)  # wait before next check

    except Exception as e:
        logging.warning(f"Scrape failed for {embed_url}: {e}")

# -----------------------
# Playlist builder
# -----------------------
def build_safe_playlist(observations: List[StreamObservation]) -> str:
    playlist = "#EXTM3U\n"
    for obs in observations:
        if obs.verdict != "hls_observed" or not obs.requests:
            continue
        for req in obs.requests:
            headers_str = ""
            if req.headers:
                headers_str += f"#EXTVLCOPT:http-user-agent={req.headers.get('user-agent','')}\n"
                headers_str += f"#EXTVLCOPT:http-referrer={req.headers.get('referer','')}\n"
                headers_str += f"#EXTVLCOPT:http-origin={req.headers.get('origin','')}\n"

            playlist += f'#EXTINF:-1 tvg-name="{obs.stream_id}",{obs.stream_id}\n{req.url}\n{headers_str}'
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
            # Use headful for debugging dynamic HLS loading
            browser = await p.firefox.launch(headless=False)
            context = await browser.new_context()
            page = await context.new_page()

            observations: List[StreamObservation] = []

            for s in streams:
                stream_id = str(s["id"])
                embed_url = await get_embed_url(session, stream_id)
                if not embed_url:
                    logging.info(f"No embed URL for stream {stream_id}")
                    continue

                obs = StreamObservation(stream_id=stream_id, embed_url=embed_url)
                await scrape_embed(page, embed_url, obs)
                observations.append(obs)
                await asyncio.sleep(1)  # rate limit

            playlist = build_safe_playlist(observations)
            with open("PPVLand.m3u8", "w", encoding="utf-8") as f:
                f.write(playlist)

            logging.info(f"Saved playlist with {len([o for o in observations if o.verdict=='hls_observed'])} streams")
            await page.close()
            await context.close()
            await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
