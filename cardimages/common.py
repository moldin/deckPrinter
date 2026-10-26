"""Game-independent parts: HTTP, image sniffing, the face model, index files and the store."""
import json
import os
import struct
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

USER_AGENT = "private-deckprinter-image-sync/1.0"
DEFAULT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------- HTTP ----------

def fetch(url, retries=3):
    """Returns the response body, or None on 403/404 (S3 answers 403 for missing keys)."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (403, 404):
                return None
            if attempt == retries - 1:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == retries - 1:
                raise
        time.sleep(2 ** attempt)


def fetch_json(url):
    data = fetch(url)
    return json.loads(data) if data else None


def run_parallel(fn, items, workers):
    results = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i, r in enumerate(pool.map(fn, items), 1):
            results.append(r)
            if i % 50 == 0 or i == len(items):
                print(f"  {i}/{len(items)}", flush=True)
    return results


# ---------- Images ----------

def image_info(data):
    """Returns (ext, width, height) from magic bytes, or None if not an image.
    RingsDB serves some JPEGs with a .png name, so never trust the URL."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        w, h = struct.unpack(">II", data[16:24])
        return "png", w, h
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp", None, None
    if data[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                h, w = struct.unpack(">HH", data[i + 5:i + 9])
                return "jpg", w, h
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            i += 2 + struct.unpack(">H", data[i + 2:i + 4])[0]
        return "jpg", None, None
    return None


def face(images_dir, side, filename, size="standard"):
    """Index entry for one printed side. Dimensions are read from the local file so the
    print layer can tell landscape cards (quests, Arkham acts/agendas/investigators) apart.
    `size` is the physical card size class: "standard" (63x88 mm) or "mini" (41x63 mm)."""
    with open(os.path.join(images_dir, filename), "rb") as f:
        _, w, h = image_info(f.read(65536)) or (None, None, None)
    orientation = None if not (w and h) else ("landscape" if w > h else "portrait")
    return {"side": side, "file": filename, "width": w, "height": h,
            "orientation": orientation, "size": size}


def find_file(images_dir, stem):
    for ext in ("png", "jpg", "webp"):
        path = os.path.join(images_dir, f"{stem}.{ext}")
        if os.path.exists(path):
            return f"{stem}.{ext}"
    return None


def write_image(images_dir, stem, data, ext):
    name = f"{stem}.{ext}"
    tmp = os.path.join(images_dir, name + ".part")
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, os.path.join(images_dir, name))
    return name


def download(images_dir, stem, urls):
    """Downloads the first url that yields an image. Returns (filename, source_url) or None."""
    for url in urls:
        data = fetch(url)
        info = data and image_info(data)
        if info:
            return write_image(images_dir, stem, data, info[0]), url
    return None


def upgrade(images_dir, stem, current, url, min_gain=1.2):
    """Replaces `current` with the image at `url` if that one is at least `min_gain` times
    wider. Returns the filename to use afterwards (new or unchanged)."""
    width = face(images_dir, "A", current)["width"] or 0
    data = fetch(url)
    info = data and image_info(data)
    if not info or not info[1] or info[1] < width * min_gain:
        return current
    os.remove(os.path.join(images_dir, current))
    return write_image(images_dir, stem, data, info[0])


def fetch_card_backs(game_dir, backs):
    """Generic card backs ({kind: url}) for cards without a printed side B."""
    backs_dir = os.path.join(game_dir, "backs")
    os.makedirs(backs_dir, exist_ok=True)
    out = {}
    for kind, url in backs.items():
        name = find_file(backs_dir, kind) or (download(backs_dir, kind, [url]) or [None])[0]
        if name:
            out[kind] = os.path.join("backs", name)
    return out


# ---------- Index ----------

def index_path(root, game):
    return os.path.join(root, game, "index.json")


def load_index(root, game):
    try:
        with open(index_path(root, game), encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None


def save_index(root, game, index):
    tmp = index_path(root, game) + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, index_path(root, game))


def disk_usage(game_dir):
    files = [e for d in ("images", "backs") if os.path.isdir(os.path.join(game_dir, d))
             for e in os.scandir(os.path.join(game_dir, d))]
    return len(files), sum(e.stat().st_size for e in files)


# ---------- Store ----------

class BaseStore:
    """Read side shared by all games. Deck entries look like
    {section, qty, name, code, faces: [{side, path, width, height, orientation, size}], card_back}
    where faces[0] is the front, further faces are printed backs (B, C..), and card_back is
    the path of the generic back to use when the card has a single face."""
    game = None

    def __init__(self, root=DEFAULT_ROOT):
        self.root = root
        self.game_dir = os.path.join(root, self.game)
        self.images_dir = os.path.join(self.game_dir, "images")
        self.index = load_index(root, self.game)
        if not self.index:
            raise SystemExit(f"No {self.game} index yet - run: python3 -m cardimages {self.game} sync")

    def faces(self, faces):
        return [{**f, "path": os.path.join(self.images_dir, f["file"])} for f in faces]

    def card_back(self, kind):
        rel = self.index.get("card_backs", {}).get(kind)
        return os.path.join(self.game_dir, rel) if rel else None

    def entry(self, section, qty, card, code=None):
        return {"section": section, "qty": qty, "name": card.get("name", "?"),
                "code": code or card.get("code"), "faces": card.get("faces", []),
                "card_back": None if len(card.get("faces", [])) > 1 else self.card_back(card.get("card_back"))}
