"""Arkham Horror LCG: images keyed by ArkhamDB card code.

Sources:
  arkham.build   assets.arkham.build/optimized/<code>[b].jpg   ~750x1050, incl. newest packs
  ArkhamDB       arkhamdb.com/bundles/cards/<code>[b].png      ~300x420 fallback
Reprints without their own scan (duplicate_of_code) reuse the original's file.

Card shapes: investigators have a landscape front and portrait back, acts/agendas are
landscape; the face model records this per side. Mini investigator cards have no scans
anywhere, so `size` is always "standard" here.

Layout: arkham/images/<code>.jpg, <code>b.jpg, arkham/backs/{player,encounter}.jpg,
        arkham/index.json, arkham/arkhamdb_cards.json
"""
import json
import os
import re
from datetime import datetime, timezone

from .common import (BaseStore, DEFAULT_ROOT, disk_usage, download, face, fetch_card_backs,
                     fetch_json, find_file, load_index, run_parallel, save_index)

GAME = "arkham"
ARKHAMDB = "https://arkhamdb.com"
ARKHAM_BUILD = "https://assets.arkham.build"
CARD_BACKS = {"player": f"{ARKHAM_BUILD}/back_player.jpg",
              "encounter": f"{ARKHAM_BUILD}/back_encounter.jpg"}


def back_kind(card):
    """Same rule as arkham.build: printed back for double-sided cards, otherwise the
    encounter back for mythos/scenario cards and the player back for the rest."""
    if card.get("double_sided"):
        return None
    if card.get("faction_code") == "mythos" or (card.get("encounter_code") and not card.get("deck_limit")):
        return "encounter"
    return "player"


