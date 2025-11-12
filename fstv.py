import re
import sys
import asyncio
import random
from playwright.async_api import async_playwright
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

# --- Helper to print status/errors to Standard Error (stderr) ---
def err_print(*args, **kwargs):
    """Prints status messages to stderr to keep stdout clean for the M3U8 output."""
    print(*args, file=sys.stderr, flush=True, **kwargs)
# ----------------------------------------------------------------

# --- Channel Mapping Data (Minimized for brevity, full map retained) ---
CHANNEL_MAPPING = {
    "usanetwork": {"name": "USA Network", "tv_id": "USA.Network.HD.us2", "group": "USA", "keywords": ["usanetwork"]},
    "cbsla": {"name": "CBS Los Angeles", "tv_id": "KCBS-DT.us_locals1", "logo": "http://drewlive24.duckdns.org:9000/Logos/CBS.png", "group": "USA", "keywords": ["cbslosangeles"]},
    "nbc": {"name": "NBC", "tv_id": "WNBC-DT.us_locals1", "group": "USA", "keywords": ["usnbc"]},
    "abc": {"name": "ABC", "tv_id": "KABC-DT.us_locals1", "group": "USA", "keywords": ["usaabc"]},
    "foxla": {"name": "Fox Los Angeles", "tv_id": "KTTV-DT.us_locals1", "logo": "http://drewlive24.duckdns.org:9000/Logos/FOX.png", "group": "USA", "keywords": ["foxchannel"]},
    "ion": {"name": "ION USA", "tv_id": "ION.Television.HD.us2", "group": "USA", "keywords": ["ionusa"]},
    "telemundo": {"name": "Telemundo", "tv_id": "KVEA-DT.us_locals1", "group": "USA", "keywords": ["usatelemundo"]},
    "unimas": {"name": "UniMás", "tv_id": "KFTH-DT.us_locals1", "logo": "https://github.com/tv-logo/tv-logos/blob/main/countries/united-states/unimas-us.png?raw=true", "group": "USA", "keywords": ["usaunimas"]},
    "tnt": {"name": "TNT", "tv_id": "TNT.HD.us2", "group": "USA", "keywords": ["tntusa"]},
    "paramount": {"name": "Paramount Network", "tv_id": "Paramount.Network.HD.us2", "logo": "https://github.com/tv-logo/tv-logos/blob/main/countries/united-states/paramount-network-hz-us.png?raw=true", "group": "USA", "keywords": ["paramountnetwork"]},
    "axstv": {"name": "AXS TV", "tv_id": "AXS.TV.us2", "group": "USA", "keywords": ["axstv"]},
    "trutv": {"name": "truTV", "tv_id": "truTV.HD.us2", "logo": "https://github.com/tv-logo/tv-logos/blob/main/countries/united-states/tru-tv-us.png?raw=true", "group": "USA", "keywords": ["trutv"]},
    "tbs": {"name": "TBS", "tv_id": "TBS.HD.us2", "group": "USA", "keywords": ["tbs"]},
    "discovery": {"name": "Discovery Channel", "tv_id": "Discovery.Channel.HD.us2", "group": "USA", "keywords": ["zentdiscovery"]},
    "nbcnews": {"name": "NBC News", "tv_id": "plex.tv.NBC.News.NOW.plex", "logo": "https://github.com/tv-logo/tv-logos/blob/main/countries/united-states/nbc-news-flat-us.png?raw=true", "group": "USA News", "keywords": ["nbcnewyork"]},
    "msnbc": {"name": "MSNBC", "tv_id": "MSNBC.HD.us2", "group": "USA News", "keywords": ["usmsnbc"]},
    "cnbc": {"name": "CNBC", "tv_id": "CNBC.HD.us2", "group": "USA News", "keywords": ["usacnbc"]},
    "cnn": {"name": "CNN", "tv_id": "CNN.HD.us2", "group": "USA News", "keywords": ["uscnn"]},
    "foxnews": {"name": "FoxNews", "tv_id": "Fox.News.Channel.HD.us2", "group": "USA News", "keywords": ["usafoxnews", "usfoxnews"]},
    "espn2": {"name": "ESPN2", "tv_id": "ESPN2.HD.us2", "group": "USA Sports", "keywords": ["usespn2"]},
    "espnu": {"name": "ESPNU", "tv_id": "ESPNU.HD.us2", "group": "USA Sports", "keywords": ["usuespn"]},
    "espnnews": {"name": "ESPNews", "tv_id": "ESPNEWS.HD.us2", "group": "USA Sports", "keywords": ["usespnnews"]},
    "secnetwork": {"name": "SEC Network", "tv_id": "SEC.Network.HD.us2", "group": "USA Sports", "keywords": ["usaespnsecnetwork"]},
    "espndeportes": {"name": "ESPN Deportes", "tv_id": "ESPN.Deportes.HD.us2", "group": "USA Sports", "keywords": ["usespndeportes"]},
    "tennis2": {"name": "Tennis Channel 2", "tv_id": "Tennis.Channel.HD.us2", "group": "USA Sports", "keywords": ["ustennistv2"]},
    "cbsgolazo": {"name": "CBS Sports Golazo!", "tv_id": "plex.tv.CBS.Sports.Golazo.Network.plex", "group": "USA Sports", "keywords": ["cbsgolazo"]},
    "cbssports": {"name": "CBS Sports Network", "tv_id": "CBS.Sports.Network.HD.us2", "group": "USA Sports", "keywords": ["usacbssport"]},
    "nflnetwork": {"name": "NFL Network", "tv_id": "NFL.Network.HD.us2", "logo": "https://github.com/tv-logo/tv-logos/blob/main/countries/united-states/nfl-network-hz-us.png?raw=true", "group": "USA Sports", "keywords": ["usnfl"]},
    "nflredzone": {"name": "NFL RedZone", "tv_id": "NFL.RedZone.HD.us2", "logo": "https://github.com/tv-logo/tv-logos/blob/main/countries/united-states/nfl-red-zone-hz-us.png?raw=true", "group": "USA Sports", "keywords": ["usredzone"]},
    "espn": {"name": "ESPN", "tv_id": "ESPN.HD.us2", "group": "USA Sports", "keywords": ["usespn"]},
    "fs1": {"name": "FS1", "tv_id": "FS1.HD.us2", "group": "USA Sports", "keywords": ["usafs1"]},
    "fs2": {"name": "FS2", "tv_id": "FS2.HD.us2", "group": "USA Sports", "keywords": ["usafs2"]},
    "golf": {"name": "Golf Channel", "tv_id": "Golf.Channel.HD.us2", "group": "USA Sports", "keywords": ["usagolf"]},
    "tennis": {"name": "Tennis Channel", "tv_id": "Tennis.Channel.HD.us2", "group": "USA Sports", "keywords": ["ustennistv"]},
    "nbcuniverso": {"name": "NBC Universo", "tv_id": "UNIVERSO.HD.us2", "group": "USA Sports", "keywords": ["usauniverso"]},
    "beinsports": {"name": "BeIN Sports USA", "tv_id": "beIN.Sports.USA.HD.us2", "group": "USA Sports", "keywords": ["beinsporthd"]},
    "beinsportsxtra": {"name": "BeIN Sports Xtra USA", "tv_id": "KSKJ-CD.us_locals1", "group": "USA Sports", "keywords": ["beinsportxtra"]},
    "beinsportses": {"name": "BeIN Sports Español", "tv_id": "613759", "group": "USA Sports", "keywords": ["beinsportespanol"]},
    "beinsportsesxtra": {"name": "BeIN Sports Español Xtra", "tv_id": "613759", "group": "USA Sports", "keywords": ["beinespanolxtra"]},
    "bignetwork": {"name": "Big Ten Network", "tv_id": "Big.Ten.Network.HD.us2", "logo": "https://github.com/tv-logo/tv-logos/blob/main/countries/united-states/big-ten-network-us.png?raw=true", "group": "USA Sports", "keywords": ["usabignetwork"]},
    "fubosports": {"name": "Fubo Sports USA", "tv_id": "Fubo.Sports.us", "logo": "https://github.com/tv-logo/tv-logos/blob/main/countries/united-states/fubo-sports-network-us.png?raw=true", "group": "USA Sports", "keywords": ["usafubosport"]},
    "foxsoccerplus": {"name": "Fox Soccer Plus", "tv_id": "Fox.Soccer.Plus.HD.us2", "group": "USA Sports", "keywords": ["usafoxsoccerplus"]},
    "tycsports": {"name": "TyC Sports", "tv_id": "TyC.Sports.Internacional.USA.us2", "logo": "https://github.com/tv-logo/tv-logos/blob/main/countries/argentina/tyc-sports-ar.png?raw=true", "group": "USA Sports", "keywords": ["usatycsport"]},
    "marqueesports": {"name": "Marquee Sports Network", "tv_id": "Marquee.Sports.Network.HD.us2", "group": "USA Sports", "keywords": ["usamarqueesportnetwork"]},
    "yesnetwork": {"name": "YES Network USA", "tv_id": "Yes.Network.us2", "group": "USA Sports", "keywords": ["yesusa"]},
    "tudn": {"name": "TUDN", "tv_id": "TUDN.us2", "group": "USA Sports", "keywords": ["usatudn"]},
    "nhlnetwork": {"name": "NHL Network", "tv_id": "NHL.Network.HD.us2", "logo": "https://github.com/tv-logo/tv-logos/blob/main/countries/united-states/nhl-network-us.png?raw=true", "group": "USA Sports", "keywords": ["usnhlnetwork"]},
    "willowhd": {"name": "Willow Cricket HD", "tv_id": "Willow.Cricket.HD.us2", "group": "USA Sports", "keywords": ["uswillowhd"]},
    "willowxtra": {"name": "Willow Xtra", "tv_id": "Willow.Xtra.us2", "logo": "https://github.com/tv-logo/tv-logos/blob/main/countries/united-states/willow-xtra-us.png?raw=true", "group": "USA Sports", "keywords": ["uswillowxtra"]},
    "nbatv": {"name": "NBA TV", "tv_id": "NBA.TV.HD.us2", "logo": "http://drewlive24.duckdns.org:9000/Logos/NBATV.png", "group": "USA Sports", "keywords": ["usnbatv"]},
    "mlbnetwork": {"name": "MLB Network", "tv_id": "MLB.Network.HD.us2", "group": "USA Sports", "keywords": ["usmlbnetwork"]},
    "accnetwork": {"name": "ACC Network", "tv_id": "ACC.Network.us2", "logo": "https://github.com/tv-logo/tv-logos/blob/main/countries/united-states/acc-network-us.png?raw=true", "group": "USA Sports", "keywords": ["usaccnetwork"]},
    "wfn": {"name": "World Fishing Network", "tv_id": "World.Fishing.Network.HD.(US).us2", "logo": "https://github.com/tv-logo/tv-logos/blob/main/countries/united-states/world-fishing-network-us.png?raw=true", "group": "USA Sports", "keywords": ["uswfn"]},
    "fightnetwork": {"name": "The Fight Network", "tv_id": "Fight.Network.us2", "logo": "https://github.com/tv-logo/tv-logos/blob/main/countries/united-states/fight-network-us.png?raw=true", "group": "USA Sports", "keywords": ["usfightnetwork"]},
    "foxdeportes": {"name": "Fox Deportes", "tv_id": "Fox.Deportes.HD.us2", "group": "USA Sports", "keywords": ["foxdeportes"]},
    "goltv": {"name": "GOL TV", "tv_id": "GOL.TV.us2", "group": "USA Sports", "keywords": ["goltv"]},
    "fandueltv": {"name": "FanDuel TV", "tv_id": "FanDuel.TV.us", "group": "USA Sports", "keywords": ["fandueltv"]},
    "itv1": {"name": "ITV 1 UK", "tv_id": "ITV1.HD.uk", "group": "UK", "keywords": ["ukitv1"]},
    "itv2": {"name": "ITV 2 UK", "tv_id": "ITV2.HD.uk", "group": "UK", "keywords": ["ukitv2"]},
    "itv3": {"name": "ITV 3 UK", "tv_id": "ITV3.HD.uk", "group": "UK", "keywords": ["ukitv3"]},
    "itv4": {"name": "ITV 4 UK", "tv_id": "ITV4.HD.uk", "group": "UK", "keywords": ["ukitv4"]},
    "bbcone": {"name": "BBC One UK", "tv_id": "BBC.One.EastHD.uk", "group": "UK", "keywords": ["ukbbcone"]},
    "bbctwo": {"name": "BBC Two UK", "tv_id": "BBC.Two.HD.uk", "group": "UK", "keywords": ["ukbbctwo"]},
    "bbcnews": {"name": "BBC News UK", "tv_id": "BBC.NEWS.HD.uk", "group": "UK", "keywords": ["ukbbcnews"]},
    "tntsports1": {"name": "TNT Sports 1", "tv_id": "TNT.Sports.1.HD.uk", "group": "UK Sports", "keywords": ["tntsport1"]},
    "tntsports2": {"name": "TNT Sports 2", "tv_id": "TNT.Sports.2.HD.uk", "group": "UK Sports", "keywords": ["tntsport2"]},
    "tntsports3": {"name": "TNT Sports 3", "tv_id": "TNT.Sports.3.HD.uk", "group": "UK Sports", "keywords": ["tntsport3"]},
    "tntsports4": {"name": "TNT Sports 4", "tv_id": "TNT.Sports.4.HD.uk", "group": "UK Sports", "keywords": ["tntsport4"]},
    "tntsports5": {"name": "TNT Sports 5", "tv_id": "TNT.Sports.Ultimate.uk", "group": "UK Sports", "keywords": ["tntsport5"]},
    "eurosport1uk": {"name": "Eurosport 1 UK", "tv_id": "Eurosport.es", "group": "UK Sports", "keywords": ["ukeurosport1"]},
    "eurosport2uk": {"name": "Eurosport 2 UK", "tv_id": "Eurosport.2.es", "group": "UK Sports", "keywords": ["ukeurosport2"]},
    "skysportsgolf": {"name": "Sky Sport Golf UK", "tv_id": "SkySp.Golf.HD.uk", "group": "UK Sports", "keywords": ["ukskysportgolf"]},
    "skysportstennis": {"name": "Sky Sport Tennis UK", "tv_id": "SkySp.Tennis.HD.uk", "group": "UK Sports", "keywords": ["ukskysporttennis"]},
    "mutv": {"name": "MUTV UK", "tv_id": "MUTV.HD.uk", "group": "UK Sports", "keywords": ["ukmutv"]},
    "laligatv": {"name": "La Liga TV UK", "tv_id": "LA.LIGA.za", "group": "UK Sports", "keywords": ["uklaliga"]},
    "skysportsplus": {"name": "Sky Sport Plus UK", "tv_id": "SkySp.PL.HD.uk", "group": "UK Sports", "keywords": ["skysportplus"]},
    "skysportsfootball": {"name": "Sky Sport Football", "tv_id": "SkySp.Fball.HD.uk", "group": "UK Sports", "keywords": ["ukfootball"]},
    "skysportspremier": {"name": "Sky Sport Premier League UK", "tv_id": "SkyPremiereHD.uk", "group": "UK Sports", "keywords": ["ukskysportpremierleague"]},
    "skysportsmix": {"name": "Sky Sport Mix UK", "tv_id": "SkySp.Mix.HD.uk", "group": "UK Sports", "keywords": ["skysportmix"]},
    "skysportsmain": {"name": "Sky Sports Main Event", "tv_id": "SkySpMainEvHD.uk", "group": "UK Sports", "keywords": ["ukmainevent"]},
    "skysportsracing": {"name": "Sky Sport Racing UK", "tv_id": "SkySp.Racing.HD.uk", "group": "UK Sports", "keywords": ["ukskysportracing"]},
    "premiersports1": {"name": "Premier Sports 1 UK", "tv_id": "Premier.Sports.1.HD.uk", "group": "UK Sports", "keywords": ["ukpremiersport1"]},
    "premiersports2": {"name": "Premier Sports 2 UK", "tv_id": "Premier.Sports.2.HD.uk", "logo": "https://github.com/tv-logo/tv-logos/blob/main/countries/united-kingdom/premier-sports-2-uk.png?raw=true", "group": "UK Sports", "keywords": ["ukpremiersport2"]},
    "racingtv": {"name": "Racing TV UK", "tv_id": "Racing.TV.HD.uk", "group": "UK Sports", "keywords": ["ukracingtv"]},
    "skysportsf1": {"name": "Sky Sport F1 UK", "tv_id": "SkySp.F1.HD.uk", "group": "UK Sports", "keywords": ["ukskysportf1"]},
    "skysportsarena": {"name": "Sky Sport Arena UK", "tv_id": "Sky.Sports+.Dummy.us", "group": "UK Sports", "keywords": ["skysportarena"]},
    "skysportsaction": {"name": "Sky Sports Action UK", "tv_id": "SkySp.ActionHD.uk", "logo": "https://github.com/tv-logo/tv-logos/blob/main/countries/united-states/sky-sports-action-hz-us.png?raw=true", "group": "UK Sports", "keywords": ["ukskysportaction"]},
    "skysportscricket": {"name": "Sky Sport Cricket UK", "tv_id": "SkySpCricket.HD.uk", "group": "UK Sports", "keywords": ["ukskysportcricket"]},
    "skysportsnews": {"name": "Sky Sport News UK", "tv_id": "SkySp.News.HD.uk", "group": "UK Sports", "keywords": ["ukskysportnews"]},
    "skysportsdarts": {"name": "Sky Sport Darts UK", "tv_id": "Sky.Sports+.Dummy.us", "group": "UK Sports", "keywords": ["ukskysportdarts"]},
    "lfctv": {"name": "LFC TV UK", "tv_id": "LFCTV.HD.uk", "group": "UK Sports", "keywords": ["uklfctv"]},
    "daznuk": {"name": "DAZN 1 UK", "tv_id": "DAZN.Dummy.us", "logo": "https://github.com/tv-logo/tv-logos/blob/main/countries/germany/dazn1-de.png?raw=true", "group": "UK Sports", "keywords": ["ukdazn"]},
    "wnetwork": {"name": "W Network", "tv_id": "W.Network.HD.ca2", "logo": "https://github.com/tv-logo/tv-logos/blob/main/countries/canada/w-network-ca.png?raw=true", "group": "Canada", "keywords": ["uswnetwork"]},
    "onesoccer": {"name": "OneSoccer Canada", "tv_id": "One.Soccer.ca2", "logo": "https://github.com/tv-logo/tv-logos/blob/main/countries/canada/one-soccer-ca.png?raw=true", "group": "Canada Sports", "keywords": ["caonesoccer"]},
    "tsn1": {"name": "TSN 1", "tv_id": "TSN.1.ca2", "group": "Canada Sports", "keywords": ["tsn1"]},
    "tsn2": {"name": "TSN 2", "tv_id": "TSN.2.ca2", "group": "Canada Sports", "keywords": ["tsn2"]},
    "tsn3": {"name": "TSN 3", "tv_id": "TSN.3.ca2", "group": "Canada Sports", "keywords": ["tsn3"]},
    "tsn4": {"name": "TSN 4", "tv_id": "TSN.4.ca2", "group": "Canada Sports", "keywords": ["tsn4"]},
    "tsn5": {"name": "TSN 5", "tv_id": "TSN.5.ca2", "group": "Canada Sports", "keywords": ["tsn5"]},
    "dazn1de": {"name": "DAZN 1 Germany", "tv_id": "DAZN.1.de", "logo": "https://github.com/tv-logo/tv-logos/blob/main/countries/germany/dazn1-de.png?raw=true", "group": "Germany", "keywords": ["dedazn1"]},
    "dazn2de": {"name": "DAZN 2 Germany", "tv_id": "DAZN.2.de", "logo": "https://github.com/tv-logo/tv-logos/blob/main/countries/germany/dazn2-de.png?raw=true", "group": "Germany", "keywords": ["dedazn2"]},
    "skytopde": {"name": "Sky DE Top Event", "tv_id": "Sky.Sport.Top.Event.de", "group": "Germany Sports", "keywords": ["ori2deskydetopent"]},
    "skypremde": {"name": "Sky Sport Premier League DE", "tv_id": "Sky.Sport.Premier.League.de", "group": "Germany Sports", "keywords": ["eplskydepre"]},
    "sportdigitalde": {"name": "SportDigital Germany", "tv_id": "sportdigital.Fussball.de", "group": "Germany Sports", "keywords": ["desportdigital"]},
    "skynewsde": {"name": "Sky Sport News DE", "tv_id": "Sky.Sport.News.de", "group": "Germany Sports", "keywords": ["deskydenews"]},
    "skymixde": {"name": "Sky Mix DE", "tv_id": "Sky.Sport.Mix.de", "logo": "https://github.com/tv-logo/tv-logos/blob/main/countries/united-kingdom/sky-mix-uk.png?raw=true", "group": "Germany Sports", "keywords": ["deskydemix"]},
    "bundesliga1": {"name": "Bundesliga 1 Germany", "tv_id": "Sky.Sport.Bundesliga.de", "group": "Germany Sports", "keywords": ["debundesliga1"]},
    "fox502": {"name": "Fox Sports 502 AU", "tv_id": "FoxCricket.au", "group": "Australia Sports", "keywords": ["fox502"]},
    "benficatv": {"name": "Benfica TV", "tv_id": "Benfica.TV.fr", "logo": "https://upload.wikimedia.org/wikipedia/commons/thumb/d/d2/Logo_Benfica_TV.png/1200px-Logo_Benfica_TV.png", "group": "Portugal Sports", "keywords": ["ptbenfica"]},
    "sporttv1": {"name": "Sport TV1 Portugal", "tv_id": "SPORT.TV1.HD.pt", "logo": "https://github.com/tv-logo/tv-logos/blob/main/countries/portugal/sport-tv-1-pt.png?raw=true", "group": "Portugal Sports", "keywords": ["ptsporttv1"]},
    "cinemax": {"name": "Cinemax", "tv_id": "Cinemax.HD.us2", "group": "Movies", "keywords": ["zentcinemax"]},
    "hbo2": {"name": "HBO 2", "tv_id": "HBO2.HD.us2", "group": "Movies", "keywords": ["usahbo2"]},
    "hbo": {"name": "HBO", "tv_id": "HBO.East.us2", "logo": "https://github.com/tv-logo/tv-logos/blob/main/countries/united-states/hbo-us.png?raw=true", "group": "Movies", "keywords": ["usahbo"]},
}
# --- End Channel Mapping ---

