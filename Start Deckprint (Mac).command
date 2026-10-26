#!/bin/bash
# Double-click in Finder to start Deckprint. The first run sets things up (needs internet).
cd "$(dirname "$0")" || exit 1

fail() {
  echo
  echo "$1"
  echo
  read -r -p "Press Enter to close this window."
  exit 1
}

# Python 3.9+ (from python.org). /usr/bin/python3 may only be a stub that asks to install tools.
PY=""
for candidate in python3 /usr/local/bin/python3 /opt/homebrew/bin/python3; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1; then
    PY="$candidate"; break
  fi
done
[ -n "$PY" ] || fail "Python 3 is not installed. Install it from https://www.python.org/downloads/ and then double-click this file again."

if [ ! -x .venv/bin/python ]; then
  echo "First start: setting up Deckprint (takes a minute)..."
  "$PY" -m venv .venv || fail "Could not set up Deckprint (python -m venv failed)."
fi
if ! cmp -s requirements.txt .venv/.installed 2>/dev/null; then
  echo "Installing the libraries Deckprint needs..."
  .venv/bin/python -m pip install --quiet --disable-pip-version-check -r requirements.txt \
    || fail "Could not install the libraries Deckprint needs. Check your internet connection and try again."
  cp requirements.txt .venv/.installed
fi

.venv/bin/python -m webapp.server
code=$?
# 0 = normal exit, 130/143 = stopped with Ctrl+C or by closing the window.
case $code in 0|130|143) ;; *) fail "Deckprint stopped with an error (see above)." ;; esac
