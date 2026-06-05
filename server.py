#!/usr/bin/env python3
"""
Remote Control Server. Run this on the machine you want to control.

Works on macOS and Linux/X11.

Features:
  • Mouse & keyboard relay (multi-monitor aware)
  • Live screen streaming with correct source resolution
  • Multi-monitor enumeration and switching
  • Bidirectional clipboard sync (manual + auto)
  • File transfer (client → this machine)
  • LAN auto-discovery (UDP broadcast)

Usage:
    python3 server.py [--host 0.0.0.0] [--port 5901] [--password secret]

Dependencies:
    pip3 install pynput mss Pillow
    Linux clipboard also needs one of: xclip, xsel, or wl-clipboard.
"""

import socket
import json
import struct
import threading
import argparse
import hashlib
import os
import sys
import io
import base64
import subprocess
import platform
import shutil
import re
import select
import tempfile
import zipfile
import urllib.request
from pathlib import Path

__version__ = "1.5.3"
GITHUB_REPO = "otto-BigO/remote-control"

try:
    from pynput import keyboard
    from pynput.mouse import Button, Controller as MouseController
    from pynput.keyboard import Key, Controller as KeyboardController
except ImportError:
    sys.exit("Missing pynput. Run: pip3 install pynput")

try:
    import mss
    from PIL import Image
except ImportError:
    sys.exit("Missing mss/Pillow. Run: pip3 install mss Pillow")

# mss.mss() is deprecated in newer releases in favour of mss.MSS()
_MSS = getattr(mss, "MSS", None) or getattr(mss, "mss")

PROTOCOL_VERSION = "2"
DISCOVERY_PORT   = 5902
TCP_PORT_DEFAULT = 5901
IS_MAC           = platform.system() == "Darwin"
IS_WIN           = platform.system() == "Windows"
MAX_MSG          = 60 * 1024 * 1024            # 60 MB frame/chunk ceiling
RECV_DIR         = Path.home() / "remote_control_received"

mouse_ctrl = MouseController()
kb_ctrl    = KeyboardController()

# ── Key / button maps ───────────────────────────────────────────────────────
# pynput's Key enum differs by platform (e.g. macOS has no Key.insert), so build
# the map from whatever the current platform actually provides.
_KEY_NAMES = [
    "alt", "alt_l", "alt_r", "backspace", "caps_lock",
    "cmd", "cmd_l", "cmd_r", "ctrl", "ctrl_l", "ctrl_r",
    "delete", "down", "end", "enter", "esc",
    "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10", "f11", "f12",
    "home", "insert", "left", "right", "up", "page_down", "page_up",
    "shift", "shift_l", "shift_r", "space", "tab",
]
SPECIAL_KEYS = {n: getattr(Key, n) for n in _KEY_NAMES if hasattr(Key, n)}
MOUSE_BUTTONS = {"left": Button.left, "right": Button.right, "middle": Button.middle}


# ── Framing protocol (4-byte length prefix) ─────────────────────────────────

def send_msg(sock, obj):
    data = json.dumps(obj).encode()
    sock.sendall(struct.pack(">I", len(data)) + data)

def recv_msg(sock):
    header = _recv_exact(sock, 4)
    if header is None:
        return None
    (length,) = struct.unpack(">I", header)
    if length > MAX_MSG:
        return None
    body = _recv_exact(sock, length)
    if body is None:
        return None
    try:
        return json.loads(body)
    except ValueError:
        return None

def _recv_exact(sock, n):
    buf = bytearray()
    while len(buf) < n:
        try:
            chunk = sock.recv(n - len(buf))
        except OSError:
            return None
        if not chunk:
            return None
        buf += chunk
    return bytes(buf)


# ── Screen capture ──────────────────────────────────────────────────────────

def monitor_geometry():
    """Return selectable monitors. mss exposes index 0 as the union of all
    screens and 1..N as individual outputs; some headless X servers expose
    only index 0, so fall back to treating that as a single monitor."""
    with _MSS() as sct:
        mons = sct.monitors
    if len(mons) >= 2:
        return [dict(m, id=i) for i, m in enumerate(mons) if i >= 1]
    return [dict(mons[0], id=1)] if mons else []

def _pick_monitor(mons, monitor_id):
    if 0 < monitor_id < len(mons):
        return mons[monitor_id]
    return mons[1] if len(mons) >= 2 else mons[0]

