import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import List, Optional

import aiohttp
from playwright.async_api import async_playwright, Page, Browser, BrowserContext, Route

logger = logging.getLogger(__name__)

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


# -------------------------
# Data models
# -------------------------
@dataclass
class NetworkEvent:
    ts: float
    url: str
    method: str


@dataclass
class StreamObservation:
    stream_id: str
    embed_url: str
    requests: List[NetworkEvent] = field(default_factory=list)
    verdict: str = "unknown"


# -------------------------
# API helpers
# -------------------------
async def fetch_streams(session: aiohttp.ClientSession) -> List[dict]:
    async with session.get(API_URL, headers=REQUEST_HEADERS) as resp:
        if resp.status != 200:
            logger.error(f"API failed with status {resp.status}")
            return []
        return [s if isinstance(s, dict) else {"id": str(s)} for s in await resp.json()]


async def get_embed_url(session: aiohttp.ClientSession, stream_id: str) -> Optional[str]:
    url = f"https://ppv.to/embed/{stream_id}"
    try:
        async with session.head(url, headers=REQUEST_HEADERS, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 200:
                return url
    except Exception as e:
        logger.debug(f"Embed URL check failed: {e}")
    return None


# -------------------------
# Scraping helpers
# -------------------------
async def scrape_embed(page: Page, embed_url: str) -> List[str]:
    """Intercept .m3u8 requests using Playwright"""
    m3u8_urls: List[str] = []

    async def intercept(route: Route):
        if ".m3u8" in route.request.url:
            m3u8_urls.append(route.request.url)
        await route.continue_()

    await page.route("**/*", intercept)
    try:
        await page.goto(embed_url, wait_until="networkidle", timeout=30_000)
        await asyncio.sleep(2)  # allow streams to start
    except Exception as e:
        logger.warning(f"Failed to load {embed_url}: {e}")
    finally:
        await page.unroute("**/*", intercept)

    return m3u8_urls


# -------------------------
# Playlist builder
# -------------------------
def build_safe_playlist(observations: List[StreamObservation]) -> str:
    playlist = "#EXTM3U\n"
    for obs in observations:
        if obs.verdict != "hls_observed" or not obs.requests:
            continue
        url = obs.requests[0].url
        headers = "|".join(CUSTOM_HEADERS)
        playlist += f'#EXTINF:-1 tvg-name="{obs.stream_id}",{obs.stream_id}\n{url}|{headers}\n'
    return playlist


# -------------------------
# Process a single stream concurrently
# -------------------------
async def process_stream(session: aiohttp.ClientSession, browser: Browser, stream: dict) -> StreamObservation:
    stream_id = str(stream["id"])
    embed_url = await get_embed_url(session, stream_id)
    obs = StreamObservation(stream_id=stream_id, embed_url=embed_url or "")
    if not embed_url:
        return obs

    context: BrowserContext = await browser.new_context()
    page: Page = await context.new_page()
    try:
        m3u8_urls = await scrape_embed(page, embed_url)
        if m3u8_urls:
            obs.verdict = "hls_observed"
            for u in m3u8_urls:
                obs.requests.append(NetworkEvent(time.time(), u, "GET"))
    except Exception as e:
        logger.warning(f"Error scraping {embed_url}: {e}")
    finally:
        await page.close()
        await context.close()

    return obs


# -------------------------
# Main
# -------------------------
async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    async with aiohttp.ClientSession() as session:
        raw_streams = await fetch_streams(session)
        logger.info(f"Found {len(raw_streams)} streams")

        async with async_playwright() as p:
            browser = await p.firefox.launch(headless=True)

            # Limit concurrency to avoid overwhelming CPU/memory
            semaphore = asyncio.Semaphore(4)

            async def sem_process(s):
                async with semaphore:
                    return await process_stream(session, browser, s)

            tasks = [sem_process(s) for s in raw_streams]
            observations = await asyncio.gather(*tasks)

            playlist = build_safe_playlist(observations)
            with open("ppv_streams.m3u", "w", encoding="utf-8") as f:
                f.write(playlist)

            logger.info(f"Saved playlist with {len([o for o in observations if o.verdict=='hls_observed'])} streams")
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
