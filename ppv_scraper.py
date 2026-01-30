import asyncio
import time
import re
from typing import Optional, List, Dict, Any

# ============================================================================
# ENHANCED IFRAME DETECTION AND HANDLING
# ============================================================================

async def check_for_blocking_elements(page) -> List[str]:
    """Check for anti-bot overlays, captchas, or adblock detectors"""
    blocking_selectors = [
        'div[class*="overlay"]',
        'div[class*="adblock"]',
        'div[class*="ad-block"]',
        'div[id*="captcha"]',
        'iframe[src*="captcha"]',
        'button:has-text("I\'m not a robot")',
        'div:has-text("Please disable")',
        'div:has-text("AdBlock")',
        'div[class*="modal"]',
        'div[class*="popup"]'
    ]
    
    found_blockers = []
    for selector in blocking_selectors:
        try:
            element = await page.query_selector(selector)
            if element:
                is_visible = await element.is_visible()
                if is_visible:
                    found_blockers.append(selector)
                    print(f"⚠️ Blocking element found (visible): {selector}")
        except Exception:
            pass
    
    return found_blockers


async def get_iframe_info_via_js(page) -> List[Dict[str, Any]]:
    """Get detailed iframe information via JavaScript"""
    try:
        js_info = await page.evaluate("""() => {
            const iframes = document.querySelectorAll('iframe');
            return Array.from(iframes).map((iframe, index) => ({
                index: index,
                src: iframe.src || null,
                dataSrc: iframe.getAttribute('data-src') || null,
                id: iframe.id || null,
                className: iframe.className || null,
                width: iframe.width || iframe.offsetWidth,
                height: iframe.height || iframe.offsetHeight,
                hasParent: !!iframe.parentElement,
                parentTag: iframe.parentElement?.tagName || null,
                isVisible: iframe.offsetParent !== null,
                style: iframe.getAttribute('style') || null
            }));
        }""")
        return js_info
    except Exception as e:
        print(f"⚠️ Failed to get iframe info via JS: {e}")
        return []