def capture_screenshot(monitor_id, scale=0.35, quality=55):
    with _MSS() as sct:
        raw = sct.grab(_pick_monitor(sct.monitors, monitor_id))
    img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")

    ow, oh = img.width, img.height
    w = max(1, int(ow * scale))
    h = max(1, int(oh * scale))
    img = img.resize((w, h), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return {
        "type": "screenshot",
        "data": base64.b64encode(buf.getvalue()).decode(),
        "width": w, "height": h,
        "orig_width": ow, "orig_height": oh,
    }


# ── Clipboard (macOS + Linux X11/Wayland) ───────────────────────────────────

def _clip_tools():
    if IS_MAC:
        return (["pbpaste"], ["pbcopy"])
    if IS_WIN:
        return (["powershell", "-NoProfile", "-Command", "Get-Clipboard"], ["clip"])
    if shutil.which("xclip"):
        return (["xclip", "-selection", "clipboard", "-o"],
                ["xclip", "-selection", "clipboard"])
    if shutil.which("xsel"):
        return (["xsel", "--clipboard", "--output"],
                ["xsel", "--clipboard", "--input"])
    if shutil.which("wl-paste"):
        return (["wl-paste", "-n"], ["wl-copy"])
    return (None, None)

_CLIP_GET, _CLIP_SET = _clip_tools()

def clipboard_get():
    if not _CLIP_GET:
        return ""
    try:
        return subprocess.run(_CLIP_GET, capture_output=True, text=True, timeout=2).stdout
    except Exception:
        return ""

def clipboard_set(text):
    if not _CLIP_SET:
        return
    try:
        subprocess.run(_CLIP_SET, input=text.encode(), timeout=2)
    except Exception:
        pass


# ── Input ───────────────────────────────────────────────────────────────────

def resolve_key(key_str):
    lower = key_str.lower()
    if lower in SPECIAL_KEYS:
        return SPECIAL_KEYS[lower]
    if len(key_str) == 1:
        return key_str
    try:
        return keyboard.KeyCode.from_char(key_str)
    except Exception:
        return None

def handle_input(event, offset):
    """Apply a mouse/keyboard event. offset = (left, top) of the active monitor,
    so client coordinates (monitor-local) map to global screen coordinates."""
    ox, oy = offset
    t = event.get("type")
    if t == "move":
        mouse_ctrl.position = (ox + event["x"], oy + event["y"])
    elif t == "click":
        btn = MOUSE_BUTTONS.get(event.get("button", "left"), Button.left)
        mouse_ctrl.position = (ox + event["x"], oy + event["y"])
        (mouse_ctrl.press if event.get("pressed") else mouse_ctrl.release)(btn)
    elif t == "scroll":
        mouse_ctrl.position = (ox + event["x"], oy + event["y"])
        mouse_ctrl.scroll(event.get("dx", 0), event.get("dy", 0))
    elif t == "key":
        k = resolve_key(event.get("key", ""))
        if k is not None:
            (kb_ctrl.press if event.get("pressed") else kb_ctrl.release)(k)
    elif t == "type":
        kb_ctrl.type(event.get("text", ""))


# ── Client session ──────────────────────────────────────────────────────────

class Session:
    def __init__(self, conn, addr, password_hash):
        self.conn = conn
        self.tag = f"{addr[0]}:{addr[1]}"
        self.pw_hash = password_hash
        self.send_lock = threading.Lock()
        self.monitor_id = 1
        self.offset = (0, 0)
        self.files = {}                       # id -> {f, path, name}
        self.clip_stop = None                 # threading.Event when auto-sync on
        self.clip_last = None
        self.term_fd = None                   # pty master fd
        self.term_proc = None                 # shell process
        self.term_stop = None

    def send(self, obj):
        with self.send_lock:
            try:
                send_msg(self.conn, obj)
            except OSError:
                pass

    # ── monitor offset bookkeeping ──────────────────────────────────────
    def _refresh_offset(self):
        for m in monitor_geometry():
            if m["id"] == self.monitor_id:
                self.offset = (m["left"], m["top"])
                return
        self.offset = (0, 0)

    # ── clipboard auto-sync watcher ─────────────────────────────────────
    def start_clip_watch(self):
        if self.clip_stop:
            return
        self.clip_stop = threading.Event()
        self.clip_last = hash(clipboard_get())
        threading.Thread(target=self._clip_loop, daemon=True).start()

    def stop_clip_watch(self):
        if self.clip_stop:
            self.clip_stop.set()
            self.clip_stop = None

    def _clip_loop(self):
        stop = self.clip_stop
        while stop and not stop.wait(1.0):
            text = clipboard_get()
            h = hash(text)
            if text and h != self.clip_last:
                self.clip_last = h
                self.send({"type": "clipboard_auto", "text": text})

    # ── terminal (pty-backed shell) ─────────────────────────────────────
    def start_terminal(self):
        if self.term_fd is not None:
            return
        if IS_WIN:
            self.send({"type": "term_output",
                       "data": "Terminal is not supported on the Windows server yet.\r\n"})
            return
        import pty
        shell = os.environ.get("SHELL") or shutil.which("bash") or "/bin/sh"
        master, slave = pty.openpty()
        try:
            import fcntl, termios
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 32, 100, 0, 0))
        except Exception:
            pass
        env = dict(os.environ, TERM="xterm-256color")
        try:
            self.term_proc = subprocess.Popen(
                [shell, "-i"], stdin=slave, stdout=slave, stderr=slave,
                preexec_fn=os.setsid, env=env, close_fds=True,
                cwd=str(Path.home()))     # open in the home directory, like a normal terminal
        except Exception as e:
            os.close(master); os.close(slave)
            self.send({"type": "term_output", "data": f"Could not start shell: {e}\r\n"})
            return
        os.close(slave)
        self.term_fd = master
        self.term_stop = threading.Event()
        threading.Thread(target=self._term_reader, daemon=True).start()
        print(f"[>] {self.tag} opened a terminal ({shell})")

    def _term_reader(self):
        fd, stop = self.term_fd, self.term_stop
        while stop and not stop.is_set():
            try:
                r, _, _ = select.select([fd], [], [], 0.3)
                if fd in r:
                    data = os.read(fd, 65536)
                    if not data:
                        break
                    self.send({"type": "term_output", "data": data.decode(errors="replace")})
            except OSError:
                break
        self.close_terminal()

    def term_write(self, data):
        if self.term_fd is not None:
            try: os.write(self.term_fd, data.encode())
            except OSError: pass

    def term_signal(self, sig):
        if self.term_fd is not None and sig == "int":
            try: os.write(self.term_fd, b"\x03")
            except OSError: pass

    def close_terminal(self):
        if self.term_stop:
            self.term_stop.set(); self.term_stop = None
        if self.term_proc:
            try: self.term_proc.terminate()
            except Exception: pass
            self.term_proc = None
        if self.term_fd is not None:
            try: os.close(self.term_fd)
            except OSError: pass
            self.term_fd = None

    # ── cleanup ─────────────────────────────────────────────────────────
    def cleanup(self):
        self.stop_clip_watch()
        self.close_terminal()
        for info in self.files.values():
            try: info["f"].close()
            except Exception: pass
        self.files.clear()


