# Deckprint

Turn a deck from **RingsDB** (The Lord of the Rings: The Card Game) or **ArkhamDB** (Arkham
Horror: The Card Game) into a PDF of real-size cards that you can print and cut out.

- Paste a deck link and see every card right away. Change how many copies you want, or set 0 for
  cards you already have.
- Click **Create PDF** and the file downloads in about a second.
- Cards are printed at their real size (63 × 88 mm) with cut marks. Double-sided cards get back
  pages that line up when you print on both sides.
- Works with RingsDB decklists, shared decks and fellowships, OCTGN/DragnCards `.o8d` files, and
  ArkhamDB decks. It covers all official packs and the
  [A Long-extended Party](https://alongextendedparty.com/) (ALeP) community expansions.
- It runs on your own computer, on Mac and Windows. Nothing is uploaded anywhere.

---

## About the card images (please read)

**This project does not contain any card images.** The artwork and card designs belong to
Fantasy Flight Games / Asmodee, the artists and, for ALeP, the community creators. This repository
only contains the program.

The first time you start Deckprint, it downloads the images **to your own computer** from the
same community sites that players already use every day:

| Game | Where the images come from |
|---|---|
| LotR | [RingsDB](https://ringsdb.com), [DragnCards](https://dragncards.com), [Hall of Beorn](https://hallofbeorn.com) |
| Arkham | [arkham.build](https://arkham.build), [ArkhamDB](https://arkhamdb.com) |

Please use them the way the community intends:

- for **personal use**, for example proxies of cards you own, or play-testing,
- don't sell the printed cards,
- don't share the downloaded images or the PDFs publicly.

Deckprint downloads politely (a few files at a time) and only fetches what is new when you update.

---

## Install on a Mac

You only need to do this once.

1. **Install Python.** Go to <https://www.python.org/downloads/>, click the big yellow
   **Download Python** button and open the file you get. Click *Continue* until it is installed.
   When it is done, a Finder window opens; you can close it.
2. **Download Deckprint.** On this page, click the green **Code** button near the top, then
   **Download ZIP**. Open the downloaded file (it is usually in *Downloads*); it unpacks into a
   folder called `deckPrinter-main`. Move that folder somewhere you will find it again, for
   example *Documents*.
3. **Start Deckprint.** Open the folder and double-click **`Start Deckprint (Mac).command`**.
   - The first time, macOS will probably say it *cannot verify the developer*. Click **Done**
     (or *Cancel*), open **System Settings → Privacy & Security**, scroll down and click
     **Open Anyway** next to *"Start Deckprint (Mac).command" was blocked*. Confirm with your
     password and click **Open**. You only need to do this once.
   - A Terminal window opens. The first start takes a minute while it sets things up.
     After that Deckprint opens in your web browser.
4. **Keep the Terminal window open** while you use Deckprint. Close it when you are done.

## Install on Windows

You only need to do this once.

1. **Install Python.** Go to <https://www.python.org/downloads/>, click **Download Python** and
   run the installer. **Tick the box "Add python.exe to PATH"** at the bottom of the first screen,
   then click **Install Now**.
2. **Download Deckprint.** On this page, click the green **Code** button near the top, then
   **Download ZIP**. In *Downloads*, right-click the file, choose **Extract All…** and click
   **Extract**. Move the `deckPrinter-main` folder somewhere you will find it again, for example
   *Documents*.
3. **Start Deckprint.** Open the folder and double-click **`Start Deckprint (Windows).bat`**.
   - If Windows shows *"Windows protected your PC"*, click **More info**, then **Run anyway**.
   - If the firewall asks, you can click **Cancel**. Deckprint only talks to your own computer.
   - A black window opens. The first start takes a minute while it sets things up. After that
     Deckprint opens in your web browser.
4. **Keep the black window open** while you use Deckprint. Close it when you are done.

---

## First start: download the card images

The first time, Deckprint shows a welcome screen. Click **Download** next to the game(s) you play.

| | Player cards (enough for printing decks) | With encounter / quest / scenario cards |
|---|---|---|
| LotR | about 1 GB | about 2.3 GB |
| Arkham | about 0.5 GB | about 2.1 GB |

The first download takes roughly 10-30 minutes depending on your internet connection. If it is
interrupted, just click the button again; it continues where it stopped.

Later, click **Card images → Update** now and then to get new packs. It only downloads what is new.

## Print a deck

1. Copy the address of a deck on RingsDB or ArkhamDB, for example
   `https://ringsdb.com/decklist/view/951`, and paste it into the box at the top. The deck appears
   at once.
2. Use **−** and **+** on a card to change the number of copies. Set it to 0 to skip a card.
   *All cards / No cards / One of each* change the whole deck at once. Click a card to see it large.
3. On the right, choose your **paper** (A4 or Letter) and the **card backs**:
   - **Auto** (recommended) prints back pages only for double-sided cards, such as contracts,
     quests and investigators.
   - **All** gives every card a back.
   - **None** prints fronts only.
4. Click **Create PDF**. The file downloads, and Deckprint tells you which pages to print on
   both sides.

**Printing tips**

- Print at **100 % / "Actual size"**, never "Fit to page". Otherwise the cards come out too small.
- For double-sided pages, use your printer's two-sided setting with **"flip on long edge"**.
- Thicker paper (160-200 g/m²) or putting the printed card in a sleeve in front of a common card
  makes the proxies easy to shuffle.

You can load several decks at once, for example a whole fellowship. Each deck starts on its own
page, so the cards don't get mixed up.

---

## Updating Deckprint

Download the ZIP again as in step 2 and unpack it. Before you start the new version, **move the
`lotr` and `arkham` folders from your old Deckprint folder into the new one**. Those folders hold
the card images, so you don't have to download them again. Then delete the old folder.

## Troubleshooting

- **"Python 3 is not installed"** means step 1 of the install is missing. On Windows, run the
  Python installer again, choose *Modify*, and make sure *Add Python to environment variables* is
  ticked.
- **The browser says it can't connect** means the Terminal/black window was closed. Start Deckprint
  again.
- **"Deck not found"** usually means the deck is private. On RingsDB/ArkhamDB the deck must be
  published or shared (*"Share your deck"* in the deck settings).
- **"This deck expired"** means Deckprint was restarted. Remove the deck (✕) and paste the link again.
- **A card shows "No image"** means no community site has a scan of it. Deckprint skips it when printing.
- **A card is marked "low res"** means only a small scan exists. It prints, but looks softer.

---

## For developers

Everything is plain Python 3.9+ with three dependencies (`flask`, `fpdf2`, `pillow`).

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m webapp.server                         # web app on http://127.0.0.1:8790

# Card images from the command line
python3 -m cardimages lotr sync [--encounter]               # RingsDB + DragnCards (+ALeP) + Hall of Beorn
python3 -m cardimages arkham sync [--encounter]             # arkham.build + ArkhamDB
python3 -m cardimages lotr deck https://ringsdb.com/decklist/view/951 [--json]
python3 -m cardimages lotr status

# PDF from the command line
.venv/bin/python deckprint.py lotr https://ringsdb.com/decklist/view/951 -o deck.pdf
.venv/bin/python deckprint.py arkham 1 --backs all --paper letter
```

```python
from cardimages import open_store
for e in open_store("arkham").resolve_deck("https://arkhamdb.com/decklist/view/1"):
    e["section"], e["qty"], e["faces"], e["card_back"]
```

**Layout**

```
cardimages/   image sync + card index (common.py, lotr.py, arkham.py)
deckprint.py  PDF layout (real-size cards, rotation of landscape cards, duplex back pages)
webapp/       Flask server + static page
lotr/ arkham/ downloaded images and index.json - created on first sync, git-ignored
```

**How cards are identified**

- **LotR:** the OCTGN id (GUID), the same id used by RingsDB, DragnCards and `.o8d` files. Every
  printing of a card has its own id, and RingsDB decklists can reference any printing.
- **Arkham:** the ArkhamDB card code. Back sides are `<code>b`. Flip cards with their own code use
  `linked_card`. Reprints without their own scan reuse the original's image.

Each deck entry has `faces`: `faces[0]` is the front, followed by printed backs (B, C… for
multi-sided quests). Each face has `width`, `height`, `orientation` (portrait/landscape) and `size`
(standard 63×88 mm, mini 41×63 mm).

**Sources and quality**

- **LotR player cards** come from RingsDB (ALeP at 750×1050), with DragnCards as fallback.
- **LotR encounter and ALeP scenario cards** come from the DragnCards plugin repository, from both
  the `main` and `alep` branches.
- **Hall of Beorn** is then checked for every LotR scan under 700 px wide. About a quarter of cards
  exist there at up to 1466×2093.
- **Arkham** comes from arkham.build (~750×1050), with ArkhamDB as fallback.

**Known gaps**

- 8 LotR "Rules" cards are DragnCards-only scenario summaries that were never printed.
- Arkham mini investigator cards have no scans anywhere.

---

Deckprint is an unofficial fan project. It is not produced, endorsed or supported by Fantasy
Flight Games or Asmodee. The Lord of the Rings: The Card Game and Arkham Horror: The Card Game
are trademarks of their respective owners.
