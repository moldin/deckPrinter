#!/usr/bin/env python3
"""Print a LotR (RingsDB / o8d) or Arkham (ArkhamDB) deck as a cut-ready PDF.

  .venv/bin/python deckprint.py lotr https://ringsdb.com/decklist/view/951 -o deck.pdf
  .venv/bin/python deckprint.py arkham 1 --backs all

Cards are placed edge to edge at their real size (63x88 mm, Arkham minis 41x63 mm) with
trim marks in the margin. Landscape scans (quests, acts/agendas, investigators) are rotated
to fit the portrait slot. Back pages follow each front page, mirrored for long-edge duplex:
  --backs auto   back pages only for the page(s) holding double-sided cards (default)
  --backs all    every card gets its printed back or the generic player/encounter back
  --backs none   fronts only
"""
import argparse
import os
import sys

from fpdf import FPDF
from PIL import Image

from cardimages import open_store
from cardimages.common import DEFAULT_ROOT

CARD_MM = {"standard": (63, 88), "mini": (41, 63)}
PAPER_MM = {"a4": (210, 297), "letter": (215.9, 279.4)}
MARK_MM = 4         # trim mark length
CACHE = os.path.join(DEFAULT_ROOT, ".cache", "print")


def printable(path, landscape, back=False):
    """fpdf embeds JPEG/PNG as-is (no resampling). Landscape scans are rotated into the
    portrait slot - clockwise on the front, counter-clockwise on the back, so both sides
    share the same top edge after a long-edge duplex flip. Other formats become JPEG."""
    ext = path.rsplit(".", 1)[1].lower()
    if not landscape and ext in ("jpg", "jpeg", "png"):
        return path
    os.makedirs(CACHE, exist_ok=True)
    tag = ("ccw" if back else "cw") if landscape else "flat"
    out = os.path.join(CACHE, f"{os.path.basename(path).rsplit('.', 1)[0]}.{tag}.jpg")
    if not os.path.exists(out):
        with Image.open(path) as img:
            img = img.convert("RGB")
            if landscape:
                img = img.transpose(Image.Transpose.ROTATE_90 if back else Image.Transpose.ROTATE_270)
            img.save(out, "JPEG", quality=95)
    return out


def slots_for(entries, sideboard, backs):
    """One slot per physical card copy: {size, front, back} with ready-to-embed paths."""
    slots, missing = [], []
    for e in entries:
        if e["section"] == "Sideboard" and not sideboard:
            continue
        if not e["faces"]:
            missing.append(e)
            continue
        front = e["faces"][0]
        back = None
        if len(e["faces"]) > 1:
            f = e["faces"][1]
            back = printable(f["path"], f["orientation"] == "landscape", back=True)
        elif backs == "all" and e.get("card_back"):
            back = printable(e["card_back"], False, back=True)
        slot = {"size": front.get("size") or "standard", "name": e["name"],
                "front": printable(front["path"], front["orientation"] == "landscape"), "back": back}
        slots.extend([slot] * e["qty"])
    return slots, missing


def grid(paper, card, gap, margin):
    (pw, ph), (cw, ch) = paper, card
    cols = max(1, int((pw - 2 * margin + gap) // (cw + gap)))
    rows = max(1, int((ph - 2 * margin + gap) // (ch + gap)))
    x0 = (pw - (cols * cw + (cols - 1) * gap)) / 2
    y0 = (ph - (rows * ch + (rows - 1) * gap)) / 2
    return cols, rows, x0, y0


def trim_marks(pdf, cols, rows, x0, y0, card, gap):
    """Short lines in the margin at every card edge; nothing is drawn over the cards."""
    cw, ch = card
    pdf.set_draw_color(120, 120, 120)
    pdf.set_line_width(0.2)
    xs = sorted({x0 + c * (cw + gap) + d for c in range(cols) for d in (0, cw)})
    ys = sorted({y0 + r * (ch + gap) + d for r in range(rows) for d in (0, ch)})
    for x in xs:
        pdf.line(x, ys[0] - 1 - MARK_MM, x, ys[0] - 1)
        pdf.line(x, ys[-1] + 1, x, ys[-1] + 1 + MARK_MM)
    for y in ys:
        pdf.line(xs[0] - 1 - MARK_MM, y, xs[0] - 1, y)
        pdf.line(xs[-1] + 1, y, xs[-1] + 1 + MARK_MM, y)


def render(slots, output, paper="a4", gap=0.0, margin=8.0, backs="auto"):
    paper_mm = PAPER_MM[paper]
    pdf = FPDF(unit="mm", format=paper_mm)
    pdf.set_auto_page_break(False)
    duplex = []     # 1-based page numbers that start a front/back pair
    for size in CARD_MM:
        # Double-sided cards first, so in auto mode only the leading pages need a back page.
        group = sorted((s for s in slots if s["size"] == size), key=lambda s: s["back"] is None)
        if not group:
            continue
        card = CARD_MM[size]
        cols, rows, x0, y0 = grid(paper_mm, card, gap, margin)
        per_page = cols * rows
        for start in range(0, len(group), per_page):
            page = group[start:start + per_page]
            with_back = backs == "all" or (backs == "auto" and any(s["back"] for s in page))
            if with_back:
                duplex.append(pdf.pages_count + 1)
            for side in ("front", "back") if with_back else ("front",):
                pdf.add_page()
                trim_marks(pdf, cols, rows, x0, y0, card, gap)
                for i, slot in enumerate(page):
                    if not slot[side]:
                        continue
                    row, col = divmod(i, cols)
                    if side == "back":
                        col = cols - 1 - col    # long-edge duplex mirrors left/right
                    pdf.image(slot[side], x=x0 + col * (card[0] + gap), y=y0 + row * (card[1] + gap),
                              w=card[0], h=card[1])
    pdf.output(output)
    return pdf.pages_count, duplex


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("game", choices=["lotr", "arkham"])
    ap.add_argument("source", help="deck url, decklist id, or .o8d file (lotr)")
    ap.add_argument("-o", "--output", default="deck.pdf")
    ap.add_argument("--paper", choices=sorted(PAPER_MM), default="a4")
    ap.add_argument("--gap", type=float, default=0.0, help="mm between cards (0 = shared cut lines)")
    ap.add_argument("--margin", type=float, default=8.0, help="minimum page margin in mm")
    ap.add_argument("--backs", choices=["auto", "all", "none"], default="auto")
    ap.add_argument("--sideboard", action="store_true", help="include sideboard cards")
    args = ap.parse_args()

    entries = open_store(args.game).resolve_deck(args.source)
    slots, missing = slots_for(entries, args.sideboard, args.backs)
    for e in missing:
        print(f"warning: no image for {e['qty']}x {e['name']} ({e['code']})", file=sys.stderr)
    pages, duplex = render(slots, args.output, args.paper, args.gap, args.margin, args.backs)
    print(f"{len(slots)} cards on {pages} pages -> {args.output}")
    if duplex:
        ranges = ", ".join(f"{p}-{p + 1}" for p in duplex)
        print(f"Print pages {ranges} double-sided (flip on long edge); the rest single-sided.")


if __name__ == "__main__":
    main()
