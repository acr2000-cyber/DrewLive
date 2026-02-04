
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
    "Darts", "Motorsports", "Ice Hockey", "Miscellaneous"
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
            if attempt == 0:
                print(f"🔍 Found {len(iframes)} iframes on initial check")
            
            for idx, iframe in enumerate(iframes):
                src = await iframe.get_attribute('src')
                if src and src.startswith('http'):
                    print(f"✅ iframe src populated after {attempt * delay:.1f}s: {src}")
                    return src
                elif attempt % 10 == 0:  # Log every 5 seconds
                    print(f"⏳ Attempt {attempt}: iframe {idx} src = {src or 'empty'}")
        except Exception as e:
            if attempt % 10 == 0:
                print(f"⚠️ Error checking iframes at attempt {attempt}: {e}")
        await asyncio.sleep(delay)
    
    print(f"⚠️ iframe src did not populate after {max_attempts * delay:.1f}s")
    return None

async def grab_m3u8_from_iframe(page, iframe_url):
    """Enhanced stream detection with dynamic iframe loading support"""
    found_streams = set()
    
    def handle_request(request):
        url = request.url
        if ".m3u8" in url:
            print(f"🎯 M3U8 in REQUEST: {url}")
            found_streams.add(url)
    
    def handle_response(response):
        url = response.url
        content_type = response.headers.get('content-type', '').lower()
        
        if ".m3u8" in url or "mpegurl" in content_type or "application/vnd.apple.mpegurl" in content_type:
            print(f"✅ Found M3U8 Stream: {url}")
            found_streams.add(url)
        elif ".ts" in url and "segment" in url.lower():
            print(f"🎬 Detected .ts segment (stream active): {url[:100]}...")

    page.on("request", handle_request)
    page.on("response", handle_response)
    
    print(f"🌐 Navigating to iframe: {iframe_url}")
    
    try:
        await page.goto(iframe_url, wait_until="domcontentloaded", timeout=30000)
        print("✅ Page loaded (domcontentloaded)")
        
        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
            print("✅ Network idle detected")
        except:
            print("⚠️ Network idle timeout - continuing anyway")
        
        # Aggressive interaction to trigger lazy-loaded content
        print("🖱️ Triggering interactions to load player...")
        try:
            viewport = page.viewport_size
            center_x = viewport['width'] // 2
            center_y = viewport['height'] // 2
            await page.mouse.move(center_x, center_y)
            await page.mouse.click(center_x, center_y)
            await asyncio.sleep(2)
        except Exception as e:
            print(f"⚠️ Interaction failed: {e}")
        
        # DEBUG: Check page content
        html = await page.content()
        iframe_count = html.count('<iframe')
        print(f"🔍 Page HTML length: {len(html)} bytes, Iframes: {iframe_count}")
        
        # Wait for iframe src to be populated
        nested_iframe_url = await wait_for_iframe_src(page, max_attempts=40, delay=0.5)
        
        if nested_iframe_url and nested_iframe_url != iframe_url:
            print(f"🔄 Found nested iframe: {nested_iframe_url}")
            await page.goto(nested_iframe_url, wait_until="domcontentloaded", timeout=30000)
            try:
                await page.wait_for_load_state("networkidle", timeout=15000)
            except:
                print("⚠️ Network idle timeout (nested)")
            await asyncio.sleep(2)
        
        # Check for video elements
        all_frames = get_all_frames(page.main_frame)
        print(f"📊 Found {len(all_frames)} total frames")
        
        video_found = False
        for frame in all_frames:
            try:
                video = await frame.query_selector('video')
                if video:
                    print("✅ Video element found")
                    video_found = True
                    break
            except
			
async def wait_for_video_element(target, max_attempts=20, delay=0.5):
    """Poll for video element to appear after interactions"""
    for attempt in range(max_attempts):
        try:
            video = await target.query_selector('video')
            if video:
                print(f"✅ Video element appeared after {attempt * delay:.1f}s")
                return video
        except:
            pass
        await asyncio.sleep(delay)
    
    print(f"⚠️ Video element did not appear after {max_attempts * delay:.1f}s")
    return None


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
            print(f"🌐 Fetching streams from {API_URL}")
            async with session.get(API_URL) as resp:
                print(f"🔍 Response status: {resp.status}")
                if resp.status != 200:
                    error_text = await resp.text()
                    print(f"❌ Error response: {error_text[:500]}")
                    return None
                return await resp.json()
    except Exception as e:
        print(f"❌ Error in get_streams: {str(e)}")
        return None

async def grab_live_now_from_html(page, base_url="https://ppv.to/"):
    print("🌐 Scraping 'Live Now' streams from HTML...")
    live_now_streams = []
    try:
        await page.goto(base_url, timeout=20000)
        await asyncio.sleep(3)

        live_cards = await page.query_selector_all("#livecards a.item-card")
        for card in live_cards:
            href = await card.get_attribute("href")
            name_el = await card.query_selector(".card-title")
            poster_el = await card.query_selector("img.card-img-top")
            name = await name_el.inner_text() if name_el else "Unnamed Live"
            poster = await poster_el.get_attribute("src") if poster_el else None

            if href:
                iframe_url = f"{base_url.rstrip('/')}{href}"
                live_now_streams.append({
                    "name": name.strip(),
                    "iframe": iframe_url,
                    "category": "Live Now",
                    "poster": poster
                })
    except Exception as e:
        print(f"❌ Failed scraping 'Live Now': {e}")

    print(f"✅ Found {len(live_now_streams)} 'Live Now' streams")
    return live_now_streams