def client_session(conn, addr, password_hash):
    s = Session(conn, addr, password_hash)
    print(f"[+] {s.tag} connected")
    try:
        # ── Handshake ──────────────────────────────────────────────────────
        s.send({"type": "hello", "version": PROTOCOL_VERSION})
        if password_hash:
            challenge = os.urandom(16).hex()
            s.send({"type": "challenge", "challenge": challenge})
            msg = recv_msg(conn)
            if not msg:
                return
            expected = hashlib.sha256((challenge + password_hash).encode()).hexdigest()
            if msg.get("response") != expected:
                s.send({"type": "auth", "status": "fail"})
                print(f"[-] {s.tag} auth failed")
                return
        s.send({"type": "auth", "status": "ok", "hostname": socket.gethostname()})
        s._refresh_offset()
        print(f"[+] {s.tag} authenticated")

        # ── Event loop ─────────────────────────────────────────────────────
        while True:
            msg = recv_msg(conn)
            if msg is None:
                break
            t = msg.get("type")

            if t in ("move", "click", "scroll", "key", "type"):
                handle_input(msg, s.offset)

            elif t == "screenshot_request":
                try:
                    s.send(capture_screenshot(
                        s.monitor_id,
                        float(msg.get("scale", 0.35)),
                        int(msg.get("quality", 55))))
                except Exception as e:
                    s.send({"type": "error", "msg": f"screenshot failed: {e}"})

            elif t == "list_monitors":
                mons = [{"id": m["id"], "name": f"Monitor {m['id']}",
                         "w": m["width"], "h": m["height"]}
                        for m in monitor_geometry()]
                s.send({"type": "monitor_list", "monitors": mons})

            elif t == "set_monitor":
                s.monitor_id = int(msg.get("id", 1))
                s._refresh_offset()
                s.send({"type": "monitor_set", "id": s.monitor_id})

            elif t == "clipboard_pull":
                s.send({"type": "clipboard", "text": clipboard_get()})

            elif t == "clipboard_push":
                text = msg.get("text", "")
                clipboard_set(text)
                s.clip_last = hash(text)          # avoid echoing it back
                s.send({"type": "ack", "for": "clipboard_push"})

            elif t == "clipboard_auto_enable":
                s.start_clip_watch()

            elif t == "clipboard_auto_disable":
                s.stop_clip_watch()

            elif t == "file_start":
                _file_start(s, msg)

            elif t == "file_chunk":
                _file_chunk(s, msg)

            elif t == "term_start":
                s.start_terminal()

            elif t == "term_input":
                s.term_write(msg.get("data", ""))

            elif t == "term_signal":
                s.term_signal(msg.get("sig", ""))

            elif t == "term_close":
                s.close_terminal()

            elif t == "ping":
                s.send({"type": "pong"})

    except (ConnectionResetError, BrokenPipeError, OSError):
        pass
    finally:
        s.cleanup()
        conn.close()
        print(f"[-] {s.tag} disconnected")