async def extract_iframe_src_from_html(page) -> Optional[str]:
    """Fallback: Extract iframe src from raw HTML"""
    try:
        content = await page.content()
        
        # Try multiple regex patterns
        patterns = [
            r'<iframe[^>]+src=["\']([^"\']+)["\']',
            r'<iframe[^>]+data-src=["\']([^"\']+)["\']',
            r'iframe\.src\s*=\s*["\']([^"\']+)["\']',
            r'setAttribute\(["\']src["\']\s*,\s*["\']([^"\']+)["\']'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                src = match.group(1)
                if src and src != 'about:blank':
                    print(f"✅ Found iframe src in HTML: {src}")
                    return src
        
        print("⚠️ No iframe src found in HTML")
        return None
    except Exception as e:
        print(f"⚠️ Failed to extract iframe src from HTML: {e}")
        return None


async def trigger_user_interactions(page):
    """Trigger user-like interactions to activate lazy-loaded content"""
    try:
        # Move mouse to simulate human behavior
        await page.mouse.move(100, 100)
        await asyncio.sleep(0.3)
        await page.mouse.move(500, 500)
        await asyncio.sleep(0.3)
        
        # Scroll to trigger lazy loading
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
        await asyncio.sleep(0.5)
        await page.evaluate("window.scrollTo(0, 0)")
        await asyncio.sleep(0.5)
        
        # Click in center of page
        viewport = page.viewport_size
        center_x = viewport['width'] // 2
        center_y = viewport['height'] // 2
        await page.mouse.click(center_x, center_y)
        await asyncio.sleep(0.5)
        
        # Hover over potential iframe area
        await page.mouse.move(center_x, center_y)
        await asyncio.sleep(0.5)
        
        print("✅ Triggered user-like interactions")
    except Exception as e:
        print(f"⚠️ Failed to trigger interactions: {e}")


async def wait_for_iframe_src_advanced(page, timeout=45) -> Optional[str]:
    """
    Advanced iframe src detection with multiple strategies:
    1. Poll for iframe src attribute
    2. Check data-src attribute
    3. Monitor JavaScript execution
    4. Extract from HTML source
    5. Wait for iframe content to load
    """
    print(f"⏳ Waiting for iframe src to populate (max {timeout}s)...")
    start_time = time.time()
    check_interval = 0.5
    last_log_time = start_time
    
    while time.time() - start_time < timeout:
        elapsed = time.time() - start_time
        
        # Log progress every 5 seconds
        if elapsed - (last_log_time - start_time) >= 5:
            print(f"   ... still waiting ({elapsed:.1f}s elapsed)")
            last_log_time = time.time()
        
        # Strategy 1: Check iframe src attribute directly
        try:
            iframes = await page.query_selector_all('iframe')
            for idx, iframe in enumerate(iframes):
                src = await iframe.get_attribute('src')
                if src and src != 'about:blank' and src.startswith('http'):
                    print(f"✅ Iframe {idx} src populated: {src}")
                    return src
                
                # Check data-src attribute
                data_src = await iframe.get_attribute('data-src')
                if data_src and data_src != 'about:blank' and data_src.startswith('http'):
                    print(f"✅ Iframe {idx} data-src found: {data_src}")
                    # Try to trigger src from data-src
                    try:
                        await page.evaluate(f"document.querySelectorAll('iframe')[{idx}].src = document.querySelectorAll('iframe')[{idx}].getAttribute('data-src')")
                        await asyncio.sleep(1)
                        src = await iframe.get_attribute('src')
                        if src and src.startswith('http'):
                            return src
                    except Exception:
                        pass
        except Exception as e:
            print(f"⚠️ Error checking iframe attributes: {e}")
        
        # Strategy 2: Get detailed JS info every 10 checks
        if int(elapsed / check_interval) % 10 == 0:
            js_info = await get_iframe_info_via_js(page)
            for info in js_info:
                if info.get('src') and info['src'] != 'about:blank':
                    print(f"✅ Found src via JS: {info['src']}")
                    return info['src']
                if info.get('dataSrc'):
                    print(f"📊 Found data-src via JS: {info['dataSrc']}")
        
        await asyncio.sleep(check_interval)
    
    print(f"⚠️ Iframe src not populated after {timeout}s")
    
    # Final fallback: Extract from HTML
    html_src = await extract_iframe_src_from_html(page)
    if html_src:
        return html_src
    
    return None


async def navigate_and_detect_iframe(page, url: str, timeout: int = 60) -> Optional[str]:
    """
    Navigate to URL and detect iframe src with comprehensive error handling
    
    Returns:
        iframe_src: The detected iframe URL, or None if not found
    """
    try:
        print(f"🌐 Navigating to iframe: {url}")
        
        # Navigate to the page
        try:
            await page.goto(url, wait_until='domcontentloaded', timeout=timeout * 1000)
            print("✅ Page loaded (domcontentloaded)")
        except Exception as e:
            print(f"⚠️ Navigation timeout or error: {e}")
            # Continue anyway, page might have partially loaded
        
        # Wait for network to settle
        try:
            await page.wait_for_load_state('networkidle', timeout=10000)
            print("✅ Network idle detected")
        except Exception:
            print("⚠️ Network idle timeout, continuing...")
        
        # Additional wait for JavaScript execution
        await asyncio.sleep(2)
        
        # Check for blocking elements first
        blockers = await check_for_blocking_elements(page)
        if blockers:
            print(f"⚠️ Found {len(blockers)} blocking elements, attempting to close...")
            # Try to close modals/overlays
            try:
                close_selectors = ['button.close', '[aria-label="Close"]', '.modal-close', 'button:has-text("Close")']
                for selector in close_selectors:
                    element = await page.query_selector(selector)
                    if element:
                        await element.click()
                        await asyncio.sleep(0.5)
            except Exception:
                pass
        
        # Trigger user interactions to activate lazy loading
        await trigger_user_interactions(page)
        
        # Get initial iframe info
        print("📊 Checking initial iframe state...")
        js_info = await get_iframe_info_via_js(page)
        if js_info:
            print(f"🔍 Found {len(js_info)} iframe(s) in DOM:")
            for info in js_info:
                print(f"   Iframe {info['index']}: src={info['src']}, data-src={info['dataSrc']}, visible={info['isVisible']}")
        else:
            print("⚠️ No iframes found in DOM")
            return None
        
        # Wait for iframe src to populate
        iframe_src = await wait_for_iframe_src_advanced(page, timeout=45)
        
        if not iframe_src:
            print("❌ Failed to detect iframe src after all attempts")
            
            # Debug: Take screenshot and dump HTML
            try:
                screenshot_path = f"debug_no_iframe_{int(time.time())}.png"
                await page.screenshot(path=screenshot_path)
                print(f"📸 Debug screenshot saved: {screenshot_path}")
                
                html_path = f"debug_no_iframe_{int(time.time())}.html"
                content = await page.content()
                with open(html_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                print(f"📄 Debug HTML saved: {html_path}")
            except Exception as e:
                print(f"⚠️ Failed to save debug files: {e}")
            
            return None
        
        # Validate the iframe src
        if not iframe_src.startswith('http'):
            print(f"⚠️ Invalid iframe src (not HTTP): {iframe_src}")
            return None
        
        return iframe_src
        
    except Exception as e:
        print(f"❌ Error in navigate_and_detect_iframe: {e}")
        import traceback
        traceback.print_exc()
        return None


async def get_all_frames_info(page) -> List[Dict[str, str]]:
    """Get information about all frames including nested ones"""
    frames_info = []
    try:
        all_frames = page.frames
        print(f"📊 Found {len(all_frames)} total frames (including nested)")
        for idx, frame in enumerate(all_frames):
            url = frame.url
            frames_info.append({'index': idx, 'url': url})
            print(f"   Frame {idx}: {url}")
    except Exception as e:
        print(f"⚠️ Error getting frames info: {e}")
    return frames_info


# ============================================================================
# INTEGRATION INTO MAIN SCRAPING FLOW
# ============================================================================

async def scrape_stream_enhanced(page, stream_data: dict, stream_index: int, total_streams: int) -> Optional[str]:
    """
    Enhanced stream scraping with advanced iframe detection
    
    Args:
        page: Playwright page object
        stream_data: Dictionary with stream info (title, iframe_url, category)
        stream_index: Current stream index
        total_streams: Total number of streams
    
    Returns:
        m3u8_url: The captured M3U8 URL, or None if failed
    """
    title = stream_data.get('title', 'Unknown')
    iframe_url = stream_data.get('iframe_url')
    category = stream_data.get('category', 'Unknown')
    
    print(f"\n🔎 Scraping stream {stream_index}/{total_streams}: {title} ({category})")
    
    if not iframe_url:
        print("❌ No iframe URL provided")
        return None
    
    # Navigate and detect iframe
    detected_iframe_src = await navigate_and_detect_iframe(page, iframe_url, timeout=60)
    
    if not detected_iframe_src:
        print(f"❌ Could not detect iframe src for {title}")
        return None
    
    # Get all frames info for debugging
    await get_all_frames_info(page)
    
    # Now navigate to the detected iframe src
    print(f"🎯 Navigating to detected iframe: {detected_iframe_src}")
    try:
        await page.goto(detected_iframe_src, wait_until='domcontentloaded', timeout=60000)
        await asyncio.sleep(3)
    except Exception as e:
        print(f"⚠️ Error navigating to iframe src: {e}")
    
    # Continue with video detection and stream capture...
    # (Your existing video detection and M3U8 capture code goes here)
    
    return None  # Replace with actual M3U8 URL when captured


# ============================================================================
# EXAMPLE USAGE
# ============================================================================

async def main():
    from playwright.async_api import async_playwright
    
    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True)
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        )
        page = await context.new_page()
        
        # Test with one of your failing streams
        test_stream = {
            'title': 'Indiana Pacers vs. Atlanta Hawks',
            'iframe_url': 'https://modistreams.org/embed/nba/2026-01-30/ind-atl',
            'category': 'Basketball'
        }
        
        result = await scrape_stream_enhanced(page, test_stream, 1, 1)
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
