#!/bin/bash
# Builds CardCrop.app and installs it in /Applications. Run once on your Mac:
#   cd ~/Documents/cardcrop && ./build_mac_app.sh
# Re-run it after copying in new versions of the .py files.
set -e
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
  echo "Setting up the environment with $($PY --version) (first time only)..."
  "$PY" -m venv .venv
fi
.venv/bin/python -m pip install -q --upgrade pip
.venv/bin/python -m pip install -q -r requirements.txt || { echo "Installing the core packages failed; paste the messages above to Claude."; exit 1; }
# the card reader is optional: without it, identify by name instead of number
.venv/bin/python -m pip install -q -r requirements-ocr.txt || echo "Note: the card number reader did not install; Identify will search by name only."
# the card reader pulls in full opencv-python, whose bundled Qt clashes with
# PySide6 (the "cocoa" plugin error); keep only the headless build
.venv/bin/python -m pip uninstall -y -q opencv-python opencv-contrib-python 2>/dev/null || true
.venv/bin/python -m pip install -q --force-reinstall --no-deps opencv-python-headless
.venv/bin/python -m pip install -q pyinstaller

echo "Drawing the icon..."
.venv/bin/python make_icon.py icon_1024.png
rm -rf CardCrop.iconset && mkdir CardCrop.iconset
for sz in 16 32 128 256 512; do
  sips -z $sz $sz icon_1024.png --out CardCrop.iconset/icon_${sz}x${sz}.png >/dev/null
  sips -z $((sz*2)) $((sz*2)) icon_1024.png --out CardCrop.iconset/icon_${sz}x${sz}@2x.png >/dev/null
done
iconutil -c icns CardCrop.iconset -o CardCrop.icns

echo "Building CardCrop.app (takes a few minutes)..."
.venv/bin/pyinstaller --noconfirm --clean --windowed \
  --name CardCrop \
  --icon CardCrop.icns \
  --osx-bundle-identifier art.zack3d.cardcrop \
  --collect-all rapidocr_onnxruntime \
  --collect-all rawpy \
  --collect-all pillow_heif \
  --collect-all imageio_ffmpeg \
  --collect-all onnxruntime \
  --add-data "fonts:fonts" \
  --add-data "mobile:mobile" \
  --hidden-import identify --hidden-import listing --hidden-import engine --hidden-import tether --hidden-import ebay --hidden-import stats \
  --hidden-import card3d --hidden-import market --hidden-import grading --hidden-import calibrate --hidden-import layers --hidden-import anim --hidden-import animui --hidden-import gltf_export --hidden-import sounds --hidden-import ui_base --hidden-import ui_widgets --hidden-import ui_tasks --hidden-import ui_editor --hidden-import ui_live --hidden-import ui_dialogs --hidden-import ui_store --hidden-import ui_list --hidden-import ui_market --hidden-import ui_reports --hidden-import ui_viewer3d --hidden-import ui_motion --hidden-import ui_marks --hidden-import main_shoot --hidden-import main_queue --hidden-import main_session --hidden-import main_ebay --hidden-import main_reports --hidden-import main_export --hidden-import main_pipeline --hidden-import sales --hidden-import prices --hidden-import phone_server --hidden-import phone_link --hidden-import phone_tools --hidden-import phone_push --hidden-import scans --hidden-import centering --hidden-import ui_centering --hidden-import segno --hidden-import cryptography --hidden-import PySide6.QtOpenGL --hidden-import PySide6.QtOpenGLWidgets --hidden-import PySide6.QtSvg --hidden-import level --hidden-import shiptrack --hidden-import ui_ship --hidden-import usps_web --hidden-import PySide6.QtWebEngineCore \
  --exclude-module scipy --exclude-module matplotlib --exclude-module pandas \
  --exclude-module skimage --exclude-module imageio \
  --exclude-module tkinter --exclude-module IPython \
  --exclude-module PySide6.QtPdf \
  --exclude-module PySide6.QtMultimedia --exclude-module PySide6.Qt3DCore \
  app.py

echo "Checking the build..."
dist/CardCrop.app/Contents/MacOS/CardCrop --selftest

# camera tethering: build the bridge too when Sony's SDK is in Downloads
if ls -d "$HOME"/Downloads/CrSDK_*_Mac >/dev/null 2>&1; then
  echo "Building the camera bridge..."
  bash tether/build_tether.sh || echo "Camera bridge did not build; everything else works. Paste the messages above to Claude."
fi

echo "Installing to /Applications..."
rm -rf /Applications/CardCrop.app
cp -R dist/CardCrop.app /Applications/
echo
echo "Done. CardCrop is in your Applications folder; drag it to the Dock to keep it handy."