# ── File transfer ───────────────────────────────────────────────────────────

def _file_start(s, msg):
    fid = msg.get("id")
    name = os.path.basename(msg.get("name", "file")) or "file"
    try:
        RECV_DIR.mkdir(parents=True, exist_ok=True)
        path = RECV_DIR / name
        s.files[fid] = {"f": open(path, "wb"), "path": str(path), "name": name}
        s.send({"type": "file_ack", "id": fid})
        print(f"[>] {s.tag} receiving '{name}' ({msg.get('size','?')} bytes)")
    except Exception as e:
        s.send({"type": "error", "msg": f"file_start failed: {e}"})

def _file_chunk(s, msg):
    info = s.files.get(msg.get("id"))
    if not info:
        return
    try:
        info["f"].write(base64.b64decode(msg.get("data", "")))
    except Exception as e:
        s.send({"type": "error", "msg": f"file_chunk failed: {e}"})
        try: info["f"].close()
        except Exception: pass
        s.files.pop(msg.get("id"), None)
        return
    if msg.get("final"):
        info["f"].close()
        s.send({"type": "file_done", "id": msg.get("id"),
                "name": info["name"], "path": info["path"]})
        print(f"[✓] {s.tag} saved '{info['name']}' → {info['path']}")
        s.files.pop(msg.get("id"), None)


# ── UDP discovery ───────────────────────────────────────────────────────────

def run_discovery_listener(tcp_port, stop_event):
    try:
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        udp.settimeout(1.0)
        udp.bind(("", DISCOVERY_PORT))
        print(f"[*] Discovery listener on UDP :{DISCOVERY_PORT}")
    except OSError as e:
        print(f"[!] Could not bind UDP discovery port {DISCOVERY_PORT}: {e}")
        return

    response = json.dumps({
        "type": "announce", "port": tcp_port,
        "hostname": socket.gethostname(), "version": PROTOCOL_VERSION,
    }).encode()

    while not stop_event.is_set():
        try:
            data, addr = udp.recvfrom(1024)
            if json.loads(data.decode()).get("type") == "discover":
                udp.sendto(response, addr)
        except socket.timeout:
            continue
        except Exception:
            pass
    udp.close()


# ── Self-update ─────────────────────────────────────────────────────────────

def _parse_ver(s):
    nums = re.findall(r"\d+", s or "")
    return tuple(int(n) for n in nums[:3]) if nums else (0,)

def _platform_asset():
    """(asset_name, kind) for this OS. kind: 'bin' (replace file) or 'zip' (folder)."""
    if IS_MAC:
        return "rc-server-macos-arm64.zip", "zip"
    if IS_WIN:
        return "rc-server-windows.exe", "bin"
    return "rc-server-linux-x86_64", "bin"

def _fetch_release():
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json", "User-Agent": "rc-server-update"})
    with urllib.request.urlopen(req, timeout=8) as r:
        d = json.loads(r.read().decode())
    assets = {a["name"]: a["browser_download_url"] for a in d.get("assets", [])}
    return d.get("tag_name"), assets

def _download(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": "rc-server-update"})
    with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)

