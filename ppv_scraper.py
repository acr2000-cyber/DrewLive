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

# Default User-Agent string used when appending params to the URL
DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:143.0) Gecko/20100101 Firefox/143.0"

ALLOWED_CATEGORIES = {
    "24/7 Streams", "Wrestling", "Football", "Basketball", "Baseball",
    "Combat Sports", "American Football", "Darts", "Motorsports", "Ice Hockey",
    "Miscellaneous"
}

CATEGORY_LOGOS = {
    "24/7 Streams": "http://drewlive24.duckdns.org:9000/Logos/247.png",
    "Wrestling": "http://drewlive24.duckdns.org:9000/Logos/Wrestling.png",
    "Football": "http://drewlive24.duckdns.org:9000/Logos/Football.png",
    "Basketball": "http://drewlive24.duckdns.org:9000/Logos/Basketball.png",
    "Baseball": "http://drewlive24.duckdns.org:9000/Logos/Baseball.png",
    "American Football": "http://drewlive24.duckdns.org:9000/Logos/NFL3.png",
    "Combat Sports": "http://drewlive24.duckdns.org:9000/Logos/CombatSports2.png",
    "Live Now": "http://drewlive24.duckdns.org:9000/Logos/DrewLiveSports.png",
    "Ice Hockey": "http://drewlive24.duckdns.org:9000/Logos/Hockey.png",
    "Miscellaneous": "http://drewlive24.duckdns.org:9000/Logos/DrewLiveSports.png"
}

CATEGORY_TVG_IDS = {
    "24/7 Streams": "24.7.Dummy.us",
    "Wrestling": "PPV.EVENTS.Dummy.us",
    "Football": "Soccer.Dummy.us",
    "Basketball": "Basketball.Dummy.us",
    "Baseball": "MLB.Baseball.Dummy.us",
    "American Football": "NFL.Dummy.us",
    "Combat Sports": "PPV.EVENTS.Dummy.us",
    "Darts": "Darts.Dummy.us",
    "Motorsports": "Racing.Dummy.us",
    "Live Now": "24.7.Dummy.us",
    "Ice Hockey": "NHL.Hockey.Dummy.us",
    "Miscellaneous": "24.7.Dummy.us"
}

GROUP_RENAME_MAP = {
    "24/7 Streams": "PPVLand - Live Channels 24/7",
    "Wrestling": "PPVLand - Wrestling Events",
    "Football": "PPVLand - Global Football Streams",
    "Basketball": "PPVLand - Basketball Hub",
    "Baseball": "PPVLand - MLB",
    "American Football": "PPVLand - NFL Action",
    "Combat Sports": "PPVLand - Combat Sports",
    "Darts": "PPVLand - Darts",
    "Motorsports": "PPVLand - Racing Action",
    "Live Now": "PPVLand - Live Now",
    "Ice Hockey": "PPVLand - NHL Action",
    "Miscellaneous": "PPVLand - Random Events"
}

NFL_TEAMS = {
    "arizona cardinals", "atlanta falcons", "baltimore ravens", "buffalo bills",
    "carolina panthers", "chicago bears", "cincinnati bengals", "cleveland browns",
    "dallas cowboys", "denver broncos", "detroit lions", "green bay packers",
    "houston texans", "indianapolis colts", "jacksonville jaguars", "kansas city chiefs",
    "las vegas raiders", "los angeles chargers", "los angeles rams", "miami dolphins",
    "minnesota vikings", "new england patriots", "new orleans saints", "new york giants",
    "new york jets", "philadelphia eagles", "pittsburgh steelers", "san francisco 49ers",
    "seattle seahawks", "tampa bay buccaneers", "tennessee titans", "washington commanders"
}

