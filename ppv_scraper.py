async def grab_m3u8_from_iframe(page, iframe_url):
    """Enhanced stream detection with better iframe and player handling"""
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
        # Navigate with longer timeout
        await page.goto(iframe_url, wait_until="domcontentloaded", timeout=30000)
        print("✅ Page loaded (domcontentloaded)")
        
        # Wait for network idle with timeout
        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
            print("✅ Network idle detected")
        except:
            print("⚠️ Network idle timeout - continuing anyway")
        
        # Check for nested iframes first
        await asyncio.sleep(2)
        frames = page.frames
        print(f"📊 Found {len(frames)} total frames")
        
        # Log all frame URLs for debugging
        for i, frame in enumerate(frames):
            frame_url = frame.url[:100] if frame.url else "about:blank"
            print(f"  Frame {i}: {frame_url}")
        
        # Try to find the actual player frame
        player_frame = None
        for frame in frames:
            frame_url = frame.url.lower()
            if any(keyword in frame_url for keyword in ['player', 'embed', 'stream', 'video']):
                if frame_url != iframe_url.lower():
                    print(f"🎯 Found potential player frame: {frame.url}")
                    player_frame = frame
                    break
        
        # Use player frame if found, otherwise use main page
        target = player_frame if player_frame else page
        
        # Scroll to trigger lazy loading
        try:
            await target.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(1)
            await target.evaluate("

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
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:142.0) Gecko/20100101 Firefox/142.0'
        }
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
    """
    Build M3U formatted output compatible with Kodi-style playlist entries.
    For each stream we append a single best URL followed by pipe-separated,
    percent-encoded header params: |User-Agent=...&Referer=...&Origin=...
    """
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

        if orig_category == "American Football":
            matched_team = None
            for team in NFL_TEAMS:
                if team in name_lower:
                    tvg_id = "NFL.Dummy.us"
                    final_group = "PPVLand - NFL Action"
                    matched_team = team
                    break
            if not matched_team:
                for team in COLLEGE_TEAMS:
                    if team in name_lower:
                        tvg_id = "NCAA.Football.Dummy.us"
                        final_group = "PPVLand - College Football"
                        matched_team = team
                        break

        # Pick the first available URL
        url = next(iter(urls))

        # Build the pipe-appended, percent-encoded header params
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
                    await asyncio.sleep(2)  # Delay between requests to avoid rate limiting

        live_now_streams = await grab_live_now_from_html(page)
        for s in live_now_streams:
            key = f"{s['name']}::{s['category']}::{s['iframe']}"
            print(f"\n🔎 Scraping 'Live Now' stream {idx+1}/{total_streams}: {s['name']} ({s['category']})")
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
                if idx < total_streams:
                    await asyncio.sleep(2)  # Delay between requests to avoid rate limiting

        streams.extend(live_now_streams)

        await browser.close()

    print("\n💾 Writing final playlist to PPVLand.m3u8 ...")
    playlist = build_m3u(streams, url_map)
    with open("PPVLand.m3u8", "w", encoding="utf-8") as f:
        f.write(playlist)
    print(f"✅ Done! Playlist saved as PPVLand.m3u8 at {datetime.utcnow().isoformat()} UTC")
    
    # NEW: Write VLC-compatible file
    print("\n💾 Writing VLC-compatible playlist to PPVLand_vlc.m3u8 ...")
    vlc_lines = ['#EXTM3U']
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

        if orig_category == "American Football":
            matched_team = None
            for team in NFL_TEAMS:
                if team in name_lower:
                    tvg_id = "NFL.Dummy.us"
                    final_group = "PPVLand - NFL Action"
                    matched_team = team
                    break
            if not matched_team:
                for team in COLLEGE_TEAMS:
                    if team in name_lower:
                        tvg_id = "NCAA.Football.Dummy.us"
                        final_group = "PPVLand - College Football"
                        matched_team = team
                        break

        # Pick the first available URL
        url = next(iter(urls))

        # Build the VLC-compatible header parameters
        try:
            referer = s.get("iframe") or ""
            origin = "https://" + referer.split('/') if referer else "https://ppv.to"
        except Exception:
            origin = "https://ppv.to"

        ua_enc = _encode_param(DEFAULT_UA)
        ref_enc = _encode_param(referer)
        origin_enc = _encode_param(origin)

        # Create VLC-compatible header parameters
        vlc_params = f"|User-Agent={ua_enc}&Referer={ref_enc}&Origin={origin_enc}"

        vlc_lines.append(f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-logo="{logo}" group-title="{final_group}",{s["name"]}')
        vlc_lines.append(f'{url}{vlc_params}')
    
    with open("PPVLand_vlc.m3u8", "w", encoding="utf-8") as f:
        f.write("\n".join(vlc_lines))
    print(f"✅ Done! VLC-compatible playlist saved as PPVLand_vlc.m3u8 at {datetime.utcnow().isoformat()} UTC")


if __name__ == "__main__":
    asyncio.run(main())
