"""
update_assets.py -- Targeted asset updater for EvilQuest bot (v5)

Fixes the gaps identified by audit:
  1. Refresh assets.json + download anything new it references
  2. Fetch the 16 missing data JSON files
  3. Refresh stale data files (items/npcs/objects -- 3 days old)
  4. Download missing assets/sprites and assets/sounds directories
  5. Fill any gaps in models, equipment, interactive-objects from items/npcs/objects data
  6. Probe for additional maps beyond kcmap
  7. Delete stale JS bundles no longer served by the CDN

Run: python update_assets.py
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

BASE_URL   = "https://evilquest.net"
OUTPUT_DIR = Path("gameassets")
STATE_DIR  = Path.home() / ".evilquest"
TIMEOUT    = (6, 20)

# --- Session -----------------------------------------------------------------

def make_session():
    auth_path = STATE_DIR / "auth.json"
    if not auth_path.exists():
        sys.exit("auth.json not found -- run the bot once to log in.")
    data      = json.loads(auth_path.read_text())
    token     = data["token"]
    cookies   = data.get("cookie", "")
    age_h     = (time.time() - data.get("ts", 0)) / 3600
    if age_h > 23:
        sys.exit("auth.json is {:.1f}h old -- run the bot to refresh.".format(age_h))
    print("[auth] token age {:.1f}h".format(age_h))

    s = requests.Session()
    adapter = HTTPAdapter(
        max_retries=Retry(total=3, backoff_factor=1.0,
                          status_forcelist=[429, 500, 502, 503, 504],
                          allowed_methods=["GET"], raise_on_status=False),
        pool_connections=2, pool_maxsize=2,
    )
    s.mount("https://", adapter)
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
    for part in cookies.split(";"):
        part = part.strip()
        if "=" in part:
            name, _, val = part.partition("=")
            s.cookies.set(name.strip(), val.strip(), domain="evilquest.net")
    return s

SESSION = None
ok = skip = err = notfound = 0
seen: set = set()

def dest(path):
    parsed = urllib.parse.urlparse(path)
    rel    = urllib.parse.unquote(parsed.path).lstrip("/")
    if parsed.query:
        safe_q = re.sub(r'[<>:"/\\|?*]', "_", parsed.query)
        stem, suf = Path(rel).stem, Path(rel).suffix or ".json"
        rel = str(Path(rel).parent / (stem + "__" + safe_q + suf))
    return OUTPUT_DIR / rel

def fetch(path, force=False):
    global ok, skip, err, notfound
    if path in seen:
        return None
    seen.add(path)
    target = dest(path)
    if not force and target.exists():
        skip += 1
        return target.read_bytes()
    url = BASE_URL + urllib.parse.quote(path, safe="/:@!$&()*+,;=~-._?=%")
    try:
        r = SESSION.get(url, timeout=TIMEOUT)
    except requests.exceptions.Timeout:
        print("  TIMEOUT  " + path); err += 1; time.sleep(3); return None
    except requests.exceptions.ConnectionError as e:
        print("  CONN-ERR  {}  {}".format(path, e)); err += 1; time.sleep(3); return None
    except Exception as e:
        print("  ERR  {}  {}".format(path, e)); err += 1; time.sleep(2); return None

    if r.status_code == 200:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(r.content)
        ok += 1
        print("  OK   {}  ({:,} B)".format(path, len(r.content)))
        time.sleep(random.uniform(0.30, 0.75))
        return r.content
    if r.status_code == 404:
        notfound += 1; return None
    if r.status_code == 429:
        wait = int(r.headers.get("Retry-After", "15"))
        print("  429  {} -- sleeping {}s".format(path, wait))
        time.sleep(wait + 2); err += 1; return None
    if r.status_code == 401:
        print("  401  {} -- token expired".format(path)); err += 1; return None
    print("  {}  {}".format(r.status_code, path)); err += 1; time.sleep(2); return None

def fetch_json(path, force=False):
    d = fetch(path, force=force)
    if d is None: return None
    try: return json.loads(d)
    except Exception: return None

def fetch_gltf(path):
    d = fetch(path)
    if not d: return
    try: gltf = json.loads(d)
    except Exception: return
    base = path.rsplit("/", 1)[0] + "/"
    for key in ("buffers", "images"):
        for item in gltf.get(key, []):
            uri = item.get("uri", "")
            if uri and not uri.startswith("data:"):
                fetch(urllib.parse.urljoin(base, uri))

ASSET_RE = re.compile(
    r'"(/[^"]{3,300}\.(glb|gltf|png|jpg|jpeg|bin|wav|ogg|mp3|basis|ktx|dds|atlas|xml|json))"',
    re.IGNORECASE,
)
def extract_paths(text):
    return [m.group(1) for m in ASSET_RE.finditer(text)]

# --- Step 1: Refresh assets.json + pull new assets ---------------------------

def step_refresh_assets_json():
    print("\n=== 1. Refresh assets.json ===")
    # Force-download the current assets.json (3 days old on disk)
    assets = fetch_json("/assets/assets.json", force=True)
    if assets is None:
        # Try reading from disk
        p = OUTPUT_DIR / "assets" / "assets.json"
        if p.exists():
            assets = json.loads(p.read_text())
        else:
            print("  assets.json not available"); return

    text  = json.dumps(assets)
    paths = extract_paths(text)
    print("  {} asset paths in assets.json".format(len(paths)))

    new_count = 0
    for path in paths:
        target = dest(path)
        if not target.exists():
            new_count += 1
            if path.endswith(".gltf"):
                fetch_gltf(path)
            else:
                fetch(path)
    print("  {} paths not yet on disk -- fetched above".format(new_count))

    # textures sub-manifest
    tex = fetch_json("/assets/textures/textures.json", force=True)
    if tex:
        for p in extract_paths(json.dumps(tex)):
            fetch(p)

# --- Step 2: Missing data JSON files -----------------------------------------

MISSING_DATA = [
    "/data/tiles.json",        "/data/maps.json",
    "/data/skills.json",       "/data/spells.json",
    "/data/shops.json",        "/data/drops.json",
    "/data/spawns.json",       "/data/world.json",
    "/data/zones.json",        "/data/config.json",
    "/data/skills-config.json","/data/combat-config.json",
    "/data/entities.json",     "/data/projectiles.json",
    "/data/sounds.json",       "/data/animations.json",
]

STALE_DATA = [
    # Present but 3 days old -- re-fetch to pick up any server-side changes
    "/data/items.json",        "/data/npcs.json",
    "/data/objects.json",      "/data/gear-overrides.json",
    "/data/quests.json",       "/data/thumbnail-overrides.json",
]

def step_data_files():
    print("\n=== 2. Missing data files ===")
    for path in MISSING_DATA:
        fetch(path)

    print("\n=== 3. Refresh stale data files (3 days old) ===")
    for path in STALE_DATA:
        fetch(path, force=True)

# --- Step 3: Sprites directory -----------------------------------------------

def step_sprites():
    print("\n=== 4. Sprites (directory missing) ===")
    # Enumerate from items.json
    items_path = OUTPUT_DIR / "data" / "items.json"
    if items_path.exists():
        rows = json.loads(items_path.read_text())
        rows = rows if isinstance(rows, list) else list(rows.values())
        for item in rows:
            if item.get("sprite"):
                fetch("/sprites/items/{}".format(item["sprite"]))
                fetch("/assets/sprites/items/{}".format(item["sprite"]))
            if item.get("id"):
                fetch("/assets/sprites/items/{}.png".format(item["id"]))
                fetch("/items/3d/{}.png".format(item["id"]))

    # Common sprite sheet paths
    for path in [
        "/assets/sprites/sprites.json",
        "/assets/sprites/atlas.json",
        "/assets/sprites/items.json",
        "/assets/sprites/icons.png",
        "/sprites/sprites.json",
        "/sprites/items.json",
    ]:
        fetch(path)

# --- Step 4: Sounds directory ------------------------------------------------

def step_sounds():
    print("\n=== 5. Sounds (directory missing) ===")
    sounds_path = OUTPUT_DIR / "data" / "sounds.json"
    if sounds_path.exists():
        rows = json.loads(sounds_path.read_text())
        rows = rows if isinstance(rows, list) else list(rows.values())
        for s in rows:
            for key in ("file", "path", "src"):
                f = s.get(key, "")
                if f:
                    path = f if f.startswith("/") else "/assets/sounds/{}".format(f)
                    fetch(path); break

    # Probe common sound manifest paths
    for path in [
        "/assets/sounds/sounds.json",
        "/data/sounds.json",
    ]:
        data = fetch_json(path)
        if data:
            rows = data if isinstance(data, list) else list(data.values())
            for s in rows:
                for key in ("file", "path", "src", "url"):
                    f = s.get(key, "")
                    if f:
                        fetch(f if f.startswith("/") else "/assets/sounds/" + f)
                        break

# --- Step 5: Model gaps from data files --------------------------------------

def step_model_gaps():
    print("\n=== 6. Model gaps from npcs.json / objects.json ===")

    # NPC models
    p = OUTPUT_DIR / "data" / "npcs.json"
    if p.exists():
        rows = json.loads(p.read_text())
        rows = rows if isinstance(rows, list) else list(rows.values())
        for npc in rows:
            for key in ("model", "modelPath", "mesh"):
                m = npc.get(key, "")
                if m:
                    path = m if m.startswith("/") else "/assets/models/npcs/{}".format(m)
                    if not Path(path).suffix: path += ".glb"
                    fetch(path); break

    # Object models
    p = OUTPUT_DIR / "data" / "objects.json"
    if p.exists():
        rows = json.loads(p.read_text())
        rows = rows if isinstance(rows, list) else list(rows.values())
        for obj in rows:
            for key in ("model", "modelPath", "mesh", "asset"):
                m = obj.get(key, "")
                if m:
                    path = m if m.startswith("/") else "/assets/models/objects/{}".format(m)
                    if not Path(path).suffix: path += ".glb"
                    if path.endswith(".gltf"): fetch_gltf(path)
                    else: fetch(path)
                    break

    # Equipment from items.json
    p = OUTPUT_DIR / "data" / "items.json"
    if p.exists():
        rows = json.loads(p.read_text())
        rows = rows if isinstance(rows, list) else list(rows.values())
        for item in rows:
            slot  = (item.get("equipSlot") or item.get("slot") or
                     item.get("equip_slot") or "")
            model = item.get("model") or ""
            if slot and model:
                ext  = "" if Path(model).suffix else ".glb"
                path = "/assets/equipment/{}/{}{}".format(slot, model, ext)
                if path.endswith(".gltf"): fetch_gltf(path)
                else: fetch(path)

# --- Step 6: Additional maps -------------------------------------------------

def step_additional_maps():
    print("\n=== 7. Additional maps ===")
    # Named candidates beyond kcmap
    candidates = [
        "tutorial", "overworld", "world", "dungeon", "cave",
        "mine", "interior", "town", "bank", "shop", "castle",
        "forest", "desert", "swamp",
    ]
    # Numeric IDs 0..30
    candidates += [str(i) for i in range(31)]

    found = []
    for mid in candidates:
        meta = fetch_json("/maps/{}/meta.json".format(mid))
        if meta is None:
            continue
        found.append(mid)
        width  = int(meta.get("width",  meta.get("w",  0)))
        height = int(meta.get("height", meta.get("h",  0)))
        print("  [MAP {}] {}x{}".format(mid, width, height))

        for fname in ("walls.json", "biomes.json"):
            fetch("/maps/{}/{}".format(mid, fname))
        fetch("/maps/{}/map.json?chunked=1".format(mid))
        fetch("/maps/{}/map.json".format(mid))

        if not (width and height):
            continue

        for chunk_size, kinds in [(32, ["tiles", "objects"]), (64, ["heights"])]:
            cx = math.ceil(width  / chunk_size)
            cz = math.ceil(height / chunk_size)
            coords = [(x, z) for x in range(cx) for z in range(cz)]
            random.shuffle(coords)
            for x, z in coords:
                for kind in random.sample(kinds, len(kinds)):
                    fetch("/maps/{}/{}/chunk_{}_{}.json".format(mid, kind, x, z))

    if found:
        print("  Found maps: {}".format(found))
    else:
        print("  No additional maps found")

# --- Step 7: Sweep downloaded JSON for missed paths --------------------------

def step_sweep():
    print("\n=== 8. Sweep downloaded JSON for missed paths ===")
    swept = 0
    for fpath in sorted(OUTPUT_DIR.rglob("*.json")):
        try:
            text = fpath.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for p in extract_paths(text):
            if not dest(p).exists() and p not in seen:
                if p.endswith(".gltf"): fetch_gltf(p)
                else: fetch(p)
                swept += 1
    print("  {} additional paths found and fetched".format(swept))

# --- Step 8: Delete stale JS bundles -----------------------------------------

STALE_BUNDLES = [
    "babylon-core-4XBUd39F.js",
    "GameManager-B7gNzArI.js",
    "GameManager-DDbuhVzL.js",
    "GameManager--mOzGP1l.js",
    "index-C31rgKnD.js",
    "index-DGTyz-tl.js",
    "index-DTlu9WCm.js",
]

def step_delete_stale_bundles():
    print("\n=== 9. Delete stale JS bundles ===")
    for name in STALE_BUNDLES:
        p = OUTPUT_DIR / "assets" / name
        if p.exists():
            p.unlink()
            print("  DEL  assets/{}".format(name))
        else:
            print("  --   assets/{} (already gone)".format(name))

# --- Main --------------------------------------------------------------------

def main():
    global SESSION
    SESSION = make_session()
    OUTPUT_DIR.mkdir(exist_ok=True)

    step_refresh_assets_json()
    step_data_files()
    step_sprites()
    step_sounds()
    step_model_gaps()
    step_additional_maps()
    step_sweep()
    step_delete_stale_bundles()

    print("\n" + "=" * 56)
    print("  Downloaded  : {:,} new files".format(ok))
    print("  Skipped     : {:,} already on disk".format(skip))
    print("  Not found   : {:,} (404)".format(notfound))
    print("  Errors      : {:,}".format(err))
    print("=" * 56)

if __name__ == "__main__":
    main()
