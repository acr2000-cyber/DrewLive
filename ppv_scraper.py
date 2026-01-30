import asyncio
from playwright.async_api import async_playwright

# Your existing constants and helper functions assumed here (get_all_frames, wait_for_video_element, etc.)

async def grab_m3u8_from_iframe(page, iframe_url):import json
import asyncio
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
import aiohttp
from datetime import datetime
import re
import urllib.parse

# Your existing constants and helper functions assumed here (get_all_frames, wait_for_video_element, etc.)

async def grab_m3u8_from_iframe(page, iframe_url):
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

        await asyncio.sleep(3)  # Wait for dynamic content

        all_frames = get_all_frames(page.main_frame)
        print(f"📊 Found {len(all_frames)} total frames (including nested)")
        for i, frame in enumerate(all_frames):
            print(f"  Frame {i}: {frame.url}")

        iframe_elements = await page.query_selector_all('iframe')
        print(f"🔍 Found {len(iframe_elements)} iframe elements in DOM")
        nested_iframe_url = None
        for iframe in iframe_elements:
            src = await iframe.get_attribute('src')
            print(f"  Iframe src: {src}")
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

        # Detect player-related content
        html_content = await page.content()
        player_indicators = ['video', 'player', 'stream', 'hls', 'm3u8', 'jwplayer', 'videojs']
        found_indicators = [ind for ind in player_indicators if ind in html_content.lower()]
        if found_indicators:
            print(f"✅ Player-related content detected: {', '.join(found_indicators)}")

        # Find video element in frames
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

        target = video_frame if video_frame else page
        interactions_attempted = []

        # 1. Try JS play() method
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

        # 2. Poll for video element to appear
        video_element = await wait_for_video_element(target, max_attempts=20, delay=0.5)

        # 3. Try clicking play buttons if video not playing
        if not video_element:
            play_button_selectors = [
                "button.play", ".vjs-big-play-button", "[aria-label='Play']", ".jw-icon-play",
                ".plyr__control--play", ".play-button", ".play-btn"
            ]
            for selector in play_button_selectors:
                try:
                    button = await target.query_selector(selector)
                    if button:
                        await button.click()
                        interactions_attempted.append(f'Clicked {selector}')
                        print(f"✅ Clicked play button: {selector}")
                        await asyncio.sleep(2)
                        # Check again for video element
                        video_element = await wait_for_video_element(target, max_attempts=10, delay=0.5)
                        if video_element:
                            break
                except Exception:
                    continue

        # 4. Additional interactions if needed (keyboard space, center click)
        if not video_element:
            try:
                await target.keyboard.press("Space")
                interactions_attempted.append('Keyboard space')
                print("✅ Triggered: keyboard space")
                await asyncio.sleep(2)
            except Exception:
                pass

            try:
                await target.mouse.click(960, 540)
                interactions_attempted.append('Center click')
                print("✅ Triggered: center click (960, 540)")
                await asyncio.sleep(2)
            except Exception:
                pass

        # Wait for stream request after interactions
        print(f"📝 Interactions attempted: {', '.join(interactions_attempted)}")
        print("⏳ Waiting for stream to be requested (max 60s)...")
        await asyncio.sleep(60)

        if found_streams:
            print(f"✅ Found {len(found_streams)} stream(s):")
            for stream_url in found_streams:
                print(f"  - {stream_url}")
        else:
            print("⚠️ No M3U8 URLs were captured")

        return list(found_streams)

    except Exception as e:
        print(f"❌ Error during scraping: {e}")
        return []

# Example usage
async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        streams = await grab_m3u8_from_iframe(page, "https://ppv.to/embed/example-stream")
        print("Streams found:", streams)
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())

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

        await asyncio.sleep(3)  # Wait for dynamic content

        all_frames = get_all_frames(page.main_frame)
        print(f"📊 Found {len(all_frames)} total frames (including nested)")
        for i, frame in enumerate(all_frames):
            print(f"  Frame {i}: {frame.url}")

        iframe_elements = await page.query_selector_all('iframe')
        print(f"🔍 Found {len(iframe_elements)} iframe elements in DOM")
        nested_iframe_url = None
        for iframe in iframe_elements:
            src = await iframe.get_attribute('src')
            print(f"  Iframe src: {src}")
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

        # Detect player-related content
        html_content = await page.content()
        player_indicators = ['video', 'player', 'stream', 'hls', 'm3u8', 'jwplayer', 'videojs']
        found_indicators = [ind for ind in player_indicators if ind in html_content.lower()]
        if found_indicators:
            print(f"✅ Player-related content detected: {', '.join(found_indicators)}")

        # Find video element in frames
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

        target = video_frame if video_frame else page
        interactions_attempted = []

        # 1. Try JS play() method
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

        # 2. Poll for video element to appear
        video_element = await wait_for_video_element(target, max_attempts=20, delay=0.5)

        # 3. Try clicking play buttons if video not playing
        if not video_element:
            play_button_selectors = [
                "button.play", ".vjs-big-play-button", "[aria-label='Play']", ".jw-icon-play",
                ".plyr__control--play", ".play-button", ".play-btn"
            ]
            for selector in play_button_selectors:
                try:
                    button = await target.query_selector(selector)
                    if button:
                        await button.click()
                        interactions_attempted.append(f'Clicked {selector}')
                        print(f"✅ Clicked play button: {selector}")
                        await asyncio.sleep(2)
                        # Check again for video element
                        video_element = await wait_for_video_element(target, max_attempts=10, delay=0.5)
                        if video_element:
                            break
                except Exception:
                    continue

        # 4. Additional interactions if needed (keyboard space, center click)
        if not video_element:
            try:
                await target.keyboard.press("Space")
                interactions_attempted.append('Keyboard space')
                print("✅ Triggered: keyboard space")
                await asyncio.sleep(2)
            except Exception:
                pass

            try:
                await target.mouse.click(960, 540)
                interactions_attempted.append('Center click')
                print("✅ Triggered: center click (960, 540)")
                await asyncio.sleep(2)
            except Exception:
                pass

        # Wait for stream request after interactions
        print(f"📝 Interactions attempted: {', '.join(interactions_attempted)}")
        print("⏳ Waiting for stream to be requested (max 60s)...")
        await asyncio.sleep(60)

        if found_streams:
            print(f"✅ Found {len(found_streams)} stream(s):")
            for stream_url in found_streams:
                print(f"  - {stream_url}")
        else:
            print("⚠️ No M3U8 URLs were captured")

        return list(found_streams)

    except Exception as e:
        print(f"❌ Error during scraping: {e}")
        return []

# Example usage
async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        streams = await grab_m3u8_from_iframe(page, "https://ppv.to/embed/example-stream")
        print("Streams found:", streams)
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
