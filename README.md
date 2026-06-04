# Remote Control

A LAN remote-desktop tool in Python and Tkinter. A GUI **client** connects to a
**server** on another machine and mirrors its screen, mouse, and keyboard. The
client runs on macOS; the server runs on macOS or Linux/X11.

## Download (no Python needed)

Prebuilt, double-click builds are on the
[Releases](https://github.com/otto-BigO/remote-control/releases) page.

**Client (macOS):** download `Remote-Control-macOS.zip`, unzip, and open
`Remote Control.app`. It's unsigned, so the first time, right-click → **Open**
to get past Gatekeeper.

**Server (Linux):** download `rc-server`, put an `rc_config.json` next to it
(copy `rc_config.example.json` and set a password), then:

```bash
chmod +x rc-server
./rc-server
```

It reads the config and starts — no arguments, no Python install. To run from
source instead, follow the sections below.

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
`--config`, `--version`. Instead of flags you can put an `rc_config.json` next
to the program (`host` / `port` / `password`); flags override it.

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

## Updates

On launch the client quietly checks GitHub for a newer release. If one exists it
shows the version and notes with a **Download** button; if you're current, it
says nothing.

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
