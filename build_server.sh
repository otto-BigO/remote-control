#!/bin/bash
# Build the server as a single run-and-go binary.
# Run on the SAME OS you'll run the server on (Linux build needs X available so
# pynput imports during analysis). Output: dist/rc-server
set -e
cd "$(dirname "$0")"

pip3 install --user pyinstaller 2>/dev/null \
    || pip3 install --user --break-system-packages pyinstaller
export PATH="$HOME/.local/bin:$PATH"

pyinstaller --noconfirm --onefile --name rc-server server.py

echo "✓ Built: dist/rc-server"
echo "  Put an rc_config.json next to it (see rc_config.example.json), then run it."
