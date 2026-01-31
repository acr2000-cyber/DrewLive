import json
import asyncio
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
import aiohttp
from datetime import datetime
import re
import urllib.parse

API_URL = "https://ppv.to/api/streams"

CUSTOM_HEADERS = [
    '#EXTVLCOPT:http-origin=https://ppv.to',
    '#EXTVLCOPT:http-referrer=https://ppv.to/',
    '#EXTVLCOPT:http-user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:143.0) Gecko/20100101 Firefox/143.0'
]

DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:143.0) Gecko/20100101 Firefox/143.0"

ALLOWED_CATEGORIES = {
    "24/7 Streams", "Wrestling", "Basketball", "Combat Sports",
    "Darts", "Motorsports", "Ice Hockey",
    "Miscellaneous"
}

CATEGORY_LOGOS = {
    "24/7 Streams": "http://drewlive24.duckdns.org:9000/Logos/247.png",
    "Wrestling": "http://drewlive24.duckdns.org:9000/Logos/Wrestling.png",
    "Basketball": "http://drewlive24.duckdns.org:9000/Logos/Basketball.png",
    "Combat Sports": "http://drewlive24.duckdns.org:9000/Logos/CombatSports2.png",
    "Darts": "http://drewlive24.duckdns.org:9000/Logos/Darts.png",
    "Motorsports": "http://drewlive24.duckdns.org:9000/Logos/Racing.Dummy.us.png",
    "Ice Hockey": "http://drewlive24.duckdns.org:9000/Logos/Hockey.png",
    "Miscellaneous": "http://drewlive24.duckdns.org:9000/Logos/DrewLiveSports.png"
}

CATEGORY_TVG_IDS = {
    "24/7 Streams": "24.7.Dummy.us",
    "Wrestling": "PPV.EVENTS.Dummy.us",
    "Basketball": "Basketball.Dummy.us",
    "Combat Sports": "PPV.EVENTS.Dummy.us",
    "Darts": "Darts.Dummy.us",
    "Motorsports": "Racing.Dummy.us",
    "Ice Hockey": "NHL.Hockey.Dummy.us",
    "Miscellaneous": "24.7.Dummy.us"
}

GROUP_RENAME_MAP = {
    "24/7 Streams": "PPVLand - Live Channels 24/7",
    "Wrestling": "PPVLand - Wrestling Events",
    "Basketball": "PPVLand - Basketball Hub",
    "Combat Sports": "PPVLand - Combat Sports",
    "Darts": "PPVLand - Darts",
    "Motorsports": "PPVLand - Racing Action",
    "Ice Hockey": "PPVLand - NHL Action",
    "Miscellaneous": "PPVLand - Random Events"
}

def get_all_frames(frame):
    """Recursively get all frames including nested ones"""
    all_frames = [frame]
    for child in frame.child_frames:
        all_frames.extend(get_all_frames(child))
    return all_frames

async def wait_for_iframe_src(page, max_attempts=30, delay=0.5):
    """Poll for iframe src attribute to be populated by JavaScript"""
    for attempt in range(max_attempts):
        try:
            iframes = await page.query_selector_all('iframe')
            for iframe in iframes:
                src = await iframe.get_attribute('src')
                if src and src.startswith('http'):
                    return src
        except:
            pass
        await asyncio.sleep(delay)
    return None

async def wait_for_video_element(target, max_attempts=20, delay=0.5):
    """Poll for video element to appear after interactions"""
    for attempt in range(max_attempts):
        try:
            video = await target.query_selector('video')
            if video:
                return video
        except:
            pass
        await asyncio.sleep(delay)
    return None

