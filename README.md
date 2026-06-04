# Remote Control

A LAN remote-desktop tool in Python and Tkinter. A GUI **client** connects to a
**server** on another machine and mirrors its screen, mouse, and keyboard. The
client runs on macOS; the server runs on macOS or Linux/X11.

## Requirements

- Python 3.9+ with Tkinter (bundled with the python.org and Homebrew builds).
- Client: `Pillow`.
- Server: `pynput`, `mss`, `Pillow` — plus a clipboard tool on Linux
  (`xclip`, `xsel`, or `wl-clipboard`).

## Files

| File | Purpose |
|------|---------|
| `client.py` | GUI client (run on the controlling machine) |
| `server.py` | Server (run on the machine being controlled) |
| `launch_client.sh` | Launches the client with a set Python path |
| `deploy_server.sh` | Copies `server.py` to a host and restarts it |
| `requirements-client.txt` / `requirements-server.txt` | Dependencies |

## Server

Run on the machine you want to control:

```bash
pip3 install -r requirements-server.txt
python3 server.py --password secret
```

Flags: `--host` (default `0.0.0.0`), `--port` (default `5901`), `--password`,
`--version`.

- **macOS:** grant the terminal Accessibility and Screen Recording permissions
  in System Settings → Privacy & Security.
- **Linux/X11:** `DISPLAY` must be set; install a clipboard tool for sync.

Files sent from the client land in `~/remote_control_received/`.

Deploy and restart from the client machine in one step:

```bash
./deploy_server.sh otto@192.168.0.170 --password secret
```

## Client

```bash
pip3 install -r requirements-client.txt
./launch_client.sh   # or: python3 client.py
```

Enter the server's IP, port, and password, then click **Connect** — or **Scan
LAN** to find a server by UDP broadcast. `launch_client.sh` points at
`/opt/homebrew/bin/python3.13`; edit it if your Python is elsewhere.

## Modes

- **Remote** — a live screen preview you click, scroll, and type into.
- **Home** — a floating bar. **Grab Input** mirrors your mouse and keyboard to
  the controlled machine through a transparent overlay; press `Esc` to release.

## Features

- Live screen streaming with adaptive frame rate.
- Multi-monitor enumeration and switching.
- Zoom (`Ctrl`+scroll) and pan (middle-drag); full-screen preview.
- Clipboard push, pull, and auto-sync.
- File transfer to the controlled machine.
- Saved connection profiles.

## Shortcuts

| Key | Action |
|-----|--------|
| `⌘K` | Connect / disconnect |
| `⌘L` | Scan the LAN |
| Double-click preview | Full screen |
| `Esc` | Release input / exit full screen |

## Protocol

Length-prefixed JSON over TCP (default port `5901`) with SHA-256
challenge-response auth. UDP broadcast on port `5902` for discovery.

## Security

The server grants full mouse, keyboard, and screen access to anyone who
connects with the password. Run it on trusted LANs only, set a strong
`--password`, and don't expose port `5901` to the internet.

## License

MIT — see [LICENSE](LICENSE).
