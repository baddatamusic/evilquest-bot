"""
scrape_full.py -- Comprehensive EvilQuest asset downloader (v5)

Auth: reads token + cookies from ~/.evilquest/auth.json (written by ws_transport).
If expired, performs a fresh HTTP login first.

Run: python scrape_full.py
"""

import json
import math
import re
import sys
import time
import random
import urllib.parse
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BASE_URL   = "https://evilquest.net"
OUTPUT_DIR = Path("gameassets")
STATE_DIR  = Path.home() / ".evilquest"

# Timeouts: (connect_s, read_s) -- never hang longer than read_s
TIMEOUT = (6, 20)

# Delay between successful downloads (seconds) -- randomised around this
DELAY_MIN = 0.30
DELAY_MAX = 0.80

# Extra backoff after a non-404 HTTP error
ERR_DELAY = 2.0

# How many consecutive errors before we abort a section
MAX_ERRORS = 10

# ---------------------------------------------------------------------------
# Session setup
# ---------------------------------------------------------------------------

def _make_session(token: str, cookie_str: str) -> requests.Session:
    """Create a requests.Session with browser headers, auth, and retry logic."""
    s = requests.Session()

    # Retry on transient network failures only -- not on 4xx/5xx
    adapter = HTTPAdapter(
        max_retries=Retry(
            total=3,
            backoff_factor=1.0,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
            raise_on_status=False,
        ),
        pool_connections=4,
        pool_maxsize=4,
    )
    s.mount("https://", adapter)
    s.mount("http://",  adapter)

    s.headers.update({
        "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/124.0.0.0 Safari/537.36",
        "Accept":          "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer":         "https://evilquest.net/play",
        "Origin":          "https://evilquest.net",
        "Sec-Fetch-Site":  "same-origin",
        "Sec-Fetch-Mode":  "no-cors",
        "Sec-Fetch-Dest":  "empty",
        "Authorization":   "Bearer " + token,
    })

    # Set every cookie from the auth.json cookie string
    for part in cookie_str.split(";"):
        part = part.strip()
        if "=" in part:
            name, _, val = part.partition("=")
            s.cookies.set(name.strip(), val.strip(), domain="evilquest.net")

    return s


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def load_auth():
    """
    Return (token, device_id, cookie_str) from ~/.evilquest/auth.json.
    Raises SystemExit if missing or expired -- caller must re-run the bot first.
    """
    auth_path = STATE_DIR / "auth.json"
    if not auth_path.exists():
        sys.exit("[auth] ~/.evilquest/auth.json not found -- run the bot once to log in first.")

    data = json.loads(auth_path.read_text())
    token     = data.get("token", "")
    device_id = data.get("device_id", "")
    cookies   = data.get("cookie", "")
    ts        = data.get("ts", 0)

    age_h = (time.time() - ts) / 3600
    if age_h > 23:
        sys.exit("[auth] auth.json is {:.1f} h old (>23 h) -- run the bot once to refresh.".format(age_h))

    print("[auth] token age {:.1f} h, device_id={}".format(age_h, device_id))
    return token, device_id, cookies


# ---------------------------------------------------------------------------
# Core downloader
# ---------------------------------------------------------------------------

class Downloader:
    def __init__(self, session: requests.Session):
        self.session    = session
        self.seen: set  = set()
        self.ok         = 0
        self.skipped    = 0
        self.errors     = 0
        self.not_found  = 0

    def dest(self, path: str) -> Path:
        parsed = urllib.parse.urlparse(path)
        rel    = urllib.parse.unquote(parsed.path).lstrip("/")
        if parsed.query:
            safe_q = re.sub(r'[<>:"/\\|?*]', "_", parsed.query)
            stem   = Path(rel).stem
            suf    = Path(rel).suffix or ".json"
            rel    = str(Path(rel).parent / (stem + "__" + safe_q + suf))
        return OUTPUT_DIR / rel

    def fetch(self, path: str, force: bool = False):
        """Download path; return bytes or None.  Skips existing files."""
        if path in self.seen:
            return None
        self.seen.add(path)

        target = self.dest(path)
        if not force and target.exists():
            self.skipped += 1
            return target.read_bytes()

        url = BASE_URL + urllib.parse.quote(path, safe="/:@!$&()*+,;=~-._?=%")
        try:
            r = self.session.get(url, timeout=TIMEOUT)
        except requests.exceptions.Timeout:
            print("  TIMEOUT  {}".format(path))
            self.errors += 1
            time.sleep(ERR_DELAY)
            return None
        except requests.exceptions.ConnectionError as e:
            print("  CONN-ERR  {}  ({})".format(path, e))
            self.errors += 1
            time.sleep(ERR_DELAY)
            return None
        except Exception as e:
            print("  ERR  {}  {}".format(path, e))
            self.errors += 1
            time.sleep(ERR_DELAY)
            return None

        if r.status_code == 200:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(r.content)
            self.ok += 1
            print("  OK   {}  ({:,} B)".format(path, len(r.content)))
            time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
            return r.content

        if r.status_code == 404:
            self.not_found += 1
            return None   # expected, don't log, don't delay

        if r.status_code == 401:
            print("  401  {}  [auth expired -- run bot to refresh token]".format(path))
            self.errors += 1
            time.sleep(ERR_DELAY)
            return None

        if r.status_code == 429:
            retry_after = int(r.headers.get("Retry-After", "10"))
            print("  429  {}  -- rate limited, sleeping {}s".format(path, retry_after))
            time.sleep(retry_after + random.uniform(1, 3))
            self.errors += 1
            return None

        print("  {}  {}".format(r.status_code, path))
        self.errors += 1
        time.sleep(ERR_DELAY)
        return None

    def fetch_json(self, path: str, force: bool = False):
        data = self.fetch(path, force=force)
        if data is None:
            return None
        try:
            return json.loads(data)
        except Exception:
            return None

    def fetch_gltf(self, path: str) -> None:
        """Fetch a .gltf and recursively pull all its .bin / image URIs."""
        data = self.fetch(path)
        if not data:
            return
        try:
            gltf = json.loads(data)
        except Exception:
            return
        base = path.rsplit("/", 1)[0] + "/"
        for key in ("buffers", "images"):
            for item in gltf.get(key, []):
                uri = item.get("uri", "")
                if uri and not uri.startswith("data:"):
                    self.fetch(urllib.parse.urljoin(base, uri))


