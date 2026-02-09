import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import List, Dict, Optional

import aiohttp
from playwright.async_api import async_playwright, Page

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

# --------------------------------------------------
# Data models
# --------------------------------------------------

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
    responses: List[NetworkEvent] = field(default_factory=list)
    verdict: str = "unknown"
    notes: Optional[str] = None


# --------------------------------------------------
# API helpers
# --------------------------------------------------

async def fetch_streams(session: aiohttp.ClientSession) -> list[dict]:
    async with session.get(API_URL, headers=REQUEST_HEADERS) as resp:
        if resp.status != 200:
            logger.error(f"API failed with status {resp.status}")
            return []
        return await resp.json()


def normalize_streams(raw: list) -> list[dict]:
    """Ensure every stream is a dict with at least 'id'"""
    normalized = []
    for item in raw:
        if isinstance(item, dict):
            if "id" in item:
                normalized.append(item)
        elif isinstance(item, (str, int)):
            normalized.append({"id": str(item)})
        else:
            logger.warning(f"Unknown stream entry: {item}")
    return normalized


async def get_embed_url(session: aiohttp.ClientSession, stream_id: str) -> Optional[str]:
    url = f"https://ppv.to/embed/{stream_id}"
    try:
        async with session.head(url, headers=REQUEST_HEADERS, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 200:
                return url
    except Exception as e:
        logger.debug(f"Embed URL check failed: {e}")
    return None


# --------------------------------------------------
# Scraping helpers
# --------------------------------------------------

async def extract_m3u8_from_page(page: Page) -> List[str]:
    """Extract .m3u8 URLs observed on page"""
    urls = set()
    try:
        video_srcs = await page.evaluate(
            """() => Array.from(document.querySelectorAll('video, video source'))
                  .map(v => v.src || v.currentSrc)
                  .filter(u => u && u.includes('.m3u8'))"""
        )
        urls.update(video_srcs)

        # HLS.js detection
        hls_urls = await page.evaluate(
            """() => {
                const urls = [];
                if (window.hls && window.hls.media && window.hls.media.currentSrc) {
                    urls.push(window.hls.media.currentSrc);
                }
                if (window.Hls && window.Hls.version) {
                    document.querySelectorAll('script').forEach(s => {
                        const matches = s.textContent?.match(/https?:\/\/[^\s<>"']+\.m3u8[^\s<>"']*/g);
                        if (matches) urls.push(...matches);
                    });
                }
                return urls;
            }"""
        )
        urls.update(hls_urls)
    except Exception as e:
        logger.debug(f"extract_m3u8_from_page error: {e}")

    return list(urls)


async def scrape_embed(page: Page, embed_url: str) -> List[str]:
    try:
        await page.goto(embed_url, wait_until="domcontentloaded", timeout=30_000)
        await asyncio.sleep(2)
        return await extract_m3u8_from_page(page)
    except Exception as e:
        logger.warning(f"Scrape failed for {embed_url}: {e}")
        return []


# --------------------------------------------------
# Playlist builder
# --------------------------------------------------

def build_safe_playlist(observations: List[StreamObservation]) -> str:
    """Only include streams with HLS observed"""
    playlist = "#EXTM3U\n"
    for obs in observations:
        if obs.verdict != "hls_observed" or not obs.requests:
            continue
        url = obs.requests[0].url
        headers = "|".join(CUSTOM_HEADERS)
        playlist += f'#EXTINF:-1 tvg-name="{obs.stream_id}",{obs.stream_id}\n{url}|{headers}\n'
    return playlist


# --------------------------------------------------
# Main
# --------------------------------------------------

async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    async with aiohttp.ClientSession() as session:
        raw_streams = await fetch_streams(session)
        streams = normalize_streams(raw_streams)
        logger.info(f"Found {len(streams)} streams after normalization")

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
                m3u8_urls = await scrape_embed(page, embed_url)
                if m3u8_urls:
                    obs.verdict = "hls_observed"
                    for u in m3u8_urls:
                        obs.requests.append(NetworkEvent(time.time(), u, "GET", "media"))

                observations.append(obs)
                await asyncio.sleep(1)  # rate limit

            # Build and save playlist
            playlist = build_safe_playlist(observations)
            with open("ppv_streams.m3u", "w", encoding="utf-8") as f:
                f.write(playlist)

            logger.info(f"Saved playlist with {len(observations)} streams")
            await page.close()
            await context.close()
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
