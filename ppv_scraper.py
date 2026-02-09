import asyncio
import aiohttp
import logging
from playwright.async_api import async_playwright, Page, TimeoutError as PlaywrightTimeout
from typing import Optional
import json

logger = logging.getLogger(__name__)

API_URL = "https://ppv.to/api/streams"
CUSTOM_HEADERS = [
    '#EXTVLCOPT:http-origin=https://ppv.to',
    '#EXTVLCOPT:http-referrer=https://ppv.to/',
    '#EXTVLCOPT:http-user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:143.0) Gecko/20100101 Firefox/143.0'
]

REQUEST_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:143.0) Gecko/20100101 Firefox/143.0',
    'Origin': 'https://ppv.to',
    'Referer': 'https://ppv.to/',
    'Accept': 'application/json',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
    'Sec-Fetch-Dest': 'empty',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Site': 'same-origin'
}


async def fetch_api_streams(session: aiohttp.ClientSession) -> list[dict]:
    """Fetch streams from ppv.to API"""
    try:
        logger.debug(f"🌐 Fetching from API: {API_URL}")
        
        async with session.get(API_URL, headers=REQUEST_HEADERS, timeout=aiohttp.ClientTimeout(total=30)) as response:
            if response.status == 200:
                data = await response.json()
                logger.debug(f"✅ API response received: {len(data)} streams")
                return data if isinstance(data, list) else data.get('streams', [])
            else:
                logger.warning(f"⚠️ API returned status {response.status}")
                return []
                
    except asyncio.TimeoutError:
        logger.error("❌ API request timeout")
        return []
    except Exception as e:
        logger.error(f"❌ Error fetching API: {e}")
        return []


async def get_stream_embed_url(session: aiohttp.ClientSession, stream_id: str) -> Optional[str]:
    """Get embed URL for a specific stream"""
    try:
        embed_url = f"https://ppv.to/embed/{stream_id}"
        
        # Verify the embed URL is accessible
        async with session.head(embed_url, headers=REQUEST_HEADERS, timeout=aiohttp.ClientTimeout(total=10), allow_redirects=True) as response:
            if response.status == 200:
                logger.debug(f"✅ Embed URL verified: {embed_url}")
                return embed_url
            else:
                logger.debug(f"⚠️ Embed URL returned status {response.status}")
                return None
                
    except Exception as e:
        logger.debug(f"⚠️ Error verifying embed URL: {e}")
        return None


