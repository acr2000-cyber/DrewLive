            # Check for video elements
            if status.get('video_elements', 0) > 0:
                logger.debug("🎮 Player initialization result: video element detected")
                return "video_element"
            
            # Check for JWPlayer instance
            if status.get('jwplayer_instance'):
                logger.debug(f"🎮 Player initialization result: jwplayer (state: {status.get('jwplayer_state', 'unknown')})")
                return "jwplayer"
            
            # Check for HLS.js
            if status.get('hls'):
                logger.debug("🎮 Player initialization result: hls.js detected")
                return "hls"
            
            # Check for Video.js
            if status.get('videojs'):
                logger.debug("🎮 Player initialization result: video.js detected")
                return "videojs"
            
            await asyncio.sleep(0.5)
            
        except Exception as e:
            logger.debug(f"Error checking player initialization: {e}")
            await asyncio.sleep(0.5)
    
    logger.debug("🎮 Player initialization result: timeout - no player detected")
    return "timeout"


async def scrape_stream_url(page: Page, iframe_url: str, timeout: int = 30) -> list[str]:
    """
    Main scraping function with enhanced modistreams.org support
    """
    m3u8_urls = []
    
    try:
        # Navigate to iframe
        logger.debug(f"🌐 Navigating to iframe: {iframe_url}")
        await page.goto(iframe_url, wait_until="domcontentloaded", timeout=timeout * 1000)
        logger.debug("✅ Page loaded (domcontentloaded)")
        
        # Wait for network idle
        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
            logger.debug("✅ Network idle detected")
        except PlaywrightTimeout:
            logger.debug("⏰ Network idle timeout (continuing anyway)")
        
        # Check for blockers
        blockers = await check_for_blockers(page)
        if blockers.get('captcha') or blockers.get('cloudflare') or blockers.get('blocked'):
            logger.warning(f"🚫 Page blocked or requires interaction: {blockers}")
            return []
        
        # Get initial player status
        status = await get_player_status(page)
        logger.debug(f"📊 Player status: {status}")
        
        # Trigger initial interactions
        await trigger_player_load(page)
        
        # Wait for iframe src to populate (if iframe exists)
        if status.get('iframes', 0) > 0:
            iframe_src = await wait_for_iframe_src(page, timeout=20)
            
            if iframe_src and iframe_src.startswith('http'):
                # Navigate to nested iframe
                logger.debug(f"🔄 Navigating to nested iframe: {iframe_src[:100]}...")
                try:
                    await page.goto(iframe_src, wait_until="domcontentloaded", timeout=timeout * 1000)
                    logger.debug("✅ Nested iframe loaded")
                    
                    # Wait for network idle on nested iframe
                    try:
                        await page.wait_for_load_state("networkidle", timeout=10000)
                    except PlaywrightTimeout:
                        pass
                    
                    # Trigger interactions on nested iframe
                    await trigger_player_load(page)
                    
                except Exception as e:
                    logger.warning(f"⚠️ Could not navigate to nested iframe: {e}")
        
        # Wait for player initialization
        player_type = await wait_for_player_initialization(page, timeout=15)
        
        # Additional interaction after player detection
        if player_type != "timeout":
            await asyncio.sleep(1)
            await trigger_player_load(page)
        
        # Check all frames for video elements
        frames = page.frames
        logger.debug(f"📊 Found {len(frames)} total frames")
        
        for i, frame in enumerate(frames):
            try:
                video_count = await frame.evaluate("document.querySelectorAll('video').length")
                if video_count > 0:
                    logger.debug(f"✅ Found {video_count} video element(s) in frame {i}")
            except Exception as e:
                logger.debug(f"⚠️ Error checking frame {i} for video: {e}")
        
        # Trigger playback
        await trigger_playback(page)
        
        # Wait for M3U8 streams to be captured
        # (This assumes you have network interception set up elsewhere)
        await asyncio.sleep(3)
        
        # Try to extract M3U8 from page source / network
        m3u8_urls = await extract_m3u8_from_sources(page)
        
        logger.debug(f"📊 Total valid streams found: {len(m3u8_urls)}")
        
    except Exception as e:
        logger.error(f"❌ Error scraping {iframe_url}: {e}")
    
    return m3u8_urls


async def extract_m3u8_from_sources(page: Page) -> list[str]:
    """Extract M3U8 URLs from various sources"""
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
                });
                return srcs;
            }
        """)
        m3u8_urls.extend(video_srcs)
        
        # Method 2: Check page source for M3U8 URLs
        page_content = await page.content()
        import re
        m3u8_pattern = r'https?://[^\s<>"\']+\.m3u8[^\s<>"\']*'
        found_urls = re.findall(m3u8_pattern, page_content)
        m3u8_urls.extend(found_urls)
        
        # Method 3: Check JWPlayer playlist
        try:
            jwplayer_playlist = await page.evaluate("""
                () => {
                    try {
                        if (window.jwplayer && typeof window.jwplayer === 'function') {
                            const player = window.jwplayer();
                            if (player && player.getPlaylist) {
                                const playlist = player.getPlaylist();
                                const urls = [];
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
                                return urls;
                            }
                        }
                    } catch(e) {
                        return [];
                    }
                    return [];
                }
            """)
            m3u8_urls.extend(jwplayer_playlist)
        except:
            pass
        
        # Remove duplicates and filter valid URLs
        m3u8_urls = list(set([url for url in m3u8_urls if url and url.startswith('http')]))
        
    except Exception as e:
        logger.debug(f"Error extracting M3U8: {e}")
    
    return m3u8_urls