async def grab_m3u8_from_iframe(page, iframe_url):
    """Enhanced stream detection with dynamic iframe loading support"""
    found_streams = set()
    
    def handle_request(request):
        url = request.url
        if ".m3u8" in url:
            found_streams.add(url)
    
    def handle_response(response):
        url = response.url
        content_type = response.headers.get('content-type', '').lower()
        if ".m3u8" in url or "mpegurl" in content_type or "application/vnd.apple.mpegurl" in content_type:
            found_streams.add(url)
        elif ".ts" in url and "segment" in url.lower():
            print(f"🎬 Detected .ts segment (stream active): {url[:100]}...")

    page.on("request", handle_request)
    page.on("response", handle_response)
    
    try:
        await page.goto(iframe_url, wait_until="domcontentloaded", timeout=30000)
        print("✅ Page loaded (domcontentloaded)")
        
        # Wait for network idle
        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
            print("✅ Network idle detected")
        except:
            print("⚠️ Network idle timeout - continuing anyway")
        
        # Wait for iframe src to be populated
        nested_iframe_url = await wait_for_iframe_src(page, max_attempts=30, delay=0.5)
        
        if nested_iframe_url and nested_iframe_url != iframe_url:
            print(f"🔄 Found populated nested iframe: {nested_iframe_url}")
            await page.goto(nested_iframe_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)
        
        # Check for video elements
        all_frames = get_all_frames(page.main_frame)
        for frame in all_frames:
            try:
                video = await frame.query_selector('video')
                if video:
                    print("✅ Video element found")
                    break
            except:
                continue
        
        # Try interactions
        try:
            await page.evaluate("""
                () => {
                    const videos = document.querySelectorAll('video');
                    videos.forEach(v => {
                        v.muted = false;
                        v.volume = 1.0;
                        v.play().catch(e => console.log('Play failed:', e));
                    });
                }
            """)
            print("✅ Triggered: JavaScript play() method")
        except:
            pass
        
        # Wait for video element
        video_element = await wait_for_video_element(page, max_attempts=20, delay=0.5)
        
        # Wait for stream request
        try:
            await page.wait_for_event("response", lambda resp: ".m3u8" in resp.url, timeout=60000)
            print("✅ M3U8 stream detected")
        except:
            print("⚠️ Stream request did not start within 60 seconds")
        
        # Final check
        await asyncio.sleep(5)
        
        page.remove_listener("request", handle_request)
        page.remove_listener("response", handle_response)
        
        return found_streams
        
    except Exception as e:
        print(f"❌ Error in grab_m3u8_from_iframe: {e}")
        return set()

async def check_m3u8_url(url, referer):
    """Checks the M3U8 URL using the correct referer for validation."""
    if "gg.poocloud.in" in url:
        return True
    try:
        origin = "https://" + referer.split('/') if referer else "https://ppv.to"
        headers = {
            "User-Agent": DEFAULT_UA,
            "Referer": referer,
            "Origin": origin
        }
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(url, headers=headers) as resp:
                return resp.status in [200, 403]
    except Exception as e:
        print(f"❌ Error checking {url}: {e}")
        return False

async def get_streams():
    try:
        timeout = aiohttp.ClientTimeout(total=30)
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:142.0) Gecko/20100101 Firefox/142.0'}
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(API_URL) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    print(f"❌ Error response: {error_text[:500]}")
                    return None
                return await resp.json()
    except Exception as e:
        print(f"❌ Error in get_streams: {str(e)}")
        return None

async def main():
    print("🚀 Starting PPV Stream Fetcher")
    data = await get_streams()
    if not data or 'streams' not in data:
        print("❌ No valid data received from the API")
        return

    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True)
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:143.0) Gecko/20100101 Firefox/143.0',
            locale='en-US',
            timezone_id='America/New_York'
        )
        page = await context.new_page()
        
        # Get streams from API
        streams = []
        for category in data.get("streams", []):
            cat = category.get("category", "").strip() or "Misc"
            if cat not in ALLOWED_CATEGORIES:
                ALLOWED_CATEGORIES.add(cat)
            for stream in category.get("streams", []):
                iframe = stream.get("iframe") 
                name = stream.get("name", "Unnamed Event")
                poster = stream.get("poster")
                if iframe:
                    streams.append({
                        "name": name,
                        "iframe": iframe,
                        "category": cat,
                        "poster": poster
                    })
        
        # Process streams
        url_map = {}
        for idx, s in enumerate(streams, start=1):
            key = f"{s['name']}::{s['category']}::{s['iframe']}"
            print(f"\n🔎 Scraping stream {idx}/{len(streams)}: {s['name']} ({s['category']})")
            try:
                urls = await grab_m3u8_from_iframe(page, s["iframe"])
                url_map[key] = urls
            except Exception as e:
                print(f"❌ Critical error for {s['name']}: {e}")
                url_map[key] = set()
            finally:
                if idx < len(streams):
                    await asyncio.sleep(2)
        
        # Build playlist
        playlist = build_m3u(streams, url_map)
        with open("PPVLand.m3u8", "w", encoding="utf-8") as f:
            f.write(playlist)
        print(f"✅ Done! Playlist saved as PPVLand.m3u8 at {datetime.utcnow().isoformat()} UTC")

if __name__ == "__main__":
    asyncio.run(main())
