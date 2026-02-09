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

# -------------------------
# Data model (no logic)
# -------------------------

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


# -------------------------
# API phase
# -------------------------

async def fetch_streams(session: aiohttp.ClientSession) -> list[dict]:
    async with session.get(API_URL, headers=REQUEST_HEADERS) as resp:
        if resp.status != 200:
            logger.error("API failed")
            return []
        return await resp.json()


# -------------------------
# Observation phase
# -------------------------

async def observe_embed(page: Page, stream_id: str, embed_url: str) -> StreamObservation:
    obs = StreamObservation(stream_id=stream_id, embed_url=embed_url)

    def on_request(req):
        obs.requests.append(NetworkEvent(
            ts=time.time(),
            url=req.url,
            method=req.method,
            resource_type=req.resource_type
        ))

    def on_response(res):
        obs.responses.append(NetworkEvent(
            ts=time.time(),
            url=res.url,
            method=res.request.method,
            resource_type=res.request.resource_type,
            status=res.status
        ))

    page.on("request", on_request)
    page.on("response", on_response)

    logger.info(f"▶ Observing {embed_url}")
    await page.goto(embed_url, wait_until="domcontentloaded")

    # minimal playback intent (no brute force)
    try:
        await page.mouse.click(400, 300, timeout=3000)
    except Exception:
        pass

    # observation window
    await asyncio.sleep(6)

    classify_observation(obs)
    return obs


# -------------------------
# Classification phase
# -------------------------

def classify_observation(obs: StreamObservation) -> None:
    urls = [r.url for r in obs.requests]

    media = [r for r in obs.requests if r.resource_type in ("media", "xhr", "fetch")]
    m3u8 = [r for r in media if ".m3u8" in r.url]
    blobs = [r for r in media if r.url.startswith("blob:")]

    if m3u8:
        obs.verdict = "hls_observed"
        obs.notes = f"{len(m3u8)} playlist request(s)"
    elif blobs:
        obs.verdict = "media_blob_based"
        obs.notes = "MediaSource / blob transport"
    elif media:
        obs.verdict = "media_no_playlist"
        obs.notes = "Media requested but no HLS"
    elif urls:
        obs.verdict = "no_media_activity"
        obs.notes = "Only static resources"
    else:
        obs.verdict = "no_network_activity"


# -------------------------
# Orchestration
# -------------------------

async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    async with aiohttp.ClientSession() as session:
        streams = await fetch_streams(session)

    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True)

        for s in streams:
            stream_id = str(s.get("id"))
            embed_url = f"https://ppv.to/embed/{stream_id}"

            context = await browser.new_context(extra_http_headers=REQUEST_HEADERS)
            page = await context.new_page()

            obs = await observe_embed(page, stream_id, embed_url)

            logger.info(
                f"[{stream_id}] verdict={obs.verdict} "
                f"requests={len(obs.requests)}"
            )

            await context.close()

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
