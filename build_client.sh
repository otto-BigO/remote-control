#!/bin/bash
# Build the macOS client as a double-clickable .app. Run on macOS.
# Output: dist/Remote Control.app
set -e
cd "$(dirname "$0")"

PY="${PYTHON:-/opt/homebrew/bin/python3.13}"
"$PY" -m venv .build-venv
.build-venv/bin/pip install --quiet --upgrade pip pyinstaller pillow
.build-venv/bin/pyinstaller --noconfirm --windowed \
    --name "Remote Control" \
    --osx-bundle-identifier com.ottobigo.remotecontrol \
    client.py

echo "✓ Built: dist/Remote Control.app"
