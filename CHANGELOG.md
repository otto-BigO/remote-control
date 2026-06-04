# Changelog

## 1.1.0

Packaged, no-install builds so the app runs with a double-click.

- **macOS client** ships as a `.app` (built with PyInstaller); no Python or pip
  needed on the machine that runs it.
- **Server** ships as a single run-and-go binary. It reads an `rc_config.json`
  placed next to it (`host` / `port` / `password`), so it starts with no
  command-line arguments — double-click and go.
- Command-line flags still win over the config file, which wins over defaults.
- Added `build_client.sh`, `build_server.sh`, and `rc_config.example.json`.

Prebuilt downloads are attached to the GitHub release.

## 1.0.0

First release-ready version. The client had gained features the server never
implemented; this brings the two sides back into sync and hardens both.

### Server — brought up to protocol parity
- Send `orig_width`/`orig_height` with every frame. The client uses these to
  map input coordinates; without them it assumed 1920×1080 and mis-placed
  clicks on any other resolution.
- Implement monitor enumeration (`list_monitors` → `monitor_list`) and
  switching (`set_monitor`), with a fallback for headless X servers that expose
  only a combined screen.
- Map input through the active monitor's offset so clicks land correctly on
  secondary monitors.
- Implement file transfer (`file_start` / `file_chunk` → `file_ack` /
  `file_done`); received files land in `~/remote_control_received/`.
- Implement clipboard auto-sync (`clipboard_auto_enable` / `_disable`), pushing
  remote clipboard changes to the client.
- Clipboard now also supports Wayland (`wl-clipboard`) and warns when no
  clipboard tool is installed.
- More reliable LAN IP detection; `--version` flag; per-session cleanup of open
  files and watcher threads on disconnect.

### Client — bug fixes
- Connect and Scan no longer block the UI thread (the blocking work used to run
  on the main thread inside `after`, freezing the window).
- Removed dead code in the disconnect handler.
- Latency (ms) shown alongside FPS.
- Window opens centered; `⌘K` connect/disconnect and `⌘L` scan shortcuts.

### UI
- Full dark theme with canvas-drawn rounded buttons that render reliably on
  macOS, hover/press states, a status dot, and a redesigned layout.

### Project
- Added LICENSE (MIT), split requirements files, this changelog, and
  `deploy_server.sh`.