# Regex to pull any absolute path ending in a known asset extension
ASSET_RE = re.compile(
    r'"(/[^"]{3,300}\.(glb|gltf|png|jpg|jpeg|bin|wav|ogg|mp3|basis|ktx|dds|atlas|xml|json))"',
    re.IGNORECASE,
)

def extract_asset_paths(text: str):
    return [m.group(1) for m in ASSET_RE.finditer(text)]


# ---------------------------------------------------------------------------
# Step 1: Live JS bundles
# ---------------------------------------------------------------------------

def step_js_bundles(dl: Downloader) -> None:
    print("\n=== 1. JS bundles ===")

    # Fetch /play as a browser would
    try:
        r = dl.session.get(
            BASE_URL + "/play",
            timeout=TIMEOUT,
            headers={"Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                     "Sec-Fetch-Mode": "navigate",
                     "Sec-Fetch-Dest": "document"},
        )
        r.raise_for_status()
        html = r.text
        print("  /play HTML fetched ({:,} chars)".format(len(html)))
    except Exception as e:
        print("  ERR fetching /play:", e)
        html = ""

    # Extract all script/modulepreload hrefs from HTML
    found = set()
    for m in re.finditer(r'(?:src|href)=["\']([^"\']+\.js(?:\?[^"\']*)?)["\']', html):
        h = m.group(1)
        found.add("/assets/" + h.lstrip("/") if not h.startswith("/") else h)
    for m in re.finditer(r'modulepreload[^>]*?href=["\']([^"\']+)["\']', html):
        h = m.group(1)
        found.add("/assets/" + h.lstrip("/") if not h.startswith("/") else h)

    for path in sorted(found):
        data = dl.fetch(path)
        # Scan each downloaded JS for dynamic imports of other /assets/*.js bundles
        # (e.g. GameManager is not in HTML but referenced inside index-*.js)
        if data:
            text = data.decode("utf-8", errors="ignore")
            for ref in re.findall(r'["\']([A-Za-z0-9_\-]+\.js)["\']', text):
                candidate = "/assets/" + ref
                dl.fetch(candidate)

    # Fetch assets.json href if in HTML
    for m in re.finditer(r'(?:src|href)=["\']([^"\']+assets\.json[^"\']*)["\']', html):
        dl.fetch(m.group(1))

    # Probe known companion bundle names that may not appear in HTML
    # (versioned names from current and previous deploys)
    companions = [
        # babylon engine builds
        "/assets/babylon-core-CFbJrqqe.js",
        "/assets/babylon-core-4XBUd39F.js",
        "/assets/babylon-loaders-D3MWuD9g.js",
        # game bundles
        "/assets/GameManager-DCJfmSEz.js",
        "/assets/GameManager-DDbuhVzL.js",
        "/assets/BakeApp-BvwGHX7r.js",
        "/assets/ItemIcon-DBCgjIv3.js",
        "/assets/ThumbnailRenderer-CftYr97R.js",
        "/assets/deviceId-BRNXmaxb.js",
    ]
    for p in companions:
        dl.fetch(p)


# ---------------------------------------------------------------------------
# Step 2: Data JSON files
# ---------------------------------------------------------------------------