MIRRORS = [
    "https://fstv.online/live-tv.html?timezone=America%2FDenver",
    "https://fstv.space/live-tv.html?timezone=America%2FDenver",
    "https://fstv.zip/live-tv.html?timezone=America%2FDenver"
]

MAX_RETRIES = 3
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:141.0) Gecko/20100101 Firefox/141.0"
BASE_ORIGIN = "https://fstv.space"
BASE_REFERER = "https://fstv.space/"


def normalize_channel_name(name: str) -> str:
    cleaned_name = re.sub(r'[^a-zA-Z0-9]', '', name)
    return cleaned_name.strip().lower()


def prettify_name(raw: str) -> str:
    raw = re.sub(r'VE[-\s]*', '', raw, flags=re.IGNORECASE)
    raw = re.sub(r'\([^)]*\)', '', raw)
    raw = re.sub(r'[^a-zA-Z0-9\s]', '', raw)
    return re.sub(r'\s+', ' ', raw.strip()).title()


# CRITICAL FIX: Ad-blocking logic to prevent hangs
async def block_ads(route):
    # This logic aborts requests for common ad/tracking/heavy media resources
    resource_type = route.request.resource_type
    url = route.request.url.lower()

    if (resource_type in ["image", "media", "font"] or
        "googlesyndication" in url or
        "doubleclick" in url or
        "adservice" in url or
        "adroll" in url or
        "pop" in url or
        "pixel" in url):
        await route.abort()
    else:
        await route.continue_()