def self_update():
    """Packaged builds only: if a newer release exists, download it, swap it in
    place (keeping rc_config.json), and re-exec. Never returns if it updates.
    On any problem it just returns and the server runs the current version."""
    if not getattr(sys, "frozen", False):
        return
    try:
        tag, assets = _fetch_release()
    except Exception:
        return                                    # offline / API issue: carry on
    if not tag or _parse_ver(tag) <= _parse_ver(__version__):
        return
    if os.environ.get("RC_UPDATED") == tag:
        return                                    # already tried this tag: no loops
    name, kind = _platform_asset()
    url = assets.get(name)
    if not url:
        return
    print(f"[*] Update available: {tag} (have {__version__}). Downloading…")
    try:
        tmp = Path(tempfile.mkdtemp(prefix="rcupd_"))
        blob = tmp / name
        _download(url, blob)
        exe = Path(sys.executable).resolve()
        if kind == "bin":
            backup = exe.with_name(exe.name + ".bak")
            shutil.copyfile(exe, backup)
            staged = tmp / "new"
            shutil.copyfile(blob, staged); os.chmod(staged, 0o755)
            os.replace(staged, exe)               # atomic on same filesystem
        else:  # zip → onedir folder (macOS)
            folder = exe.parent
            with zipfile.ZipFile(blob) as z:
                z.extractall(tmp / "x")
            new_folder = tmp / "x" / "rc-server"
            if not (new_folder / "rc-server").exists():
                raise RuntimeError("unexpected archive layout")
            backup = folder.with_name(folder.name + ".bak")
            if backup.exists(): shutil.rmtree(backup, ignore_errors=True)
            shutil.move(str(folder), str(backup))
            shutil.move(str(new_folder), str(folder))
            os.chmod(exe, 0o755)
        os.environ["RC_UPDATED"] = tag
        print(f"[*] Updated to {tag}. Restarting…")
        os.execv(str(exe), [str(exe)] + sys.argv[1:])
    except Exception as e:
        print(f"[!] Update failed ({e}); running current version {__version__}.")


# ── Main ────────────────────────────────────────────────────────────────────

def _local_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return "127.0.0.1"

def run_server(host, port, password):
    pw_hash = hashlib.sha256(password.encode()).hexdigest() if password else None
    stop = threading.Event()
    threading.Thread(target=run_discovery_listener, args=(port, stop), daemon=True).start()

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, port))
    srv.listen(5)

    if not _CLIP_GET:
        print("[!] No clipboard tool found (install xclip / xsel / wl-clipboard "
              "for clipboard sync).")

    print(f"[*] Remote Control Server v{__version__}  (protocol {PROTOCOL_VERSION})")
    print(f"    Listening on  : {host}:{port}")
    print(f"    Likely LAN IP : {_local_ip()}")
    print(f"    Auth          : {'enabled' if password else 'DISABLED'}")
    print(f"    Hostname      : {socket.gethostname()}")
    print(f"    Monitors      : {len(monitor_geometry())}")
    print("    Press Ctrl-C to stop.\n")

    try:
        while True:
            conn, addr = srv.accept()
            threading.Thread(target=client_session,
                             args=(conn, addr, pw_hash), daemon=True).start()
    except KeyboardInterrupt:
        print("\n[*] Stopping server.")
    finally:
        stop.set()
        srv.close()


def _app_dir():
    """Directory of the running program (works for a PyInstaller binary too)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent

def load_config(explicit=None):
    """Read rc_config.json next to the program, then ~/.rc_config.json.
    Lets a double-clicked binary start with no command-line args."""
    paths = [Path(explicit)] if explicit else [
        _app_dir() / "rc_config.json", Path.home() / ".rc_config.json"]
    for path in paths:
        try:
            if path.exists():
                return json.loads(path.read_text()), path
        except Exception as e:
            print(f"[!] Ignoring bad config {path}: {e}")
    return {}, None


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Remote Control Server")
    p.add_argument("--host",     default=None)
    p.add_argument("--port",     type=int, default=None)
    p.add_argument("--password", default=None)
    p.add_argument("--config",   default=None, help="path to an rc_config.json")
    p.add_argument("--no-update", action="store_true", help="skip the self-update check")
    p.add_argument("--version",  action="version", version=f"%(prog)s {__version__}")
    args = p.parse_args()

    # Self-update before serving (packaged builds only; re-execs if it updates).
    if not args.no_update:
        self_update()

    # Precedence: command-line flag > config file > built-in default.
    cfg, cfg_path = load_config(args.config)
    if cfg_path:
        print(f"[*] Loaded config: {cfg_path}")
    host     = args.host or cfg.get("host") or "0.0.0.0"
    port     = args.port or cfg.get("port") or TCP_PORT_DEFAULT
    password = args.password if args.password is not None else cfg.get("password")

    run_server(host, port, password)