DATA_PATHS = [
    "/data/items.json",       "/data/npcs.json",
    "/data/objects.json",     "/data/gear-overrides.json",
    "/data/quests.json",      "/data/thumbnail-overrides.json",
    "/data/tiles.json",       "/data/maps.json",
    "/data/skills.json",      "/data/spells.json",
    "/data/shops.json",       "/data/drops.json",
    "/data/spawns.json",      "/data/world.json",
    "/data/zones.json",       "/data/config.json",
    "/data/skills-config.json","/data/combat-config.json",
    "/data/entities.json",    "/data/projectiles.json",
    "/data/sounds.json",      "/data/animations.json",
    "/data/achievements.json","/data/dialogue.json",
    "/data/crafting.json",    "/data/fishing.json",
    "/data/farming.json",     "/data/mining.json",
    "/data/smithing.json",    "/data/loot-tables.json",
]

def step_data_files(dl: Downloader) -> None:
    print("\n=== 2. Data JSON files ===")
    for path in DATA_PATHS:
        dl.fetch(path)


# ---------------------------------------------------------------------------
# Step 3: Map chunks
# ---------------------------------------------------------------------------

def _fetch_map(dl: Downloader, map_id) -> bool:
    """Download all chunks for a single map. Returns True if map exists."""
    meta = dl.fetch_json("/maps/{}/meta.json".format(map_id))
    if meta is None:
        return False

    width  = int(meta.get("width",  meta.get("w",  0)))
    height = int(meta.get("height", meta.get("h",  0)))
    print("  [MAP {}] {}x{}  name={}".format(
        map_id, width, height, meta.get("name", "?")))

    # Per-map static files
    for fname in ("walls.json", "biomes.json"):
        dl.fetch("/maps/{}/{}".format(map_id, fname))
    dl.fetch("/maps/{}/map.json?chunked=1".format(map_id))
    dl.fetch("/maps/{}/map.json".format(map_id))

    if not (width and height):
        return True

    # tiles + objects use 32-tile chunks; heights use 64-tile chunks
    for chunk_size, kinds in [
        (32, ["tiles", "objects"]),
        (64, ["heights"]),
    ]:
        cx_max = math.ceil(width  / chunk_size)
        cz_max = math.ceil(height / chunk_size)
        coords = [(cx, cz) for cx in range(cx_max) for cz in range(cz_max)]
        random.shuffle(coords)
        print("    chunk_size={:2d}  grid={}x{}  kinds={}".format(
            chunk_size, cx_max, cz_max, kinds))
        for cx, cz in coords:
            ks = kinds[:]
            random.shuffle(ks)
            for kind in ks:
                dl.fetch("/maps/{}/{}/chunk_{}_{}.json".format(map_id, kind, cx, cz))

    return True


def step_maps(dl: Downloader) -> None:
    print("\n=== 3. Map data ===")

    # Collect map IDs from maps.json if available
    maps_path = OUTPUT_DIR / "data" / "maps.json"
    disc = []
    if maps_path.exists():
        try:
            md = json.loads(maps_path.read_text())
            if isinstance(md, list):
                disc = [str(m.get("id") or m.get("mapId") or "") for m in md
                        if isinstance(m, dict)]
            elif isinstance(md, dict):
                disc = list(md.keys())
            disc = [x for x in disc if x]
            print("  maps.json -> {}".format(disc))
        except Exception as e:
            print("  maps.json parse err:", e)

    named   = ["kcmap", "tutorial", "overworld", "world",
                "dungeon", "cave", "mine", "interior", "town", "bank"]
    numeric = [str(i) for i in range(40)]
    all_ids = list(dict.fromkeys(disc + named + numeric))

    found = []
    for mid in all_ids:
        if _fetch_map(dl, mid):
            found.append(mid)
    print("\n  Maps downloaded: {}".format(found))


# ---------------------------------------------------------------------------
# Step 4: assets.json manifest
# ---------------------------------------------------------------------------

def step_assets_manifest(dl: Downloader) -> None:
    print("\n=== 4. Assets manifest ===")
    assets = dl.fetch_json("/assets/assets.json")
    if assets is None:
        # Try on-disk copy
        p = OUTPUT_DIR / "assets" / "assets.json"
        if p.exists():
            assets = json.loads(p.read_text())
        else:
            print("  assets.json not available")
            return

    text  = json.dumps(assets)
    paths = extract_asset_paths(text)
    print("  {} asset paths in assets.json".format(len(paths)))
    for path in paths:
        if path.endswith(".gltf"):
            dl.fetch_gltf(path)
        else:
            dl.fetch(path)

    # textures sub-manifest
    tex = dl.fetch_json("/assets/textures/textures.json")
    if tex:
        for p in extract_asset_paths(json.dumps(tex)):
            dl.fetch(p)
    dl.fetch("/assets/textures/1.png")