COLLEGE_TEAMS = {
    "alabama crimson tide", "auburn tigers", "arkansas razorbacks", "georgia bulldogs",
    "florida gators", "lsu tigers", "ole miss rebels", "mississippi state bulldogs",
    "tennessee volunteers", "texas longhorns", "oklahoma sooners", "oklahoma state cowboys",
    "baylor bears", "tcu horned frogs", "kansas jayhawks", "kansas state wildcats",
    "iowa state cyclones", "iowa hawkeyes", "michigan wolverines", "ohio state buckeyes",
    "penn state nittany lions", "michigan state spartans", "wisconsin badgers",
    "minnesota golden gophers", "illinois fighting illini", "northwestern wildcats",
    "indiana hoosiers", "notre dame fighting irish", "usc trojans", "ucla bruins",
    "oregon ducks", "oregon state beavers", "washington huskies", "washington state cougars",
    "arizona wildcats", "stanford cardinal", "california golden bears", "colorado buffaloes",
    "florida state seminoles", "miami hurricanes", "clemson tigers", "north carolina tar heels",
    "duke blue devils", "nc state wolfpack", "wake forest demon deacons", "syracuse orange",
    "virginia cavaliers", "virginia tech hokies", "louisville cardinals", "pittsburgh panthers",
    "maryland terrapins", "rutgers scarlet knights", "nebraska cornhuskers", "purdue boilermakers",
    "texas a&m aggies", "kentucky wildcats", "missouri tigers", "vanderbilt commodores",
    "houston cougars", "utah utes", "byu cougars", "boise state broncos", "san diego state aztecs",
    "cincinnati bearcats", "memphis tigers", "ucf knights", "south florida bulls", "smu mustangs",
    "tulsa golden hurricane", "tulane green wave", "navy midshipmen", "army black knights",
    "arizona state sun devils", "texas tech red raiders", "florida atlantic owls"
}

def get_all_frames(frame):
    """Recursively get all frames including nested ones"""
    all_frames = [frame]
    for child in frame.child_frames:
        all_frames.extend(get_all_frames(child))
    return all_frames

