"""Local web UI for deckprint: paste RingsDB / ArkhamDB links, tweak, download a PDF.

  .venv/bin/python -m webapp.server            # opens http://127.0.0.1:8790
"""
import argparse
import os
import re
import tempfile
import threading
import time
import uuid
import webbrowser

from flask import Flask, abort, jsonify, request, send_file, send_from_directory
from PIL import Image
from werkzeug.exceptions import HTTPException

import deckprint
from cardimages import GAMES, open_store
from cardimages.common import DEFAULT_ROOT

HERE = os.path.dirname(os.path.abspath(__file__))
THUMBS = os.path.join(DEFAULT_ROOT, ".cache", "thumbs")
THUMB_PX = 260

app = Flask(__name__, static_folder=os.path.join(HERE, "static"), static_url_path="/static")
stores = {}             # game -> Store, loaded once at startup (indexes are several MB)
decks = {}              # deck id -> {"game", "deck"}; what /api/pdf prints from
decks_lock = threading.Lock()


def load_stores():
    for game in GAMES:
        try:
            stores[game] = open_store(game)
        except SystemExit as e:
            print(f"  {game}: {e}")


def detect_game(source, fallback):
    if "ringsdb.com" in source or source.lower().endswith(".o8d"):
        return "lotr"
    if "arkhamdb.com" in source:
        return "arkham"
    return fallback


def thumb_url(game, face):
    return f"/thumb/{game}/{face['file']}" if face else None


def deck_payload(game, deck):
    """What the page needs: one row per entry, keyed by position so quantities can be
    edited client-side and sent back."""
    did = uuid.uuid4().hex[:12]
    with decks_lock:
        decks[did] = {"game": game, "deck": deck}
    rows = []
    for i, e in enumerate(deck["entries"]):
        faces = e["faces"]
        rows.append({
            "key": str(i), "section": e["section"], "qty": e["qty"], "name": e["name"], "code": e["code"],
            "thumb": thumb_url(game, faces[0]) if faces else None,
            "back_thumb": thumb_url(game, faces[1]) if len(faces) > 1 else None,
            "double_sided": len(faces) > 1,
            "landscape": bool(faces) and faces[0]["orientation"] == "landscape",
            "size": faces[0].get("size", "standard") if faces else "standard",
            "low_res": bool(faces) and (faces[0]["width"] or 0) < 400,
            "missing": not faces,
        })
    return {"id": did, "game": game, "name": deck["name"], "url": deck["url"], "entries": rows}


@app.errorhandler(HTTPException)
def http_error(e):
    return jsonify({"error": e.description}), e.code


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/status")
def status():
    out = {}
    for game, store in stores.items():
        idx = store.index
        cards = idx.get("by_octgnid") or idx.get("cards") or {}
        out[game] = {"generated": idx.get("generated"), "cards": len(cards)}
    return jsonify(out)


@app.post("/api/resolve")
def resolve():
    body = request.get_json(force=True)
    fallback = body.get("game") or "lotr"
    sources = [s.strip() for s in re.split(r"[\s,]+", body.get("sources", "")) if s.strip()]
    result, errors = [], []
    for src in sources:
        game = detect_game(src, fallback)
        if game not in stores:
            errors.append(f"{src}: ingen bildsamling för {game} - kör sync först")
            continue
        try:
            for deck in stores[game].load(src):
                result.append(deck_payload(game, deck))
        except Exception as e:     # bad link, private deck, network error: show it, keep the rest
            errors.append(f"{src}: {e}")
    return jsonify({"decks": result, "errors": errors})


@app.post("/api/o8d")
def upload_o8d():
    files = request.files.getlist("file")
    result, errors = [], []
    for f in files:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, os.path.basename(f.filename or "deck.o8d"))
            f.save(path)
            try:
                result += [deck_payload("lotr", d) for d in stores["lotr"].load(path)]
            except Exception as e:
                errors.append(f"{f.filename}: {e}")
    return jsonify({"decks": result, "errors": errors})


@app.post("/api/pdf")
def make_pdf():
    body = request.get_json(force=True)
    opts = body.get("options", {})
    slots, names = [], []
    with decks_lock:
        chosen = [(decks.get(d["id"]), d.get("quantities", {})) for d in body.get("decks", [])]
    started = time.time()
    for group, (stored, quantities) in enumerate(chosen):
        if not stored:
            abort(410, "Leken har gått ut (servern startades om) - hämta den igen")
        entries = []
        for i, e in enumerate(stored["deck"]["entries"]):
            qty = int(quantities.get(str(i), e["qty"]))
            if qty > 0:
                entries.append({**e, "qty": qty})
        if entries:
            names.append(stored["deck"]["name"])
            # Quantities already reflect the sideboard choice made in the page.
            slots += deckprint.slots_for(entries, sideboard=True, backs=opts.get("backs", "auto"), group=group)[0]
    if not slots:
        abort(400, "Inga kort valda")
    pages, duplex, data = deckprint.render(
        slots, None, paper=opts.get("paper", "a4"), gap=float(opts.get("gap", 0)),
        backs=opts.get("backs", "auto"))
    filename = re.sub(r"[^\w\-+ ]+", "", " + ".join(names))[:80].strip() or "deck"
    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    tmp.write(data)
    tmp.close()
    resp = send_file(tmp.name, mimetype="application/pdf", as_attachment=True,
                     download_name=f"{filename}.pdf")
    resp.headers["X-Cards"] = str(len(slots))
    resp.headers["X-Pages"] = str(pages)
    resp.headers["X-Duplex"] = ",".join(map(str, duplex))
    resp.headers["X-Seconds"] = f"{time.time() - started:.1f}"
    resp.call_on_close(lambda: os.unlink(tmp.name))
    return resp


def image_path(game, filename):
    """Only plain file names inside the game's images directory."""
    store = stores.get(game)
    name = os.path.basename(filename)
    if not store or name != filename:
        abort(404)
    src = os.path.join(store.images_dir, name)
    if not os.path.exists(src):
        abort(404)
    return src


@app.get("/image/<game>/<path:filename>")
def image(game, filename):
    resp = send_file(image_path(game, filename))
    resp.headers["Cache-Control"] = "public, max-age=604800"
    return resp


@app.get("/thumb/<game>/<path:filename>")
def thumb(game, filename):
    src = image_path(game, filename)
    name = os.path.basename(src)
    out_dir = os.path.join(THUMBS, game)
    out = os.path.join(out_dir, name.rsplit(".", 1)[0] + ".jpg")
    if not os.path.exists(out):
        os.makedirs(out_dir, exist_ok=True)
        with Image.open(src) as img:
            img = img.convert("RGB")
            img.thumbnail((THUMB_PX, THUMB_PX))
            img.save(out + ".part", "JPEG", quality=82)
        os.replace(out + ".part", out)
    resp = send_file(out, mimetype="image/jpeg")
    resp.headers["Cache-Control"] = "public, max-age=604800"
    return resp


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()
    print("Loading card indexes…")
    load_stores()
    url = f"http://127.0.0.1:{args.port}"
    print(f"Deckprint running at {url}")
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=args.port, threaded=True)


if __name__ == "__main__":
    main()
