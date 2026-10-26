"""Lord of the Rings LCG: images keyed by OCTGN id.

Sources:
  RingsDB        ringsdb.com/bundles/cards/<code>.png         player cards (ALeP at 750x1050)
  DragnCards S3  .../cards/English/<octgnid>[.B].jpg           all cards, encounter cards, back sides
  Hall of Beorn  .../Images/Cards/<Pack>/<Name>.jpg            upgrade pass: ~1/4 of cards exist at
                                                               up to 1466x2093 (~600 dpi printed)

Layout: lotr/images/<octgnid>.<ext>, <octgnid>.B.<ext> (C.. for multi-sided quests),
        lotr/backs/{player,encounter}.jpg, lotr/index.json, lotr/ringsdb_cards.json
"""
import csv
import io
import json
import os
import re
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from .common import (BaseStore, DEFAULT_ROOT, disk_usage, download, face, fetch, fetch_card_backs,
                     fetch_json, find_file, load_index, run_parallel, save_index, upgrade)

GAME = "lotr"
RINGSDB = "https://ringsdb.com"
S3 = "https://dragncards-lotrlcg.s3.amazonaws.com/cards/English/"
HOB = "https://s3.amazonaws.com/hallofbeorn-resources/Images/Cards/"
DRAGNCARDS_REPO = "seastan/dragncards-lotrlcg-plugin"
DRAGNCARDS_DB = f"https://raw.githubusercontent.com/{DRAGNCARDS_REPO}/main/tsvs/cardDb.tsv"
# The alep branch holds one TSV per ALeP set (incl. encounter cards); skip work-in-progress sets.
ALEP_TREE = f"https://api.github.com/repos/{DRAGNCARDS_REPO}/git/trees/alep?recursive=1"
ALEP_RAW = f"https://raw.githubusercontent.com/{DRAGNCARDS_REPO}/alep/"
ALEP_SKIP = re.compile(r"Scratch|Backup|Placeholder")
CARD_BACKS = {"player": "https://dragncards-lotrlcg.s3.amazonaws.com/cardbacks/player.jpg",
              "encounter": "https://dragncards-lotrlcg.s3.amazonaws.com/cardbacks/encounter.jpg"}
LOW_RES_WIDTH = 420     # below this, try DragnCards for a better scan
HOB_TRY_BELOW = 700     # below this, try Hall of Beorn for a better scan


