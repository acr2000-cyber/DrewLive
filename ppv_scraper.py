import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import List, Dict

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

# -----------------------
# Scraping helpers
# -----------------------
async def intercept_m3u8_requests(page: Page, observation: StreamObservation):
    async def handle_request(route: Route, request: Request):
        url = request.url
        if ".m3u8" in url:
            observation.requests.append(
                NetworkEvent(
                    ts=time.time(),
                    url=url,
                    method=request.method,
                    resource_type=request.resource_type,
                    headers=dict(request.headers),
                )
            )
            observation.verdict = "hls_observed"
            logging.info(f"[HLS] {observation.stream_id} → {url}")
        await route.continue_()

    await page.route("**/*", handle_request)

async def scrape_embed(page: Page, embed_url: str, observation: StreamObservation):
    try:
        await intercept_m3u8_requests(page, observation)

        await page.goto(embed_url, wait_until="networkidle", timeout=60_000)
        await asyncio.sleep(5)

        # Scan all frames for video sources
        for frame in page.frames:
            try:
                urls = await frame.evaluate(
                    """() => Array.from(document.querySelectorAll('video, video source'))
                          .map(v => v.src || v.currentSrc)
                          .filter(u => u && u.includes('.m3u8'))"""
                )
                for u in urls:
                    if u not in [r.url for r in observation.requests]:
                        observation.requests.append(
                            NetworkEvent(time.time(), u, "GET", "media", DEFAULT_HEADERS)
                        )
                        observation.verdict = "hls_observed"
                        logging.info(f"[HLS-FRAME] {observation.stream_id} → {u}")
            except Exception:
                pass

    except Exception as e:
        logging.warning(f"Scrape failed for {embed_url}: {e}")

# -----------------------
# Playlist builder
# -----------------------
def build_safe_playlist(observations: List[StreamObservation]) -> str:
    playlist = "#EXTM3U\n"
    seen_urls = set()

    for obs in observations:
        if obs.verdict != "hls_observed":
            continue

        for req in obs.requests:
            if req.url in seen_urls:
                continue
            seen_urls.add(req.url)

            playlist += f'#EXTINF:-1 tvg-name="{obs.stream_id}",{obs.stream_id}\n'
            if req.headers:
                if "user-agent" in req.headers:
                    playlist += f'#EXTVLCOPT:http-user-agent={req.headers["user-agent"]}\n'
                if "referer" in req.headers:
                    playlist += f'#EXTVLCOPT:http-referrer={req.headers["referer"]}\n'
                if "origin" in req.headers:
                    playlist += f'#EXTVLCOPT:http-origin={req.headers["origin"]}\n'
            playlist += f"{req.url}\n"

    return playlist

# -----------------------
# Main
# -----------------------
async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s"
    )

    headless_mode = os.getenv("HEADLESS", "true").lower() == "true"

    async with aiohttp.ClientSession() as session:
        raw_streams = await fetch_streams(session)
        streams = normalize_streams(raw_streams)
        logging.info(f"Found {len(streams)} streams after normalization")

        async with async_playwright() as p:
            browser = await p.firefox.launch(
                headless=headless_mode,
                args=["--disable-dev-shm-usage"],
            )
            context = await browser.new_context()

            observations: List[StreamObservation] = []

            for s in streams:
                stream_id = str(s["id"])
                embed_url = f"https://ppv.to/embed/{stream_id}"

                page = await context.new_page()
                obs = StreamObservation(stream_id=stream_id, embed_url=embed_url)

                await scrape_embed(page, embed_url, obs)
                observations.append(obs)

                await page.close()
                await asyncio.sleep(1)

            playlist = build_safe_playlist(observations)
            with open("PPVLand.m3u8", "w", encoding="utf-8") as f:
                f.write(playlist)

            found = len([o for o in observations if o.verdict == "hls_observed"])
            logging.info(f"Saved playlist with {found} streams")

            await context.close()
            await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
