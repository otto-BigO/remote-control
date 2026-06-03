# Remote Control

A LAN remote-desktop client for macOS, written in Python and Tkinter. It connects
to a companion `server.py` running on the Mac you want to control and mirrors that
machine's screen, mouse, and keyboard.

## Files

- `client.py` — the GUI client; run it on the controlling machine.
- `launch_client.sh` — starts the client with the bundled Python path.
- `server.py` — runs on the machine being controlled (e.g. a Mac Mini).

## Server

Run on the machine you want to control:

```bash
pip3 install pynput mss Pillow
python3 server.py --password secret
```

Flags: `--host` (default `0.0.0.0`), `--port` (default `5901`), `--password`.
On macOS, grant the running terminal Accessibility and Screen Recording
permissions in System Settings → Privacy & Security.

## Client

```bash
pip3 install Pillow
./launch_client.sh   # or: python3 client.py
```

Enter the server's IP, port (default `5901`), and password, then click **Connect**.
**Scan LAN** finds a running server by UDP broadcast.

`launch_client.sh` points at Homebrew's `/opt/homebrew/bin/python3.13`; edit it if
your Python lives elsewhere.

## Modes

- **Remote** — a live screen preview you click, scroll, and type into.
- **Home** — a small floating bar. **Grab Input** mirrors your mouse and keyboard
  to the other Mac through a transparent overlay; press `Esc` to release.

## Features

- Adaptive frame rate with delta-frame updates.
- Multi-monitor switching.
- Zoom (`Ctrl`+scroll) and pan (middle-drag).
- Full-screen preview (double-click).
- Clipboard push, pull, and auto-sync.
- File transfer to the remote machine.
- Saved connection profiles.

## Shortcuts

- `⌘K` — connect / disconnect
- `⌘L` — scan the LAN
- Double-click the preview — full screen
- `Esc` — release input / exit full screen

## Protocol

Length-prefixed JSON over TCP (default port `5901`), with SHA-256
challenge-response authentication. UDP broadcast on port `5902` for discovery.