async def grab_m3u8_from_iframe(page, iframe_url):
    """Enhanced stream detection with nested iframe support"""
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
        
        # Wait for iframes to load
        await asyncio.sleep(3)
        
        # Get all frames including nested ones
        all_frames = get_all_frames(page.main_frame)
        print(f"📊 Found {len(all_frames)} total frames (including nested)")
        for i, frame in enumerate(all_frames):
            print(f"  Frame {i}: {frame.url}")
        
        # Check for iframe elements in DOM
        iframe_elements = await page.query_selector_all('iframe')
        print(f"🔍 Found {len(iframe_elements)} iframe elements in DOM")
        for i, iframe in enumerate(iframe_elements):
            src = await iframe.get_attribute('src')
            print(f"  Iframe {i} src: {src}")
        
        # Check if there's a nested iframe we should navigate to
        nested_iframe_url = None
        for iframe in iframe_elements:
            src = await iframe.get_attribute('src')
            if src and src.startswith('http') and src != iframe_url:
                nested_iframe_url = src
                print(f"🔄 Found nested iframe: {nested_iframe_url}")
                break
        
        if nested_iframe_url:
            print(f"🌐 Navigating to nested iframe: {nested_iframe_url}")
            await page.goto(nested_iframe_url, wait_until="domcontentloaded", timeout=30000)
            
            try:
                await page.wait_for_load_state("networkidle", timeout=15000)
                print("✅ Network idle detected (nested iframe)")
            except:
                print("⚠️ Network idle timeout (nested iframe)")
            
            # Re-check frames after navigation
            all_frames = get_all_frames(page.main_frame)
            print(f"📊 Found {len(all_frames)} frames in nested iframe")
        
        # Scroll to trigger lazy loading
        try:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(1)
            await page.evaluate("window.scrollTo(0, 0)")
            print("✅ Scrolled page to trigger lazy loading")
        except:
            pass
        
        # Check for player-related content in HTML
        try:
            html_content = await page.content()
            player_indicators = ['video', 'player', 'stream', 'hls', 'm3u8', 'jwplayer', 'videojs']
            found_indicators = [ind for ind in player_indicators if ind in html_content.lower()]
            if found_indicators:
                print(f"✅ Player-related content detected: {', '.join(found_indicators)}")
        except:
            pass
        
        # Check for video elements in all frames
        video_found = False
        video_frame = None
        player_selectors = [
            "video", "video[src]", "video source", ".video-js", "#player video",
            ".plyr video", "[id*='video']", "[class*='video']", "iframe[src*='player']",
            ".jwplayer video", "#vplayer", ".vplayer", "[id*='player']", "[class*='player']"
        ]
        
        for frame in all_frames:
            try:
                for selector in player_selectors:
                    video = await frame.query_selector(selector)
                    if video:
                        print(f"✅ Video element found in frame with selector: {selector}")
                        video_found = True
                        video_frame = frame
                        break
                if video_found:
                    break
            except Exception:
                continue
        
        if not video_found:
            print("⚠️ No video element found in any frame")
        
        # Try interactions on the frame with video (or main page if not found)
        target = video_frame if video_frame else page
        interactions_attempted = []
        
        # 1. Click body to focus
        try:
            await target.evaluate('document.body.click()')
            interactions_attempted.append('body click')
            print("✅ Triggered: body click")
            await asyncio.sleep(1)
        except Exception as e:
            print(f"⚠️ Body click failed: {e}")
        
        # 2. Try common play button selectors
        play_button_selectors = [
            "button.play", ".vjs-big-play-button", "[aria-label*='Play']",
            "[aria-label*='play']", ".plyr__control--overlaid", ".jw-display-icon-container",
            "[class*='play-button']", "[id*='play-button']", "button[title*='Play']",
            ".play-button", "div.play-button", "div[class*='play']", "div[id*='play']"
        ]
        
        play_button_clicked = False
        for selector in play_button_selectors:
            try:
                play_button = await target.query_selector(selector)
                if play_button:
                    await play_button.click(timeout=3000)
                    interactions_attempted.append(f'play button ({selector})')
                    print(f"✅ Clicked play button: {selector}")
                    play_button_clicked = True
                    await asyncio.sleep(2)
                    break
            except:
                continue
        
        if not play_button_clicked:
            print("⚠️ Could not find/click any play button")
        
        # 3. Try JavaScript play() method
        try:
            await target.evaluate("""
                () => {
                    const videos = document.querySelectorAll('video');
                    videos.forEach(v => {
                        v.muted = false;
                        v.volume = 1.0;
                        v.play().catch(e => console.log('Play failed:', e));
                    });
                    
                    if (window.player && typeof window.player.play === 'function') {
                        window.player.play();
                    }
                    
                    if (window.jwplayer && typeof window.jwplayer === 'function') {
                        try { window.jwplayer().play(); } catch(e) {}
                    }
                    
                    if (window.videojs) {
                        try {
                            const players = document.querySelectorAll('.video-js');
                            players.forEach(p => {
                                const player = window.videojs(p.id);
                                if (player) player.play();
                            });
                        } catch(e) {}
                    }
                }
            """)
            interactions_attempted.append('JS play()')
            print("✅ Triggered: JavaScript play() method")
            await asyncio.sleep(2)
        except Exception as e:
            print(f"⚠️ JavaScript play() failed: {e}")
        
        # 4. Try keyboard space
        try:
            await page.keyboard.press("Space")
            interactions_attempted.append('keyboard space')
            print("✅ Triggered: keyboard space")
            await asyncio.sleep(1)
        except Exception as e:
            print(f"⚠️ Keyboard space failed: {e}")
        
        # 5. Try clicking center of viewport
        try:
            viewport = page.viewport_size
            if viewport:
                center_x = viewport['width'] // 2
                center_y = viewport['height'] // 2
                await target.mouse.click(center_x, center_y)
                interactions_attempted.append('center click')
                print(f"✅ Triggered: center click ({center_x}, {center_y})")
                await asyncio.sleep(2)
        except Exception as e:
            print(f"⚠️ Center click failed: {e}")
        
        # Wait for stream to initialize
        await asyncio.sleep(3)
        
        # Check if video is playing
        try:
            is_playing = await target.evaluate("""
                () => {
                    const video = document.querySelector('video');
                    return video && !video.paused && !video.ended && video.readyState > 2;
                }
            """)
            if is_playing:
                print("✅ Video is playing!")
            else:
                print("⚠️ Video element exists but may not be playing")
        except:
            print("⚠️ Could not verify video playback state")
        
        print(f"📝 Interactions attempted: {', '.join(interactions_attempted)}")
        
        # Extended wait for stream request
        print("⏳ Waiting for stream to be requested (max 60s)...")
        try:
            await page.wait_for_event(
                "response",
                lambda resp: ".m3u8" in resp.url,
                timeout=60000
            )
            print("✅ M3U8 stream detected. Proceeding immediately to validation.")
        except PlaywrightTimeoutError:
            print("⚠️ Stream request did not start within 60 seconds. Checking for streams anyway...")
        except Exception as e:
            print(f"❌ Failed during wait for M3U8 event: {e}")

        # Final wait to capture late-loading streams
        await asyncio.sleep(5)

        page.remove_listener("request", handle_request)
        page.remove_listener("response", handle_response)

        if not found_streams:
            print(f"❌ No M3U8 URLs were captured for {iframe_url}")
            return set()

        valid_urls = set()
        tasks = [check_m3u8_url(url, iframe_url) for url in found_streams]
        results = await asyncio.gather(*tasks)
        
        for url, is_valid in zip(found_streams, results):
            if is_valid:
                valid_urls.add(url)
            else:
                print(f"🗑️ Discarding invalid or unreachable URL: {url}")
                
        return valid_urls
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
