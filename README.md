# Remote Control

A LAN remote-desktop tool written in Python and Tkinter. A GUI **client** connects
to a **server** running on another machine and mirrors that machine's screen,
mouse, and keyboard. The client runs on macOS; the server runs on macOS or
Linux/X11.

## Files

| File | Purpose |
|------|---------|
| `client.py` | GUI client (run on the controlling machine) |
| `server.py` | Server (run on the machine being controlled) |
| `launch_client.sh` | Launches the client with a set Python path |
| `deploy_server.sh` | Copies `server.py` to a target host and restarts it |
| `requirements-client.txt` / `requirements-server.txt` | Dependencies |

## Server

Run on the machine you want to control:

```bash
pip3 install -r requirements-server.txt
python3 server.py --password secret
```

Flags: `--host` (default `0.0.0.0`), `--port` (default `5901`), `--password`,
`--version`.

- **macOS:** grant the running terminal Accessibility and Screen Recording
  permissions in System Settings → Privacy & Security.
- **Linux/X11:** a `DISPLAY` must be set; for clipboard sync install one of
  `xclip`, `xsel`, or `wl-clipboard`.

Files sent from the client are saved to `~/remote_control_received/`.

To deploy from the client machine in one step:

```bash
./deploy_server.sh otto@192.168.0.170 --password secret
```

## Client

```bash
pip3 install -r requirements-client.txt
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
