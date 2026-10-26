#!/bin/bash
# Double-click in Finder to start Deckprint; it opens http://127.0.0.1:8790 in your browser.
cd "$(dirname "$0")"
[ -d .venv ] || { python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt; }
exec .venv/bin/python -m webapp.server