def sync(root=DEFAULT_ROOT, workers=4, encounter=False, **_):
    """Player cards only by default (~1,800 cards); encounter=True adds every scenario card.
    Once encounter cards are in the index, later syncs keep including them."""
    game_dir = os.path.join(root, GAME)
    images_dir = os.path.join(game_dir, "images")
    os.makedirs(images_dir, exist_ok=True)
    previous = load_index(root, GAME) or {}
    old = previous.get("cards", {})
    encounter = encounter or previous.get("encounter", False)

    print(f"Fetching ArkhamDB card list{' (incl. encounter cards)' if encounter else ''}…")
    cards = fetch_json(f"{ARKHAMDB}/api/public/cards/" + ("?encounter=1" if encounter else ""))
    with open(os.path.join(game_dir, "arkhamdb_cards.json"), "w", encoding="utf-8") as f:
        json.dump(cards, f, ensure_ascii=False)

    def work(c):
        code = c["code"]
        prev = old.get(code, {})
        front = find_file(images_dir, code)
        if not front:
            urls = [f"{ARKHAM_BUILD}/optimized/{code}.jpg"] + ([ARKHAMDB + c["imagesrc"]] if c.get("imagesrc") else [])
            front = (download(images_dir, code, urls) or [None])[0]
        back = None
        if c.get("double_sided"):
            back = find_file(images_dir, code + "b")
            if not back and not prev.get("b_checked"):
                urls = [f"{ARKHAM_BUILD}/optimized/{code}b.jpg"] + (
                    [ARKHAMDB + c["backimagesrc"]] if c.get("backimagesrc") else [])
                back = (download(images_dir, code + "b", urls) or [None])[0]
        return {
            "code": code, "name": c["name"], "subname": c.get("subname"), "type": c.get("type_code"),
            "pack": c.get("pack_name"), "faction": c.get("faction_code"),
            "encounter": c.get("encounter_name"), "hidden": bool(c.get("hidden")),
            "linked_code": (c.get("linked_card") or {}).get("code"),
            "duplicate_of": c.get("duplicate_of_code"), "card_back": back_kind(c),
            "faces": [face(images_dir, side, f) for side, f in (("A", front), ("B", back)) if f],
            "b_checked": bool(c.get("double_sided")),
        }

    print(f"Syncing {len(cards)} cards with {workers} workers…")
    by_code = {r["code"]: r for r in run_parallel(work, cards, workers)}
    for r in by_code.values():
        orig = by_code.get(r["duplicate_of"] or "")
        if not r["faces"] and orig and orig["faces"]:
            r["faces"], r["faces_from"] = orig["faces"], orig["code"]

    index = {"cards": by_code, "encounter": encounter, "card_backs": fetch_card_backs(game_dir, CARD_BACKS),
             "generated": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    save_index(root, GAME, index)
    missing = [r for r in by_code.values() if not r["faces"]]
    print(f"Done. {len(by_code) - len(missing)} cards have images, {len(missing)} missing.")
    for r in missing[:30]:
        print(f"  missing: {r['code']} {r['name']} ({r['pack']})")


class Store(BaseStore):
    game = GAME

    def by_code(self, code):
        c = self.index["cards"].get(code)
        if not c:
            return None
        faces = list(c["faces"])
        # Flip cards stored under their own code (e.g. agenda 01121a -> enemy 01121b).
        linked = self.index["cards"].get(c.get("linked_code") or "")
        if linked and linked["faces"]:
            faces.append({**linked["faces"][0], "side": "B"})
        return {**c, "faces": self.faces(faces)}

    def resolve_deck(self, source):
        return self.load(source)[0]["entries"]

    def load(self, source):
        """source: ArkhamDB decklist/deck URL or numeric decklist id. Returns [{name, url, entries}]."""
        m = re.search(r"/(decklist|deck)/view/(\d+)", source)
        kind, deck_id = (m.group(1), m.group(2)) if m else ("decklist", source.strip())
        if not deck_id.isdigit():
            raise ValueError(f"Not an ArkhamDB deck url or id: {source}")
        deck = fetch_json(f"{ARKHAMDB}/api/public/{kind}/{deck_id}")
        if deck is None:
            raise ValueError(f"ArkhamDB {kind} {deck_id} not found (private decks must be public)")
        entries = [self._investigator(deck)]
        for section, slots in (("Main", deck.get("slots") or {}), ("Sideboard", deck.get("sideSlots") or {})):
            for code, qty in sorted(slots.items()):
                entries.append(self.entry(section, qty, self.by_code(code) or {}, code))
        return [{"name": deck.get("name") or f"ArkhamDB {deck_id}",
                 "url": f"{ARKHAMDB}/{kind}/view/{deck_id}", "entries": entries}]

    def _investigator(self, deck):
        """Parallel investigators: meta.alternate_front / alternate_back swap one side."""
        meta = deck.get("meta") or {}
        if isinstance(meta, str):
            meta = json.loads(meta or "{}")
        code = deck["investigator_code"]
        card = self.by_code(code) or {}
        faces = card.get("faces", [])
        front = (self.by_code(meta.get("alternate_front") or "") or {}).get("faces", faces)[:1]
        back = [f for f in (self.by_code(meta.get("alternate_back") or "") or {}).get("faces", faces) if f["side"] == "B"]
        return self.entry("Investigator", 1, {**card, "faces": front + back}, code)

    def status(self):
        cards = list(self.index["cards"].values())
        print(f"Generated: {self.index['generated']}")
        print(f"Cards: {sum(1 for c in cards if c['faces'])}/{len(cards)} with image, "
              f"{sum(1 for c in cards if len(c['faces']) > 1)} double-sided, "
              f"{sum(1 for c in cards if c.get('linked_code'))} linked flip cards, "
              f"{sum(1 for c in cards if c.get('faces_from'))} reprints using the original's scan")
        missing = [c for c in cards if not c["faces"]]
        for c in missing[:30]:
            print(f"  missing: {c['code']} {c['name']} ({c['pack']})")
        n, size = disk_usage(self.game_dir)
        print(f"Files on disk: {n}, {size / 1e6:.0f} MB")
