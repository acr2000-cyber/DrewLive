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
            normalized.append({"id": str(
