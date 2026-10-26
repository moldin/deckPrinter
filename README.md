# cardimages

Private local mirror of card scans for **LotR LCG** and **Arkham Horror LCG**, plus a deck
printer that turns RingsDB / ArkhamDB decks into cut-ready PDFs. The scans are community
work (FFG, ALeP, DragnCards, Hall of Beorn, arkham.build). Keep them private and don't redistribute them.

## Setup

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt   # only needed for deckprint.py
python3 -m cardimages lotr sync --encounter    # ~5,000 LotR player + encounter cards incl. ALeP
python3 -m cardimages arkham sync              # ~6,000 Arkham cards incl. encounter cards
```

Re-run `sync` whenever new packs appear. It only downloads what is missing.

## Use

```bash
python3 -m cardimages lotr deck https://ringsdb.com/decklist/view/951   # list cards + image status
python3 -m cardimages lotr deck mydeck.o8d --json                        # machine-readable
python3 -m cardimages arkham deck https://arkhamdb.com/decklist/view/1
python3 -m cardimages lotr status

.venv/bin/python deckprint.py lotr https://ringsdb.com/decklist/view/951 -o deck.pdf
.venv/bin/python deckprint.py arkham 1 --backs all --paper letter
```

From Python:

```python
from cardimages import open_store
for e in open_store("arkham").resolve_deck("https://arkhamdb.com/decklist/view/1"):
    e["section"], e["qty"], e["faces"], e["card_back"]
```

Each deck entry has `faces`: `faces[0]` is the front, then printed backs (B, C… for
multi-sided quests). Each face has `path`, `width`, `height`, `orientation`
(portrait/landscape) and `size` (standard 63×88 mm, mini 41×63 mm). `card_back` is the generic
player/encounter back for single-faced cards.

## Sources and keys

| Game | Key | Primary | Fallback / upgrade |
|---|---|---|---|
| LotR player cards | OCTGN id | RingsDB (ALeP 750×1050) | DragnCards S3; Hall of Beorn when ≥1.2× wider (up to 1466×2093) |
| LotR encounter, quest, campaign, ALeP | OCTGN id | DragnCards S3 (`main` + `alep` branch TSVs) | Hall of Beorn |
| Arkham (all) | ArkhamDB code | arkham.build (~750×1050) | ArkhamDB; reprints reuse the original scan |

RingsDB decklists can reference any printing's code (e.g. `144003`). The index maps every
printing, not just the canonical card. LotR o8d files use OCTGN ids directly.

Known gaps: 8 LotR "Rules" cards (#999) are DragnCards-only summaries that were never printed
(`virtual: true`). Mini investigator cards for Arkham have no scans anywhere.

## Layout

```
lotr/   images/<octgnid>.jpg|png, <octgnid>.B.jpg   backs/   index.json   ringsdb_cards.json
arkham/ images/<code>.jpg, <code>b.jpg              backs/   index.json   arkhamdb_cards.json
```

`lotr/` and `arkham/` (~4 GB) are git-ignored. Back them up separately.