def hob_slug(text):
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[’'!,.:?]", "", text)
    return re.sub(r"\s+", "-", text.strip())


def hob_url(pack, name):
    return f"{HOB}{hob_slug(pack)}/{hob_slug(name)}.jpg"


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


def sync(root=DEFAULT_ROOT, workers=4, encounter=False, recheck_backs=False, hob=True):
    game_dir = os.path.join(root, GAME)
    images_dir = os.path.join(game_dir, "images")
    os.makedirs(images_dir, exist_ok=True)
    index = load_index(root, GAME) or {}
    old_printings = index.get("printings", {})
    hob_checked = set(index.get("hob_checked", []))

    def improve(stem, front, pack, name):
        """Hall of Beorn pass, once per image file."""
        if not hob or stem in hob_checked:
            return front
        hob_checked.add(stem)
        if (face(images_dir, "A", front)["width"] or 0) >= HOB_TRY_BELOW:
            return front
        return upgrade(images_dir, stem, front, hob_url(pack, name))

    print("Fetching RingsDB card list…")
    cards = fetch_json(f"{RINGSDB}/api/public/cards/")
    with open(os.path.join(game_dir, "ringsdb_cards.json"), "w", encoding="utf-8") as f:
        json.dump(cards, f, ensure_ascii=False)
    printings = {p["code"]: p for p in ringsdb_printings(cards)}

    def work(p):
        old = old_printings.get(p["code"], {})
        stem = p["octgnid"]
        result = {"source": old.get("source")}
        front = find_file(images_dir, stem)
        if not front:
            urls = ([RINGSDB + p["imagesrc"]] if p.get("imagesrc") else []) + [f"{S3}{stem}.jpg"]
            got = download(images_dir, stem, urls)
            if got:
                front, result["source"] = got
        if front and not old.get("upgrade_checked"):
            if (face(images_dir, "A", front)["width"] or 0) < LOW_RES_WIDTH:
                front = upgrade(images_dir, stem, front, f"{S3}{stem}.jpg", min_gain=1.0)
        result["upgrade_checked"] = True
        if front:
            front = improve(stem, front, p["pack"], p["name"])
        back = find_file(images_dir, stem + ".B")
        if not back and (recheck_backs or not old.get("back_checked")):
            got = download(images_dir, stem + ".B", [f"{S3}{stem}.B.jpg"])
            back = got[0] if got else None
        result["faces"] = [face(images_dir, side, f) for side, f in (("A", front), ("B", back)) if f]
        result["back_checked"] = True
        return stem, result

    # Some printings share an OCTGN id (and so an image file); fetch each file once.
    first = {}
    for p in printings.values():
        first.setdefault(p["octgnid"], p)
    print(f"Syncing {len(printings)} player-card printings ({len(first)} images) with {workers} workers…")
    done = dict(run_parallel(work, list(first.values()), workers))
    index["printings"] = {
        code: {**{k: v for k, v in p.items() if k != "imagesrc"}, **done[p["octgnid"]], "card_back": "player"}
        for code, p in printings.items()
    }

    if encounter or "dragncards" in index:
        index["dragncards"] = sync_dragncards(images_dir, workers, improve)

    index["card_backs"] = fetch_card_backs(game_dir, CARD_BACKS)
    index["hob_checked"] = sorted(hob_checked)
    index["generated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    index["by_octgnid"] = build_octgn_lookup(index)
    save_index(root, GAME, index)

    missing = [p for p in index["printings"].values() if not p["faces"]]
    print(f"Done. {len(index['printings']) - len(missing)} player printings have images, {len(missing)} missing.")
    for p in missing[:30]:
        print(f"  missing: {p['code']} {p['name']} ({p['pack']})")


def sync_dragncards(images_dir, workers, improve):
    """All cards in the DragnCards database (encounter, quest, campaign cards), plus the
    ALeP sets from the plugin's alep branch."""
    print("Fetching DragnCards card databases (main + ALeP)…")
    urls = [DRAGNCARDS_DB] + [ALEP_RAW + t["path"] for t in fetch_json(ALEP_TREE)["tree"]
                              if t["path"].startswith("tsvs/") and t["path"].endswith(".tsv")
                              and t["path"] != "tsvs/cardDb.tsv"]
    rows = [r for url in urls
            for r in csv.DictReader(io.StringIO(fetch(url).decode("utf-8")), delimiter="\t")
            if not ALEP_SKIP.search(r["packName"] or "")]
    by_id = {}
    for r in rows:
        entry = by_id.setdefault(r["databaseId"], {
            "octgnid": r["databaseId"], "name": r["name"], "type": r["type"],
            "pack": r["packName"], "encounter_set": r["encounterSet"] or None,
            "card_back": {"multi_sided": None}.get(r["cardBack"], r["cardBack"]), "files": {},
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
            if name and side == "A":
                name = improve(stem, name, entry["pack"], entry["name"])
            if name:
                faces.append(face(images_dir, side, name))
        # Imageless Rules cards are DragnCards-only scenario summaries that were never
        # printed; no scan exists on DragnCards, Hall of Beorn or RingsDB.
        return {**entry, "faces": faces, "virtual": not faces and entry["type"] == "Rules"}

    print(f"Syncing {len(by_id)} DragnCards cards…")
    return {e["octgnid"]: e for e in run_parallel(work, list(by_id.values()), workers)}


def build_octgn_lookup(index):
    """octgnid -> {name, code, faces, card_back}, merging DragnCards cards and RingsDB
    printings (RingsDB wins: it has the higher-res ALeP images)."""
    out = {}
    for e in index.get("dragncards", {}).values():
        out[e["octgnid"]] = {"name": e["name"], "code": None, "faces": e["faces"], "card_back": e["card_back"]}
    for p in index["printings"].values():
        if p["faces"] or p["octgnid"] not in out:
            out[p["octgnid"]] = {"name": p["name"], "code": p["code"], "faces": p["faces"], "card_back": "player"}
    return out


class Store(BaseStore):
    game = GAME

    def by_code(self, code):
        p = self.index["printings"].get(code)
        return p and {**p, "faces": self.faces(p["faces"])}

    def by_octgnid(self, octgnid):
        e = self.index["by_octgnid"].get(octgnid)
        return e and {"octgnid": octgnid, **e, "faces": self.faces(e["faces"])}

    def resolve_deck(self, source):
        """All entries of all decks behind `source` (see load)."""
        return [e for deck in self.load(source) for e in deck["entries"]]

    def load(self, source):
        """source: RingsDB decklist/deck/fellowship URL, numeric decklist id, or path to an
        .o8d file. Returns a list of {name, url, entries} (fellowships hold several decks)."""
        if os.path.exists(source):
            return [self._from_o8d(source)]
        if "/fellowship/view/" in source:
            # Fellowship pages have no API; their "Play on DragnCards" link lists the decks.
            page = (fetch(source) or b"").decode("utf-8", "replace")
            m = re.search(r"external/ringsdb/([^\"']+)", page)
            pairs = re.findall(r"(decklist|deck)/(\d+)", m.group(1)) if m else []
            if not pairs:
                raise ValueError(f"No decks found in fellowship {source} (is it public?)")
            return [self._from_ringsdb(kind, deck_id) for kind, deck_id in pairs]
        m = re.search(r"/(decklist|deck)/view/(\d+)", source)
        kind, deck_id = (m.group(1), m.group(2)) if m else ("decklist", source.strip())
        if not deck_id.isdigit():
            raise ValueError(f"Not a RingsDB deck url, id or existing file: {source}")
        return [self._from_ringsdb(kind, deck_id)]

    def _from_ringsdb(self, kind, deck_id):
        deck = fetch_json(f"{RINGSDB}/api/public/{kind}/{deck_id}")
        if deck is None:
            raise ValueError(f"RingsDB {kind} {deck_id} not found (private decks must be shared)")
        heroes = deck.get("heroes") or {}
        entries = []
        for section, slots in (("Main", deck.get("slots") or {}), ("Sideboard", deck.get("sideslots") or {})):
            for code, qty in slots.items():
                card = self.by_code(code) or {}
                sec = "Hero" if section == "Main" and code in heroes else section
                entries.append({**self.entry(sec, qty, card, code), "octgnid": card.get("octgnid")})
        order = {"Hero": 0, "Main": 1, "Sideboard": 2}
        entries.sort(key=lambda e: (order[e["section"]], e["code"]))
        return {"name": deck.get("name") or f"RingsDB {deck_id}",
                "url": f"{RINGSDB}/{kind}/view/{deck_id}", "entries": entries}

    def _from_o8d(self, path):
        entries = []
        for section in ET.parse(path).getroot().iter("section"):
            for card in section.iter("card"):
                octgnid = card.get("id")
                found = self.by_octgnid(octgnid) or {"name": (card.text or "").strip()}
                entries.append({**self.entry(section.get("name"), int(card.get("qty", 1)), found),
                                "octgnid": octgnid})
        name = os.path.splitext(os.path.basename(path))[0]
        return {"name": name, "url": None, "entries": entries}

    def status(self):
        index = self.index
        p = list(index["printings"].values())
        print(f"Generated: {index['generated']}")
        print(f"Player printings: {sum(1 for x in p if x['faces'])}/{len(p)} with image, "
              f"{sum(1 for x in p if len(x['faces']) > 1)} double-sided")
        if "dragncards" in index:
            d = index["dragncards"].values()
            missing = [e for e in d if not e["faces"] and not e.get("virtual")]
            print(f"DragnCards cards (incl. encounter): {len(d)}, "
                  f"{sum(1 for e in d if e.get('virtual'))} unprinted DragnCards rules cards, {len(missing)} missing")
            for e in missing[:30]:
                print(f"  missing: {e['name']} ({e['pack']}) {e['octgnid']}")
        widths = [f["width"] or 0 for e in index["by_octgnid"].values() for f in e["faces"][:1]]
        print(f"Front resolution: {sum(1 for w in widths if w >= 1000)} >=1000px, "
              f"{sum(1 for w in widths if 600 <= w < 1000)} 600-999px, {sum(1 for w in widths if w < 600)} <600px")
        n, size = disk_usage(self.game_dir)
        print(f"Files on disk: {n}, {size / 1e6:.0f} MB")