# ---------------------------------------------------------------------------
# Step 5-8: Model / sprite enumeration from data files
# ---------------------------------------------------------------------------

def step_equipment_models(dl: Downloader) -> None:
    print("\n=== 5. Equipment models (items.json) ===")
    items_path = OUTPUT_DIR / "data" / "items.json"
    if not items_path.exists():
        print("  items.json not on disk"); return
    items = json.loads(items_path.read_text())
    rows  = items if isinstance(items, list) else list(items.values())
    slots = set()
    for item in rows:
        slot  = (item.get("equipSlot") or item.get("slot") or
                 item.get("equip_slot") or "")
        model = item.get("model") or ""
        if not (slot and model):
            continue
        ext = "" if Path(model).suffix else ".glb"
        p = "/assets/equipment/{}/{}{}".format(slot, model, ext)
        if p.endswith(".gltf"):
            dl.fetch_gltf(p)
        else:
            dl.fetch(p)
        slots.add(slot)
    print("  Equipment slots: {}".format(sorted(slots)))


def step_npc_models(dl: Downloader) -> None:
    print("\n=== 6. NPC models (npcs.json) ===")
    p = OUTPUT_DIR / "data" / "npcs.json"
    if not p.exists():
        return
    rows = json.loads(p.read_text())
    rows = rows if isinstance(rows, list) else list(rows.values())
    for npc in rows:
        for key in ("model", "modelPath", "mesh"):
            m = npc.get(key, "")
            if m:
                path = m if m.startswith("/") else "/assets/models/npcs/{}".format(m)
                if not Path(path).suffix:
                    path += ".glb"
                dl.fetch(path); break


def step_object_models(dl: Downloader) -> None:
    print("\n=== 7. Object models (objects.json) ===")
    p = OUTPUT_DIR / "data" / "objects.json"
    if not p.exists():
        return
    rows = json.loads(p.read_text())
    rows = rows if isinstance(rows, list) else list(rows.values())
    for obj in rows:
        for key in ("model", "modelPath", "mesh", "asset"):
            m = obj.get(key, "")
            if m:
                path = m if m.startswith("/") else "/assets/models/objects/{}".format(m)
                if not Path(path).suffix:
                    path += ".glb"
                dl.fetch(path); break


def step_item_sprites(dl: Downloader) -> None:
    print("\n=== 8. Item sprites / thumbnails ===")
    p = OUTPUT_DIR / "data" / "items.json"
    if not p.exists():
        return
    rows = json.loads(p.read_text())
    rows = rows if isinstance(rows, list) else list(rows.values())
    for item in rows:
        if item.get("sprite"):
            dl.fetch("/sprites/items/{}".format(item["sprite"]))
        if item.get("id"):
            dl.fetch("/items/3d/{}.png".format(item["id"]))


def step_sounds(dl: Downloader) -> None:
    print("\n=== 9. Sounds ===")
    p = OUTPUT_DIR / "data" / "sounds.json"
    if not p.exists():
        return
    rows = json.loads(p.read_text())
    rows = rows if isinstance(rows, list) else list(rows.values())
    for s in rows:
        for key in ("file", "path", "src"):
            f = s.get(key, "")
            if f:
                path = f if f.startswith("/") else "/assets/sounds/{}".format(f)
                dl.fetch(path); break


# ---------------------------------------------------------------------------
# Step 10: sweep all downloaded JSON for any paths we missed
# ---------------------------------------------------------------------------

def step_sweep_downloaded(dl: Downloader) -> None:
    print("\n=== 10. Sweep downloaded JSON for missed asset paths ===")
    new_paths = 0
    for fpath in sorted(OUTPUT_DIR.rglob("*.json")):
        try:
            text = fpath.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for p in extract_asset_paths(text):
            if not dl.dest(p).exists() and p not in dl.seen:
                if p.endswith(".gltf"):
                    dl.fetch_gltf(p)
                else:
                    dl.fetch(p)
                new_paths += 1
    print("  {} additional paths swept".format(new_paths))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    token, device_id, cookies = load_auth()
    session = _make_session(token, cookies)
    dl = Downloader(session)

    OUTPUT_DIR.mkdir(exist_ok=True)

    step_js_bundles(dl)
    step_data_files(dl)
    step_maps(dl)
    step_assets_manifest(dl)
    step_equipment_models(dl)
    step_npc_models(dl)
    step_object_models(dl)
    step_item_sprites(dl)
    step_sounds(dl)
    step_sweep_downloaded(dl)

    print("\n" + "=" * 56)
    print("  Downloaded  : {:,} new files".format(dl.ok))
    print("  Skipped     : {:,} already on disk".format(dl.skipped))
    print("  Not found   : {:,} (404)".format(dl.not_found))
    print("  Errors      : {:,}".format(dl.errors))
    print("=" * 56)


if __name__ == "__main__":
    main()