def _encode_param(value: str) -> str:
    """Percent-encode a header value for use in the pipe params"""
    return urllib.parse.quote(value or "", safe='')

def build_m3u(streams, url_map):
    """Build M3U formatted output compatible with Kodi-style playlist entries."""
    lines = ['#EXTM3U url-tvg="https://epgshare01.online/epgshare01/epg_ripper_DUMMY_CHANNELS.xml.gz"']
    seen_names = set()
    
    for s in streams:
        name_lower = s["name"].strip().lower()
        if name_lower in seen_names:
            continue
        seen_names.add(name_lower)

        unique_key = f"{s['name']}::{s['category']}::{s['iframe']}"
        urls = url_map.get(unique_key, [])
        if not urls:
            print(f"⚠️ No working URLs for {s['name']}")
            continue

        orig_category = s.get("category") or "Misc"
        final_group = GROUP_RENAME_MAP.get(orig_category, f"PPVLand - {orig_category}")
        logo = s.get("poster") or CATEGORY_LOGOS.get(orig_category, "http://drewlive24.duckdns.org:9000/Logos/Default.png")
        tvg_id = CATEGORY_TVG_IDS.get(orig_category, "Misc.Dummy.us")

        url = next(iter(urls))

        try:
            referer = s.get("iframe") or ""
            origin = "https://" + referer.split('/') if referer else "https://ppv.to"
        except Exception:
            origin = "https://ppv.to"

        ua_enc = _encode_param(DEFAULT_UA)
        ref_enc = _encode_param(referer)
        origin_enc = _encode_param(origin)

        param_str = f"|User-Agent={ua_enc}&Referer={ref_enc}&Origin={origin_enc}"

        lines.append(f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-logo="{logo}" group-title="{final_group}",{s["name"]}')
        lines.append(f'{url}{param_str}')
    
    return "\n".join(lines)

async def main():
    print("🚀 Starting PPV Stream Fetcher")
    data = await get_streams()
    if not data or 'streams' not in data:
        print("❌ No valid data received from the API")
        if data:
            print(f"API Response: {data}")
        return

    print(f"✅ Found {len(data['streams'])} categories")
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

    # Deduplicate streams
    seen_names = set()
    deduped_streams = []
    for s in streams:
        name_key = s["name"].strip().lower()
        if name_key not in seen_names:
            seen_names.add(name_key)
            deduped_streams.append(s)
    streams = deduped_streams

    async with async_playwright() as p:
        browser = await p.firefox.launch(
            headless=True,
            firefox_user_prefs={
                "media.autoplay.default": 0,
                "media.autoplay.blocking_policy": 0
            }
        )
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:143.0) Gecko/20100101 Firefox/143.0',
            locale='en-US',
            timezone_id='America/New_York'
        )
        page = await context.new_page()
        url_map = {}

        total_streams = len(streams)
        for idx, s in enumerate(streams, start=1):
            key = f"{s['name']}::{s['category']}::{s['iframe']}"
            print(f"\n🔎 Scraping stream {idx}/{total_streams}: {s['name']} ({s['category']})")
            try:
                urls = await grab_m3u8_from_iframe(page, s["iframe"])
                if urls:
                    print(f"✅ Got {len(urls)} stream(s) for {s['name']} ({idx}/{total_streams})")
                    url_map[key] = urls
                else:
                    print(f"⚠️ No valid streams for {s['name']} ({idx}/{total_streams})")
                    url_map[key] = set()
            except Exception as e:
                print(f"❌ Critical error for {s['name']}: {e}")
                url_map[key] = set()
            finally:
                if idx < total_streams:
                    await asyncio.sleep(2)

        # Scrape Live Now streams
        live_now_streams = await grab_live_now_from_html(page)
        for live_idx, s in enumerate(live_now_streams, start=total_streams+1):
            key = f"{s['name']}::{s['category']}::{s['iframe']}"
            print(f"\n🔎 Scraping 'Live Now' stream {live_idx}/{total_streams + len(live_now_streams)}: {s['name']} ({s['category']})")
            try:
                urls = await grab_m3u8_from_iframe(page, s["iframe"])
                if urls:
                    print(f"✅ Got {len(urls)} 'Live Now' stream(s) for {s['name']}")
                    url_map[key] = urls
                else:
                    print(f"⚠️ No valid 'Live Now' streams for {s['name']}")
                    url_map[key] = set()
            except Exception as e:
                print(f"❌ Critical error for {s['name']}: {e}")
                url_map[key] = set()
            finally:
                if live_idx < (total_streams + len(live_now_streams)):
                    await asyncio.sleep(2)

        streams.extend(live_now_streams)

        await browser.close()

    print("\n💾 Writing final playlist to PPVLand.m3u8 ...")
    playlist = build_m3u(streams, url_map)
    with open("PPVLand.m3u8", "w", encoding="utf-8") as f:
        f.write(playlist)
    print(f"✅ Done! Playlist saved as PPVLand.m3u8 at {datetime.utcnow().isoformat()} UTC")

if __name__ == "__main__":
    asyncio.run(main())
