#!/bin/bash
cd "$(dirname "$0")"
# Use a Python every dependency supports. Brand-new releases (3.13+) often
# lack packages for the card reader, so prefer 3.12 or 3.11; if neither is
# installed, fetch 3.12 automatically with uv (a one-time ~30 MB download that
# lives in your home folder and leaves any other Python untouched).
PY=""
for c in python3.12 python3.11 /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 \
         /Library/Frameworks/Python.framework/Versions/3.11/bin/python3; do
  if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  if ! command -v uv >/dev/null 2>&1; then
    echo "Fetching the uv tool to get Python 3.12 (one time only)..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  fi
  echo "Getting Python 3.12 (one time only)..."
  uv python install 3.12
  PY="$(uv python find 3.12)"
fi
if [ -z "$PY" ] || ! "$PY" -c "import sys" 2>/dev/null; then
  echo "Could not set up Python 3.12 automatically. Paste the messages above to Claude."
  exit 1
fi
# a .venv built with a different Python is rebuilt
if [ -d .venv ] && ! .venv/bin/python -c "import sys; sys.exit(0 if sys.version_info[:2] in ((3,12),(3,11)) else 1)" 2>/dev/null; then
  echo "Rebuilding the environment with $($PY --version)..."
  rm -rf .venv
fi
if [ ! -d .venv ]; then
  echo "First run: setting up with $($PY --version), this takes a few minutes..."
  "$PY" -m venv .venv
  .venv/bin/python -m pip install -q --upgrade pip
  .venv/bin/python -m pip install -q -r requirements.txt || { echo "Installing the core packages failed; paste the messages above to Claude."; exit 1; }
  # the card reader is optional: without it, identify by name instead of number
  .venv/bin/python -m pip install -q -r requirements-ocr.txt || echo "Note: the card number reader did not install; Identify will search by name only."
  # the card reader pulls in full opencv-python, whose bundled Qt clashes with
  # PySide6 (the "cocoa" plugin error); keep only the headless build
  .venv/bin/python -m pip uninstall -y -q opencv-python opencv-contrib-python 2>/dev/null || true
  .venv/bin/python -m pip install -q --force-reinstall --no-deps opencv-python-headless
fi
exec .venv/bin/python app.py "$@"
