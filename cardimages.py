#!/usr/bin/env python3
"""Private local mirror of LotR LCG card images, keyed by OCTGN id.

Sources (in order of preference):
  1. RingsDB          https://ringsdb.com/bundles/cards/<code>.png  (player cards, ALeP in higher res)
  2. DragnCards S3    https://dragncards-lotrlcg.s3.amazonaws.com/cards/English/<octgnid>.jpg
                      (all cards incl. encounter cards and back sides <octgnid>.B.jpg)

Layout under --root (default: directory of this script):
  lotr/images/<octgnid>.<jpg|png>      front
  lotr/images/<octgnid>.B.<jpg|png>    back side, when the card has one
  lotr/index.json                      lookup tables (see build_index)
  lotr/ringsdb_cards.json              last RingsDB snapshot

Usage:
  python3 cardimages.py sync [--encounter] [--workers 4]
  python3 cardimages.py deck <ringsdb url | decklist id | file.o8d> [--json] [--copy-to DIR]
  python3 cardimages.py status

Stdlib only. Images are for private use — do not redistribute.
"""
import argparse
import csv
import io
import json
import os
import re
import shutil
import struct
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

RINGSDB = "https://ringsdb.com"
S3 = "https://dragncards-lotrlcg.s3.amazonaws.com/cards/English/"
DRAGNCARDS_DB = "https://raw.githubusercontent.com/seastan/dragncards-lotrlcg-plugin/main/tsvs/cardDb.tsv"
USER_AGENT = "private-deckprinter-image-sync/1.0"
DEFAULT_ROOT = os.path.dirname(os.path.abspath(__file__))


# ---------- HTTP ----------

def fetch(url, retries=3):
    """Returns the response body, or None on 403/404."""
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


# ---------- Image helpers ----------

def image_info(data):
    """Returns (ext, width, height) from magic bytes, or None if not an image.
    RingsDB serves some JPEGs with a .png name, so never trust the URL."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        w, h = struct.unpack(">II", data[16:24])
        return "png", w, h
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
    `size` is the physical card size class: "standard" (63x88 mm); Arkham will add "mini"."""
    with open(os.path.join(images_dir, filename), "rb") as f:
        _, w, h = image_info(f.read(65536)) or (None, None, None)
    orientation = None if not (w and h) else ("landscape" if w > h else "portrait")
    return {"side": side, "file": filename, "width": w, "height": h,
            "orientation": orientation, "size": size}


def find_file(images_dir, stem):
    for ext in ("png", "jpg"):
        path = os.path.join(images_dir, f"{stem}.{ext}")
        if os.path.exists(path):
            return f"{stem}.{ext}"
    return None


def download(images_dir, stem, urls):
    """Downloads the first url that yields an image. Returns (filename, source_url, w, h) or None."""
    for url in urls:
        data = fetch(url)
        info = data and image_info(data)
        if not info:
            continue
        ext, w, h = info
        name = f"{stem}.{ext}"
        tmp = os.path.join(images_dir, name + ".part")
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, os.path.join(images_dir, name))
        return name, url, w, h
    return None


# ---------- Sync ----------

def ringsdb_printings(cards):
    """One entry per printing. A card reprinted in several packs has one RingsDB code
    and one OCTGN id per printing; decklists may reference any of those codes."""
    for c in cards:
        for p in c.get("packs") or [c]:
            octgnid = p.get("octgnid")
            if not octgnid:
                continue
            yield {
                "code": p.get("image_code") or c["code"],
                "card_code": c["code"],
                "octgnid": octgnid,
                "name": c["name"],
                "type": c.get("type_name"),
                "sphere": c.get("sphere_name"),
                "pack": p.get("pack_name"),
                "position": p.get("position"),
                "imagesrc": p.get("imagesrc"),
            }


