"""Local web UI for deckprint: paste RingsDB / ArkhamDB links, tweak, download a PDF.

  .venv/bin/python -m webapp.server            # opens http://127.0.0.1:8790
"""
import argparse
import collections
import logging
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import webbrowser

import flask.cli
from flask import Flask, abort, jsonify, request, send_file, send_from_directory
from PIL import Image
from werkzeug.exceptions import HTTPException

import deckprint
from cardimages import GAMES, open_store
from cardimages.common import DEFAULT_ROOT, disk_usage

HERE = os.path.dirname(os.path.abspath(__file__))
GAME_LABEL = {"lotr": "LotR", "arkham": "Arkham"}
THUMBS = os.path.join(DEFAULT_ROOT, ".cache", "thumbs")
THUMB_PX = 260

app = Flask(__name__, static_folder=os.path.join(HERE, "static"), static_url_path="/static")
stores = {}             # game -> Store, loaded once at startup (indexes are several MB)
decks = {}              # deck id -> {"game", "deck"}; what /api/pdf prints from
decks_lock = threading.Lock()


def load_store(game):
    try:
        stores[game] = open_store(game)
    except SystemExit:
        stores.pop(game, None)
        print(f"  {GAME_LABEL[game]}: no card images yet - download them from the web page")


class Sync:
    """One image download at a time, run as `python -m cardimages <game> sync` in a child
    process so a crash or Ctrl-C there never takes the web server down. The page polls
    /api/sync for progress."""

    def __init__(self):
        self.lock = threading.Lock()
        self.proc = None
        self.game = None
        self.lines = collections.deque(maxlen=200)
        self.returncode = None

    def start(self, game, encounter):
        with self.lock:
            if self.proc and self.proc.poll() is None:
                abort(409, f"{GAME_LABEL[self.game]} images are already downloading")
            cmd = [sys.executable, "-u", "-m", "cardimages", game, "sync"] + (["--encounter"] if encounter else [])
            # UTF-8 pipe even on Windows, where the default code page can't encode some card names.
            env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
            self.proc = subprocess.Popen(cmd, cwd=DEFAULT_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                         text=True, encoding="utf-8", errors="replace", env=env)
            self.game, self.returncode = game, None
            self.lines.clear()
        threading.Thread(target=self._pump, args=(self.proc, game), daemon=True).start()

    def _pump(self, proc, game):
        for line in proc.stdout:
            self.lines.append(line.rstrip())
        self.returncode = proc.wait()
        load_store(game)

    def state(self):
        running = bool(self.proc and self.proc.poll() is None)
        done = total = None
        stage = None
        for line in reversed(self.lines):
            m = re.match(r"\s+(\d+)/(\d+)$", line)
            if m and done is None:
                done, total = int(m.group(1)), int(m.group(2))
            elif not m and line.strip() and stage is None:
                stage = line.strip()
            if done is not None and stage:
                break
        return {"running": running, "game": self.game, "returncode": self.returncode,
                "stage": friendly_stage(stage), "done": done, "total": total, "log": list(self.lines)[-8:]}


def friendly_stage(line):
    """The sync CLI prints developer-oriented lines; the page shows plain words."""
    if not line:
        return None
    if line.startswith("Fetching"):
        return "Getting the list of cards…"
    if line.startswith("Syncing"):
        kind = "encounter and scenario" if "DragnCards" in line else "card"
        return f"Downloading {kind} images…"
    return line


sync = Sync()


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
    for game in GAMES:
        store = stores.get(game)
        if not store:
            out[game] = None
            continue
        idx = store.index
        cards = idx.get("by_octgnid") or idx.get("cards") or {}
        files, size = disk_usage(store.game_dir)
        out[game] = {"generated": idx.get("generated"), "cards": len(cards), "size_mb": round(size / 1e6),
                     "encounter": bool(idx.get("encounter") or idx.get("dragncards"))}
    return jsonify({"games": out, "sync": sync.state()})


@app.get("/api/sync")
def sync_state():
    return jsonify(sync.state())


@app.post("/api/sync")
def sync_start():
    body = request.get_json(force=True)
    game = body.get("game")
    if game not in GAMES:
        abort(400, "Unknown game")
    sync.start(game, bool(body.get("encounter")))
    return jsonify(sync.state())


@app.post("/api/resolve")
def resolve():
    body = request.get_json(force=True)
    fallback = body.get("game") or "lotr"
    sources = [s.strip() for s in re.split(r"[\s,]+", body.get("sources", "")) if s.strip()]
    result, errors = [], []
    for src in sources:
        game = detect_game(src, fallback)
        if game not in stores:
            errors.append(f"{src}: no {GAME_LABEL[game]} card images yet - download them first (Card images ▸ Download)")
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
    if "lotr" not in stores:
        abort(409, "No LotR card images yet - download them first (Card images ▸ Download)")
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
            abort(410, "This deck expired because Deckprint was restarted - remove it and paste the link again")
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
        abort(400, "No cards selected")
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
    for game in GAMES:
        load_store(game)
    url = f"http://127.0.0.1:{args.port}"
    print(f"\nDeckprint is running at {url}")
    print("Keep this window open while you use it. Close it (or press Ctrl+C) to stop Deckprint.\n")
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    # Keep the console readable for non-technical users: no "development server" banner or
    # per-request log lines (this server only ever listens on 127.0.0.1).
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    flask.cli.show_server_banner = lambda *a, **k: None
    app.run(host="127.0.0.1", port=args.port, threaded=True)


if __name__ == "__main__":
    main()
