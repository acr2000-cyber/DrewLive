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
# Data models (pure data, no scraping logic)
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
# API phase
# --------------------------------------------------

async def fetch_streams(session: aiohttp.ClientSession) -> list[dict]:
    async with session.get(API_URL, headers=REQUEST_HEADERS) as resp:
        if resp.status != 200:
            logger.error(f"API failed with status {resp.status}")
            return []
        return await resp.json()


# --------------------------------------------------
# Observation phase
# --------------------------------------------------

async def observe_embed(page: Page, stream_id: str, embed_url: str) -> StreamObservation:
    obs = StreamObservation(stream_id=stream_id, embed_url=embed_url)

    def on_request(req):
        obs.requests.append(
            NetworkEvent(
                ts=time.time(),
                url=req.url,
                method=req.method,
                resource_type=req.resource_type,
            )
        )

    def on_response(res):
        obs.responses.append(
            NetworkEvent(
                ts=time.time(),
                url=res.url,
                method=res.request.method,
                resource_type=res.request.resource_type,
                status=res.status,
            )
        )

    page.on("request", on_request)
    page.on("response", on_response)

    logger.info(f"▶ Observing embed {stream_id}")
    await page.goto(embed_url, wait_until="domcontentloaded")

    # Minimal playback intent (no brute force, no loops)
    try:
        await page.mouse.click(400, 300, timeout=3000)
    except Exception:
        pass

    # Observation window
    await asyncio.sleep(6)

    classify_observation(obs)
    return obs


# --------------------------------------------------
# Classification phase
# --------------------------------------------------

def classify_observation(obs: StreamObservation) -> None:
    media_requests = [
        r for r in obs.requests
        if r.resource_type in ("media", "xhr", "fetch")
    ]

    m3u8 = [r for r in media_requests if ".m3u8" in r.url]
    blobs = [r for r in media_requests if r.url.startswith("blob:")]

    if m3u8:
        obs.verdict = "hls_observed"
        obs.notes = f"{len(m3u8)} playlist request(s)"
    elif blobs:
        obs.verdict = "media_blob_based"
        obs.notes = "MediaSource / blob transport"
    elif media_requests:
        obs.verdict = "media_no_playlist"
        obs.notes = "Media requested without HLS"
    elif obs.requests:
        obs.verdict = "no_media_activity"
        obs.notes = "Only static resources"
    else:
