import json
import asyncio
import re
import urllib.parse
from datetime import datetime
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
# Nota: Se recomienda instalar playwright-stealth
# from playwright_stealth import stealth_async 

# ... (Mantener tus constantes API_URL, CATEGORY_LOGOS, etc.)

async def grab_m3u8_from_iframe(page, iframe_url):
    found_streams = set()
    
    # Monitor de red mejorado: Captura URLs que contienen m3u8 incluso en fragmentos
    def handle_network_item(item):
        url = item.url
        if ".m3u8" in url.lower() or "playlist.m3u8" in url.lower():
            # Limpiar URL de posibles parámetros de rastreo si es necesario
            found_streams.add(url)

    page.on("request", handle_network_item)
    page.on("response", handle_network_item)

    try:
        # 1. Navegación con headers de Referer real
        await page.goto(iframe_url, wait_until="networkidle", timeout=45000)
        
        # 2. Bypass de Click-to-Play: Muchos sitios requieren una interacción física real
        # para cargar el script del reproductor
        await page.mouse.click(100, 100) 
        await asyncio.sleep(2)

        # 3. Escaneo profundo de Iframes
        # A veces el video está oculto tras 3 o 4 niveles de frames
        for _ in range(3): # Reintentar el escaneo si no hay resultados
            all_frames = page.frames
            for frame in all_frames:
                try:
                    # Intentar forzar el play en cada frame encontrado
                    await frame.evaluate("""() => {
                        const v = document.querySelector('video');
                        if(v) { v.play(); v.muted = true; }
                    }""").catch(lambda e: None)
                except:
                    continue
            
            if found_streams: break
            await asyncio.sleep(3)

        # 4. Validación de URLs encontradas
        valid_urls = set()
        for url in found_streams:
            if await check_m3u8_url(url, iframe_url):
                valid_urls.add(url)
        
        return valid_urls

    except Exception as e:
        print(f"❌ Error en la captura: {e}")
        return set()
    finally:
        page.remove_listener("request", handle_network_item)
