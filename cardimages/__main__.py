"""CLI:
  python3 -m cardimages lotr sync [--encounter] [--no-hob] [--workers 4]
  python3 -m cardimages arkham sync [--encounter]
  python3 -m cardimages <game> deck <url | id | file.o8d> [--json] [--copy-to DIR]
  python3 -m cardimages <game> status
"""
import argparse
import json
import os
import shutil
import sys

from . import GAMES, open_store
from .common import DEFAULT_ROOT


def cmd_deck(args):
    entries = open_store(args.game, args.root).resolve_deck(args.source)
    if args.json:
        json.dump(entries, sys.stdout, ensure_ascii=False, indent=1)
        print()
    else:
        for e in entries:
            sides = "".join(f["side"] for f in e["faces"]) or "MISSING IMAGE"
            land = " landscape" if any(f["orientation"] == "landscape" for f in e["faces"]) else ""
            print(f"{e['section']:<12} {e['qty']}x {e['name']:<35} {e['code'] or '':<8} {sides}{land}")
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


def main():
    ap = argparse.ArgumentParser(prog="python3 -m cardimages", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("game", choices=sorted(GAMES))
    ap.add_argument("--root", default=DEFAULT_ROOT)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sync", help="download new/missing images and rebuild the index")
    s.add_argument("--workers", type=int, default=4)
    s.add_argument("--encounter", action="store_true",
                   help="also download encounter/quest/scenario cards (remembered for later syncs)")
    s.add_argument("--recheck-backs", action="store_true", help="lotr: look for back sides again")
    s.add_argument("--no-hob", action="store_true", help="lotr: skip the Hall of Beorn upgrade pass")
    d = sub.add_parser("deck", help="resolve a deck to local image files")
    d.add_argument("source")
    d.add_argument("--json", action="store_true")
    d.add_argument("--copy-to", help="copy one image per card copy (excluding sideboard) into DIR")
    sub.add_parser("status")
    args = ap.parse_args()
    if args.cmd == "sync":
        kw = {"workers": args.workers, "encounter": args.encounter}
        if args.game == "lotr":
            kw.update(recheck_backs=args.recheck_backs, hob=not args.no_hob)
        GAMES[args.game].sync(args.root, **kw)
    elif args.cmd == "deck":
        sys.exit(cmd_deck(args))
    else:
        open_store(args.game, args.root).status()


if __name__ == "__main__":
    main()