async def extract_m3u8_from_page(page: Page) -> list[str]:
    """Extract M3U8 URLs from page source and network"""
    m3u8_urls = []
    
    try:
        # Method 1: Check video element src
        video_srcs = await page.evaluate("""
            () => {
                const videos = document.querySelectorAll('video');
                const srcs = [];
                videos.forEach(v => {
                    if (v.src && v.src.includes('.m3u8')) srcs.push(v.src);
                    if (v.currentSrc && v.currentSrc.includes('.m3u8')) srcs.push(v.currentSrc);
                    const sources = v.querySelectorAll('source');
                    sources.forEach(s => {
                        if (s.src && s.src.includes('.m3u8')) srcs.push(s.src);
                    });
                });
                return srcs;
            }
        """)
               m3u8_urls.extend(video_srcs)
        logger.debug(f"Found {len(video_srcs)} M3U8 from video elements")
        
        # Method 2: Check page source for M3U8 URLs
        page_content = await page.content()
        import re
        m3u8_pattern = r'https?://[^\s<>"\']+\.m3u8[^\s<>"\']*'
        found_urls = re.findall(m3u8_pattern, page_content)
        m3u8_urls.extend(found_urls)
        logger.debug(f"Found {len(found_urls)} M3U8 from page source")
        
        # Method 3: Check HLS.js player
        try:
            hls_urls = await page.evaluate("""
                () => {
                    const urls = [];
                    if (window.hls && window.hls.media && window.hls.media.currentSrc) {
                        urls.push(window.hls.media.currentSrc);
                    }
                    if (window.Hls && window.Hls.version) {
                        // HLS.js is loaded, check for manifest
                        const scripts = document.querySelectorAll('script');
                        scripts.forEach(s => {
                            if (s.textContent && s.textContent.includes('.m3u8')) {
                                const matches = s.textContent.match(/https?:\/\/[^\s<>"']+\.m3u8[^\s<>"']*/g);
                                if (matches) urls.push(...matches);
                            }
                        });
                    }
                    return urls;
                }
            """)
            m3u8_urls.extend(hls_urls)
            logger.debug(f"Found {len(hls_urls)} M3U8 from HLS.js")
        except Exception as e:
            logger.debug(f"HLS.js check failed: {e}")
        
        # Method 4: Check JWPlayer
        try:
            jwplayer_urls = await page.evaluate("""
                () => {
                    const urls = [];
                    try {
                        if (window.jwplayer && typeof window.jwplayer === 'function') {
                            const player = window.jwplayer();
                            if (player && player.getPlaylist) {
                                const playlist = player.getPlaylist();
                                if (playlist) {
                                    playlist.forEach(item => {
                                        if (item.file && item.file.includes('.m3u8')) {
                                            urls.push(item.file);
                                        }
                                        if (item.sources) {
                                            item.sources.forEach(source => {
                                                if (source.file && source.file.includes('.m3u8')) {
                                                    urls.push(source.file);
                                                }
                                            });
                                        }
                                    });
                                }
                            }
                        }
                    } catch(e) {
                        return [];
                    }
                    return urls;
                }
            """)
            m3u8_urls.extend(jwplayer_urls)
            logger.debug(f"Found {len(jwplayer_urls)} M3U8 from JWPlayer")
        except Exception as e:
            logger.debug(f"JWPlayer check failed: {e}")
        
        # Method 5: Check for iframe with src containing m3u8
        try:
            iframe_urls = await page.evaluate("""
                () => {
                    const urls = [];
                    const iframes = document.querySelectorAll('iframe');
                    iframes.forEach(iframe => {
                        if (iframe.src && iframe.src.includes('.m3u8')) {
                            urls.push(iframe.src);
                        }
                    });
                    return urls;
                }
            """)
            m3u8_urls.extend(iframe_urls)
            logger.debug(f"Found {len(iframe_urls)} M3U8 from iframes")
        except Exception as e:
            logger.debug(f"Iframe check failed: {e}")
        
        # Remove duplicates and filter valid URLs
        m3u8_urls = list(set([url for url in m3u8_urls if url and url.startswith('http')]))
        logger.debug(f"Total unique M3U8 URLs found: {len(m3u8_urls)}")
        
    except Exception as e:
        logger.debug(f"Error extracting M3U8: {e}")
    
    return m3u8_urls


async def scrape_stream_embed(page: Page, embed_url: str, timeout: int = 30) -> list[str]:
    """Scrape M3U8 URLs from ppv.to embed"""
    m3u8_urls = []
    
    try:
        logger.debug(f"🌐 Navigating to embed: {embed_url}")
        
        # Navigate to embed page
        await page.goto(embed_url, wait_until="domcontentloaded", timeout=timeout * 1000)
        logger.debug("✅ Embed page loaded (domcontentloaded)")
        
        # Wait for network idle
        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
            logger.debug("✅ Network idle detected")
        except PlaywrightTimeout:
            logger.debug("⏰ Network idle timeout (continuing anyway)")
        
        # Wait a bit for player to initialize
        await asyncio.sleep(2)
        
        # Trigger player interactions
        try:
            # Click on player area
            await page.mouse.move(400, 300)
            await page.mouse.click(400, 300)
            await asyncio.sleep(0.5)
            
            # Try keyboard triggers
            await page.keyboard.press('Space')
            await asyncio.sleep(0.3)
            
        except Exception as e:
            logger.debug(f"Interaction trigger error: {e}")
        
        # Wait for playback to start
        await asyncio.sleep(2)
        
        # Extract M3U8 URLs
        m3u8_urls = await extract_m3u8_from_page(page)
        
        if m3u8_urls:
            logger.debug(f"✅ Found {len(m3u8_urls)} M3U8 URL(s)")
        else:
            logger.warning(f"⚠️ No M3U8 URLs found on embed page")
        
    except PlaywrightTimeout:
        logger.error(f"❌ Timeout loading embed: {embed_url}")
    except Exception as e:
        logger.error(f"❌ Error scraping embed {embed_url}: {e}")
    
    return m3u8_urls