async def fetch_fstv_channels():
    scraped_data = []
    
    async with async_playwright() as p:
        browser = None
        try:
            # Use Firefox for stability
            browser = await p.firefox.launch(headless=True)
            context = await browser.new_context(
                user_agent=USER_AGENT,
                extra_http_headers={"Origin": BASE_ORIGIN, "Referer": BASE_REFERER},
            )
            page = await context.new_page()

            # Enable ad-blocking (CRITICAL FIX for hanging)
            await page.route("**/*", block_ads) 
            # Auto-close popups
            context.on("page", lambda popup: asyncio.create_task(popup.close()))

            visited_urls = set()
            # The regex pattern to find the stream URL
            m3u8_pattern = re.compile(r'\.m3u8\?auth_key=')

            for url in MIRRORS:
                try:
                    err_print(f"\n📡 Starting scrape...")
                    err_print(f"🌐 Trying {url}...")
                    
                    # 1. Navigate to the page
                    await page.goto(url, timeout=120000, wait_until="domcontentloaded")
                    await page.wait_for_selector(".item-channel", timeout=30000)
                    all_elements = await page.query_selector_all(".item-channel")
                    
                    if not all_elements:
                        err_print(f"⚠️ No channels found on {url}")
                        continue
                        
                    # This is the outer loop index, used for re-referencing elements if necessary
                    i = 0 
                    while i < len(all_elements):
                        element = all_elements[i]
                        
                        raw_name = await element.get_attribute("title")
                        if not raw_name:
                            i += 1
                            continue

                        # Map channel info from local dictionary
                        normalized_name = normalize_channel_name(raw_name)
                        mapped_info = {}
                        for channel_data in CHANNEL_MAPPING.values():
                            if any(keyword in normalized_name for keyword in channel_data.get("keywords", [])):
                                mapped_info = channel_data
                                break

                        new_name = mapped_info.get("name", prettify_name(raw_name))
                        tv_id = mapped_info.get("tv_id", "")
                        logo = mapped_info.get("logo", await element.get_attribute("data-logo"))
                        group_title = mapped_info.get("group", "FSTV")
                        last_m3u8_url = None

                        # 2. Click and capture the stream URL using expect_request (ROBUST FIX)
                        for attempt in range(1, MAX_RETRIES + 1):
                            err_print(f"👆 Clicking {new_name} ({i+1}/{len(all_elements)}) [Attempt {attempt}]...")
                            
                            try:
                                # Use expect_request to wait for the network call to be triggered by the click
                                async with page.expect_request(m3u8_pattern, timeout=15000) as request_info:
                                    # Perform the click that should trigger the request
                                    await element.click(force=True, timeout=10000) 
                                
                                # Get the request object and the URL
                                request = await request_info.value
                                last_m3u8_url = request.url
                                break # Success
                            
                            except PlaywrightTimeoutError:
                                err_print(f"⚠️ Attempt {attempt} timed out waiting for stream URL for {new_name}")
                                # After a failed click, the internal iframe state is often broken.
                                # The best approach is often to reload the page to reset the context.
                                if attempt < MAX_RETRIES:
                                    err_print(f"🔄 Reloading page to reset context before next attempt...")
                                    await page.goto(url, timeout=30000, wait_until="domcontentloaded")
                                    await page.wait_for_selector(".item-channel", timeout=30000)
                                    # Re-query elements and get the element for the current index 'i'
                                    all_elements = await page.query_selector_all(".item-channel")
                                    if i < len(all_elements):
                                        element = all_elements[i]
                                    else:
                                        err_print(f"❌ Failed to re-find element after reload. Breaking loop.")
                                        break
                                else:
                                    err_print(f"❌ Giving up on {new_name} after {MAX_RETRIES} attempts.")
                                    break
                            
                            except Exception as e:
                                # Catch unexpected errors, including context-related issues
                                err_print(f"⚠️ Attempt {attempt} failed due to unexpected error for {new_name}: {e}")
                                await asyncio.sleep(random.uniform(1, 2))


                        # 3. Add to final list
                        if last_m3u8_url and last_m3u8_url not in visited_urls and "false" not in last_m3u8_url.lower():
                            scraped_data.append({
                                "url": last_m3u8_url,
                                "logo": logo,
                                "name": new_name,
                                "tv_id": tv_id,
                                "group": group_title
                            })
                            visited_urls.add(last_m3u8_url)
                            # Print the full last_m3u8_url to stderr for logging
                            err_print(f"✅ Added {new_name} → {last_m3u8_url}")
                        else:
                            err_print(f"❌ Skipping {new_name}: No valid URL captured after {MAX_RETRIES} attempts.")
                        
                        i += 1 # Move to the next channel

                    err_print(f"🎉 Processed all channels from {url}")
                    
                    # Return immediately on successful mirror processing
                    return scraped_data

                except Exception as e:
                    err_print(f"❌ Failed processing mirror {url}: {e}")
                    await asyncio.sleep(5) # Wait before trying next mirror
                    continue

            # If the script reaches here, all mirrors failed
            raise Exception("❌ All mirrors failed after all attempts.")
            
        finally:
            # ESSENTIAL: This ensures the browser always closes
            if browser:
                await browser.close()
    
    return scraped_data


