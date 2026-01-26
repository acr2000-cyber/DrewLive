import json
import asyncio
import re
import urllib.parse
from datetime import datetime
import aiohttp
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

# --- CONFIGURACIÓN Y CONSTANTES ---
API_URL = "https://ppv.to/api/streams"
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

# --- FUNCIONES DE SOPORTE ---

def get_all_frames(frame):
    """Obtiene recursivamente todos los frames."""
    all_frames = [frame]
    for child in frame.child_frames:
        all_frames.extend(get_all_frames(child))
    return all_frames

async def check_m3u8_url(url, referer):
    """Valida si la URL de m3u8 es funcional."""
    if "gg.poocloud.in" in url:
        return True
    try:
        origin = "https://" + referer.split('/')[2] if referer else "https://ppv.to"
        headers = {"User-Agent": DEFAULT_UA, "Referer": referer, "Origin": origin}
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            async with session.get(url, headers=headers) as resp:
                return resp.status in [200, 403]
    except:
        return False

def _encode_param(value: str) -> str:
    return urllib.parse.quote(value or "", safe='')

# --- LÓGICA DE SCRAPING ---

async def grab_m3u8_from_iframe(page, iframe_url):
    """Versión mejorada para detectar streams en sitios con alta protección."""
    found_streams = set()
    
    def handle_network(item):
        url = item.url
        if ".m3u8" in url.lower():
            found_streams.add(url)

    page.on("request", handle_network)
    page.on("response", handle_network)
    
    try:
        print(f"🌐 Navegando a: {iframe_url}")
        await page.goto(iframe_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(5) # Espera para carga de scripts dinámicos

        # Interacción física para bypass de anti-bots
        await page.mouse.click(960, 540)
        await page.keyboard.press("Space")

        # Escaneo profundo de frames para encontrar el reproductor oculto
        frames = get_all_frames(page.main_frame)
        for frame in frames:
            try:
                # Intentar disparar el play vía JS en cada frame
                await frame.evaluate("() => { const v = document.querySelector('video'); if(v) v.play(); }")
            except:
                continue

        # Espera extendida para capturar la petición de red
        try:
            async with page.expect_response(lambda r: ".m3u8" in r.url, timeout=15000):
                print("🎯 Stream detectado en tráfico de red")
        except:
            pass

        valid_urls = set()
        for url in found_streams:
            if await check_m3u8_url(url, iframe_url):
                valid_urls.add(url)
        return valid_urls

    except Exception as e:
        print(f"⚠️ Error en frame: {e}")
        return set()
    finally:
        page.remove_listener("request", handle_network)
        page.remove_listener("response", handle_network)

async def get_streams():
    """Obtiene la lista inicial de la API."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(API_URL) as resp:
                if resp.status == 200:
                    return await resp.json()
    except Exception as e:
        print(f"❌ Error API: {e}")
    return None

def build_m3u(streams, url_map):
    """Genera el contenido del archivo M3U8 con parámetros de VLC."""
    lines = ['#EXTM3U']
    for s in streams:
        key = f"{s['name']}::{s['category']}::{s['iframe']}"
        urls = url_map.get(key)
        if not urls: continue

        url = next(iter(urls))
        referer = s["iframe"]
        origin = "https://" + referer.split('/')[2] if "/" in referer else "https://ppv.to"
        
        # Formato compatible con VLC y reproductores estándar
        params = f"|User-Agent={_encode_param(DEFAULT_UA)}&Referer={_encode_param(referer)}&Origin={_encode_param(origin)}"
        
        logo = s.get("poster") or CATEGORY_LOGOS.get(s["category"], "")
        group = GROUP_RENAME_MAP.get(s["category"], "PPVLand")
        tvg = CATEGORY_TVG_IDS.get(s["category"], "")

        lines.append(f'#EXTINF:-1 tvg-id="{tvg}" tvg-logo="{logo}" group-title="{group}",{s["name"]}')
        lines.append(f'{url}{params}')
    return "\n".join(lines)

# --- EJECUCIÓN PRINCIPAL ---

async def main():
    print("🚀 Iniciando PPV Land Fetcher Pro")
    data = await get_streams()
    if not data: return

    all_streams = []
    for cat_data in data.get("streams", []):
        cat_name = cat_data.get("category", "Misc")
        for s in cat_data.get("streams", []):
            if s.get("iframe"):
                all_streams.append({
                    "name": s.get("name"),
                    "iframe": s.get("iframe"),
                    "category": cat_name,
                    "poster": s.get("poster")
                })

    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True)
        context = await browser.new_context(user_agent=DEFAULT_UA)
        page = await context.new_page()
        
        url_map = {}
        for idx, s in enumerate(all_streams, 1):
            print(f"[{idx}/{len(all_streams)}] Procesando: {s['name']}")
            key = f"{s['name']}::{s['category']}::{s['iframe']}"
            urls = await grab_m3u8_from_iframe(page, s["iframe"])
            url_map[key] = urls
            await asyncio.sleep(2)

        await browser.close()

    # Guardar resultados
    playlist = build_m3u(all_streams, url_map)
    with open("PPVLand.m3u8", "w", encoding="utf-8") as f:
        f.write(playlist)
    print(f"✅ Proceso completado. Playlist generada a las {datetime.now()}")

if __name__ == "__main__":
    asyncio.run(main())