async def process_stream(session: aiohttp.ClientSession, page: Page, stream: dict, index: int, total: int) -> dict:
    """Process a single stream from API"""
    result = {
        'id': stream.get('id'),
        'title': stream.get('title', 'Unknown'),
        'category': stream.get('category', 'Unknown'),
        'embed_url': None,
        'm3u8_urls': [],
        'status': 'failed'
    }
    
    try:
        stream_id = stream.get('id')
        title = stream.get('title', 'Unknown')
        
        logger.info(f"🔎 Scraping stream {index}/{total}: {title}")
        
        # Get embed URL
        embed_url = await get_stream_embed_url(session, stream_id)
        if not embed_url:
            logger.warning(f"⚠️ Could not get embed URL for {title}")
            return result
        
        result['embed_url'] = embed_url
        
        # Scrape embed for M3U8
        m3u8_urls = await scrape_stream_embed(page, embed_url)
        
        if m3u8_urls:
            result['m3u8_urls'] = m3u8_urls
            result['status'] = 'success'
            logger.info(f"✅ Found {len(m3u8_urls)} stream(s) for {title}")
        else:
            result['status'] = 'no_streams'
            logger.warning(f"⚠️ No streams found for {title}")
        
    except Exception as e:
        logger.error(f"❌ Error processing stream: {e}")
        result['status'] = 'error'
    
    return result


async def build_m3u_playlist(streams: list[dict]) -> str:
    """Build M3U8 playlist from scraped streams"""
    playlist = "#EXTM3U\n"
    
    for stream in streams:
        if not stream['m3u8_urls']:
            continue
        
        title = stream['title']
        category = stream['category']
        m3u8_url = stream['m3u8_urls']  # Use first URL if multiple
        
        # Add custom headers
        headers_str = '|'.join(CUSTOM_HEADERS)
        
                # Format: #EXTINF with headers
        playlist += f"#EXTINF:-1 tvg-name=\"{title}\" tvg-group=\"{category}\",{title}\n"
        playlist += f"{m3u8_url}|{headers_str}\n"
    
    return playlist


async def main():
    """Main scraper function"""
    logger.info("🚀 Starting ppv.to scraper...")
    
    async with aiohttp.ClientSession() as session:
        # Fetch streams from API
        streams = await fetch_api_streams(session)
        
        if not streams:
            logger.error("❌ No streams fetched from API")
            return
        
        logger.info(f"📊 Found {len(streams)} streams from API")
        
        # Initialize Playwright
        async with async_playwright() as p:
            browser = await p.firefox.launch(headless=True)
            context = await browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:143.0) Gecko/20100101 Firefox/143.0',
                extra_http_headers=REQUEST_HEADERS
            )
            page = await context.new_page()
            
            # Set up network interception for M3U8 URLs
            intercepted_urls = []
            
            async def handle_route(route):
                if '.m3u8' in route.request.url:
                    intercepted_urls.append(route.request.url)
                    logger.debug(f"🔗 Intercepted M3U8: {route.request.url[:100]}...")
                await route.continue_()
            
            await page.route('**/*', handle_route)
            
            # Process streams
            results = []
            for i, stream in enumerate(streams, 1):
                result = await process_stream(session, page, stream, i, len(streams))
                results.append(result)
                
                # Add any intercepted URLs
                if intercepted_urls:
                    result['m3u8_urls'].extend(intercepted_urls)
                    intercepted_urls.clear()
                
                # Rate limiting
                await asyncio.sleep(1)
            
            # Build playlist
            playlist = await build_m3u_playlist(results)
            
            # Save playlist
            output_file = "ppv_streams.m3u"
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(playlist)
            
            logger.info(f"✅ Playlist saved to {output_file}")
            
            # Print summary
            successful = len([r for r in results if r['status'] == 'success'])
            logger.info(f"📊 Summary: {successful}/{len(results)} streams successfully scraped")
            
            # Cleanup
            await page.close()
            await context.close()
            await browser.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s %(levelname)s %(message)s'
    )
    asyncio.run(main())