def build_playlist(channels_data):
    lines = ["#EXTM3U\n"]
    for ch in channels_data:
        tvg_id = f' tvg-id="{ch["tv_id"]}"' if ch["tv_id"] else ""
        logo = f' tvg-logo="{ch["logo"]}"' if ch["logo"] else ""
        # Force every channel to group FSTV regardless of mapping
        group = ' group-title="FSTV"'

        lines.append(f'#EXTINF:-1{tvg_id}{logo}{group},{ch["name"]}\n')
        lines.append(
            "#EXTVLCOPT:http-origin=https://fstv.space\n"
            "#EXTVLCOPT:http-referrer=https://fstv.space/\n"
            "#EXTVLCOPT:http-user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:141.0) Gecko/20100101 Firefox/141.0\n"
        )
        lines.append(ch["url"] + "\n")
    return "".join(lines)


if __name__ == "__main__":
    # --- Output Filename Defined Here ---
    OUTPUT_FILENAME = "FSTV24.m3u8"
    # ------------------------------------
    
    try:
        channels_data = asyncio.run(fetch_fstv_channels())
    except Exception as e:
        err_print(f"❌ Scrape failed completely. Check logs for mirror failures: {e}")
        sys.exit(1)

    if not channels_data:
        err_print("❌ No channels scraped. Exiting.")
        sys.exit(1)

    # --- NEW: Write to local file instead of sys.stdout ---
    try:
        playlist_content = build_playlist(channels_data)
        with open(OUTPUT_FILENAME, "w", encoding="utf-8") as f:
            f.write(playlist_content)
        
        err_print(f"\n✅ Scrape complete. {len(channels_data)} channels found.")
        err_print(f"💾 Playlist successfully saved to {OUTPUT_FILENAME}")
    except IOError as e:
        err_print(f"❌ ERROR: Could not write playlist to file {OUTPUT_FILENAME}: {e}")
        sys.exit(1)