def sync(root, workers=4, encounter=False, recheck_backs=False):
    lotr = os.path.join(root, "lotr")
    images_dir = os.path.join(lotr, "images")
    os.makedirs(images_dir, exist_ok=True)
    index = load_index(root) or {}
    old_printings = index.get("printings", {})

    print("Fetching RingsDB card list…")
    cards = fetch_json(f"{RINGSDB}/api/public/cards/")
    with open(os.path.join(lotr, "ringsdb_cards.json"), "w", encoding="utf-8") as f:
        json.dump(cards, f, ensure_ascii=False)
    printings = {p["code"]: p for p in ringsdb_printings(cards)}

    def work(p):
        old = old_printings.get(p["code"], {})
        stem = p["octgnid"]
        result = dict(p)
        result["source"] = old.get("source")
        front = find_file(images_dir, stem)
        if not front:
            urls = ([RINGSDB + p["imagesrc"]] if p.get("imagesrc") else []) + [f"{S3}{stem}.jpg"]
            got = download(images_dir, stem, urls)
            if got:
                front, result["source"] = got[0], got[1]
        if front and not old.get("upgrade_checked"):
            front = upgrade_low_res(images_dir, stem, front, result)
        result["upgrade_checked"] = True
        back = find_file(images_dir, stem + ".B")
        if not back and (recheck_backs or not old.get("back_checked")):
            got = download(images_dir, stem + ".B", [f"{S3}{stem}.B.jpg"])
            back = got[0] if got else None
        result["faces"] = [face(images_dir, side, f) for side, f in (("A", front), ("B", back)) if f]
        result["back_checked"] = True
        result.pop("imagesrc", None)
        return result

    # Some printings share an OCTGN id (and so an image file); fetch each file once.
    first = {}
    for p in printings.values():
        first.setdefault(p["octgnid"], p)
    print(f"Syncing {len(printings)} player-card printings ({len(first)} images) with {workers} workers…")
    done = {r["octgnid"]: r for r in run_parallel(work, list(first.values()), workers)}
    shared = ("source", "faces", "back_checked", "upgrade_checked")
    index["printings"] = {
        code: {**{k: v for k, v in p.items() if k != "imagesrc"}, **{k: done[p["octgnid"]][k] for k in shared}}
        for code, p in printings.items()
    }

    if encounter:
        index["dragncards"] = sync_dragncards(images_dir, workers, index.get("dragncards", {}))

    index["generated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    index["by_octgnid"] = build_octgn_lookup(index)
    save_index(root, index)

    missing = [p for p in index["printings"].values() if not p["faces"]]
    print(f"Done. {len(index['printings']) - len(missing)} player printings have images, {len(missing)} missing.")
    for p in missing[:30]:
        print(f"  missing: {p['code']} {p['name']} ({p['pack']})")


LOW_RES_WIDTH = 420


def upgrade_low_res(images_dir, stem, front, result):
    """Some RingsDB scans are only ~300x419; DragnCards often has the same card at ~429x600.
    Keeps whichever is wider. Returns the front filename."""
    if face(images_dir, "A", front)["width"] >= LOW_RES_WIDTH:
        return front
    data = fetch(f"{S3}{stem}.jpg")
    info = data and image_info(data)
    if not info or not info[1] or info[1] <= face(images_dir, "A", front)["width"]:
        return front
    os.remove(os.path.join(images_dir, front))
    name = f"{stem}.{info[0]}"
    with open(os.path.join(images_dir, name), "wb") as f:
        f.write(data)
    result["source"] = f"{S3}{stem}.jpg"
    return name


def sync_dragncards(images_dir, workers, old):
    """All cards in the DragnCards database (encounter, quest, campaign cards).
    ALeP is not in the public TSV; its player cards come from RingsDB instead."""
    print("Fetching DragnCards card database…")
    rows = csv.DictReader(io.StringIO(fetch(DRAGNCARDS_DB).decode("utf-8")), delimiter="\t")
    by_id = {}
    for r in rows:
        entry = by_id.setdefault(r["databaseId"], {
            "octgnid": r["databaseId"], "name": r["name"], "type": r["type"],
            "pack": r["packName"], "encounter_set": r["encounterSet"] or None,
            "card_back": r["cardBack"], "files": {},
        })
        # The `side` column is often empty on both rows of a double-sided card, so read the
        # side from the file name (<id>.B.jpg) and fall back to the column.
        url = r["imageUrl"]
        m = re.search(r"\.([B-H])\.\w+$", url)
        side = m.group(1) if m else (r.get("side") or "A")
        if side == "A":
            entry["name"], entry["type"] = r["name"], r["type"]
        entry["files"][side] = url

    def work(entry):
        faces = []
        for side, url in sorted(entry.pop("files").items()):
            # A few rows point at absolute (mostly dead) Hall of Beorn URLs instead of S3.
            stem = entry["octgnid"] + ("" if side == "A" else f".{side}")
            name = find_file(images_dir, stem)
            if not name:
                got = download(images_dir, stem, [url if url.startswith("http") else S3 + url])
                name = got[0] if got else None
            if name:
                faces.append(face(images_dir, side, name))
        # Imageless Rules cards are DragnCards-only scenario summaries that were never
        # printed; no scan exists on DragnCards, Hall of Beorn or RingsDB.
        return {**entry, "faces": faces, "virtual": not faces and entry["type"] == "Rules"}

    print(f"Syncing {len(by_id)} DragnCards cards…")
    return {e["octgnid"]: e for e in run_parallel(work, list(by_id.values()), workers)}


def run_parallel(fn, items, workers):
    results = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i, r in enumerate(pool.map(fn, items), 1):
            results.append(r)
            if i % 100 == 0 or i == len(items):
                print(f"  {i}/{len(items)}", flush=True)
    return results


# ---------- Index ----------

def index_path(root):
    return os.path.join(root, "lotr", "index.json")


def load_index(root):
    try:
        with open(index_path(root), encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None


def save_index(root, index):
    tmp = index_path(root) + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, index_path(root))


def build_octgn_lookup(index):
    """octgnid -> {name, code, faces}, merging DragnCards cards and RingsDB printings
    (RingsDB wins, it has the higher-res ALeP images)."""
    out = {}
    for e in index.get("dragncards", {}).values():
        out[e["octgnid"]] = {"name": e["name"], "code": None, "faces": e["faces"]}
    for p in index["printings"].values():
        if p["faces"] or p["octgnid"] not in out:
            out[p["octgnid"]] = {"name": p["name"], "code": p["code"], "faces": p["faces"]}
    return out


# ---------- Deck lookup (library API) ----------

class CardImageStore:
    def __init__(self, root=DEFAULT_ROOT):
        self.root = root
        self.images_dir = os.path.join(root, "lotr", "images")
        self.index = load_index(root)
        if not self.index:
            raise SystemExit("No index yet - run: python3 cardimages.py sync")

    def faces(self, faces):
        """Index faces with absolute paths. faces[0] is the front; any further entries are
        the other sides (B, and C.. for multi-sided quest cards)."""
        return [{**f, "path": os.path.join(self.images_dir, f["file"])} for f in faces]

    def by_code(self, code):
        p = self.index["printings"].get(code)
        return p and {**p, "faces": self.faces(p["faces"])}

    def by_octgnid(self, octgnid):
        e = self.index["by_octgnid"].get(octgnid)
        return e and {"octgnid": octgnid, **e, "faces": self.faces(e["faces"])}

    def resolve_deck(self, source):
        """source: RingsDB decklist/deck URL, numeric decklist id, or path to an .o8d file.
        Returns a list of {section, qty, name, code, octgnid, faces}."""
        if os.path.exists(source):
            return self._from_o8d(source)
        m = re.search(r"/(decklist|deck)/view/(\d+)", source)
        kind, deck_id = (m.group(1), m.group(2)) if m else ("decklist", source.strip())
        if not deck_id.isdigit():
            raise ValueError(f"Not a RingsDB deck url, id or existing file: {source}")
        deck = fetch_json(f"{RINGSDB}/api/public/{kind}/{deck_id}")
        if deck is None:
            raise ValueError(f"RingsDB {kind} {deck_id} not found (private decks must be shared)")
        heroes = deck.get("heroes") or {}
        entries = []
        for section, slots in (("Main", deck.get("slots") or {}), ("Sideboard", deck.get("sideslots") or {})):
            for code, qty in slots.items():
                card = self.by_code(code) or {"name": "?", "octgnid": None, "faces": []}
                sec = "Hero" if section == "Main" and code in heroes else section
                entries.append({"section": sec, "qty": qty, "name": card["name"], "code": code,
                                "octgnid": card["octgnid"], "faces": card["faces"]})
        order = {"Hero": 0, "Main": 1, "Sideboard": 2}
        return sorted(entries, key=lambda e: (order[e["section"]], e["code"]))

    def _from_o8d(self, path):
        entries = []
        for section in ET.parse(path).getroot().iter("section"):
            for card in section.iter("card"):
                octgnid = card.get("id")
                found = self.by_octgnid(octgnid) or {}
                entries.append({"section": section.get("name"), "qty": int(card.get("qty", 1)),
                                "name": found.get("name") or (card.text or "").strip(), "code": found.get("code"),
                                "octgnid": octgnid, "faces": found.get("faces", [])})
        return entries


# ---------- CLI ----------

def cmd_deck(args):
    store = CardImageStore(args.root)
    entries = store.resolve_deck(args.source)
    if args.json:
        json.dump(entries, sys.stdout, ensure_ascii=False, indent=1)
        print()
    else:
        for e in entries:
            sides = "".join(f["side"] for f in e["faces"]) or "MISSING IMAGE"
            land = " landscape" if any(f["orientation"] == "landscape" for f in e["faces"]) else ""
            print(f"{e['section']:<10} {e['qty']}x {e['name']:<35} {e['code'] or '':<7} {e['octgnid']}  {sides}{land}")
    if args.copy_to:
        os.makedirs(args.copy_to, exist_ok=True)
        n = 0
        for e in entries:
            if not e["faces"] or e["section"] == "Sideboard":
                continue
            for _ in range(e["qty"]):
                n += 1
                for f in e["faces"]:
                    suffix = "" if f["side"] == "A" else f"_{f['side']}"
                    ext = f["file"].rsplit(".", 1)[1]
                    shutil.copyfile(f["path"], os.path.join(args.copy_to, f"{n:03d}{suffix}.{ext}"))
        print(f"Copied {n} cards to {args.copy_to}", file=sys.stderr)
    missing = sum(1 for e in entries if not e["faces"])
    if missing:
        print(f"{missing} card(s) without image", file=sys.stderr)
        return 1
    return 0


def cmd_status(args):
    index = CardImageStore(args.root).index
    p = index["printings"].values()
    have = [x for x in p if x["faces"]]
    print(f"Generated: {index['generated']}")
    print(f"Player printings: {len(have)}/{len(p)} with image, {sum(1 for x in p if len(x['faces']) > 1)} double-sided")
    print(f"From RingsDB: {sum(1 for x in have if (x.get('source') or '').startswith(RINGSDB))}, "
          f"from DragnCards: {sum(1 for x in have if (x.get('source') or '').startswith(S3))}")
    if "dragncards" in index:
        d = index["dragncards"].values()
        missing = [e for e in d if not e["faces"] and not e.get("virtual")]
        print(f"DragnCards cards (incl. encounter): {len(d)}, "
              f"{sum(1 for e in d if e.get('virtual'))} unprinted DragnCards rules cards, {len(missing)} missing")
        for e in missing[:30]:
            print(f"  missing: {e['name']} ({e['pack']}) {e['octgnid']}")
    images_dir = os.path.join(args.root, "lotr", "images")
    size = sum(e.stat().st_size for e in os.scandir(images_dir))
    print(f"Images on disk: {len(os.listdir(images_dir))} files, {size / 1e6:.0f} MB")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=DEFAULT_ROOT)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sync", help="download new/missing images and rebuild the index")
    s.add_argument("--encounter", action="store_true", help="also mirror all DragnCards cards (encounter etc.)")
    s.add_argument("--workers", type=int, default=4)
    s.add_argument("--recheck-backs", action="store_true", help="look for back sides again on every card")
    d = sub.add_parser("deck", help="resolve a deck to local image files")
    d.add_argument("source")
    d.add_argument("--json", action="store_true")
    d.add_argument("--copy-to", help="copy one image per card copy (main deck + heroes) into DIR")
    sub.add_parser("status")
    args = ap.parse_args()
    if args.cmd == "sync":
        sync(args.root, args.workers, args.encounter, args.recheck_backs)
    elif args.cmd == "deck":
        sys.exit(cmd_deck(args))
    else:
        cmd_status(args)


if __name__ == "__main__":
    main()
