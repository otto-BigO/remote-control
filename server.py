#!/usr/bin/env python3
"""
Remote Control Server  –  run this on your Mac Mini (headless).

Features:
  • Mouse & keyboard relay
  • Live screenshot streaming
  • Bidirectional clipboard sync
  • LAN auto-discovery (UDP broadcast)

Usage:
    python3 server.py [--host 0.0.0.0] [--port 5901] [--password secret]

Install deps:
    pip3 install pynput mss Pillow
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
import time

try:
    from pynput import mouse, keyboard
    from pynput.mouse import Button, Controller as MouseController
    from pynput.keyboard import Key, Controller as KeyboardController
except ImportError:
    sys.exit("Missing pynput. Run: pip3 install pynput")

try:
    import mss
    from PIL import Image
except ImportError:
    sys.exit("Missing mss/Pillow. Run: pip3 install mss Pillow")

PROTOCOL_VERSION = "2"
DISCOVERY_PORT   = 5902
TCP_PORT_DEFAULT = 5901
IS_MAC           = platform.system() == "Darwin"

mouse_ctrl = MouseController()
kb_ctrl    = KeyboardController()

# ── Key map ────────────────────────────────────────────────────────────────
SPECIAL_KEYS = {
    "alt": Key.alt, "alt_l": Key.alt_l, "alt_r": Key.alt_r,
    "backspace": Key.backspace, "caps_lock": Key.caps_lock,
    "cmd": Key.cmd, "cmd_l": Key.cmd_l, "cmd_r": Key.cmd_r,
    "ctrl": Key.ctrl, "ctrl_l": Key.ctrl_l, "ctrl_r": Key.ctrl_r,
    "delete": Key.delete, "down": Key.down, "end": Key.end,
    "enter": Key.enter, "esc": Key.esc,
    "f1": Key.f1, "f2": Key.f2, "f3": Key.f3, "f4": Key.f4,
    "f5": Key.f5, "f6": Key.f6, "f7": Key.f7, "f8": Key.f8,
    "f9": Key.f9, "f10": Key.f10, "f11": Key.f11, "f12": Key.f12,
    "home": Key.home, "insert": Key.insert,
    "left": Key.left, "right": Key.right, "up": Key.up, "down": Key.down,
    "page_down": Key.page_down, "page_up": Key.page_up,
    "shift": Key.shift, "shift_l": Key.shift_l, "shift_r": Key.shift_r,
    "space": Key.space, "tab": Key.tab,
}
MOUSE_BUTTONS = {
    "left": Button.left, "right": Button.right, "middle": Button.middle,
}


# ── Framing protocol (4-byte length prefix) ────────────────────────────────

def send_msg(sock: socket.socket, obj: dict):
    data = json.dumps(obj).encode()
    header = struct.pack(">I", len(data))
    sock.sendall(header + data)


def recv_msg(sock: socket.socket) -> dict | None:
    """Block until a full message arrives; return None on disconnect."""
    header = _recv_exact(sock, 4)
    if header is None:
        return None
    (length,) = struct.unpack(">I", header)
    if length > 20 * 1024 * 1024:      # sanity: 20 MB cap
        return None
    body = _recv_exact(sock, length)
    if body is None:
        return None
    return json.loads(body)


def _recv_exact(sock: socket.socket, n: int) -> bytes | None:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


# ── Screenshot ─────────────────────────────────────────────────────────────

def capture_screenshot(scale: float = 0.35, quality: int = 55) -> dict:
    """Capture primary screen, return base64-encoded JPEG dict."""
    with mss.mss() as sct:
        monitor = sct.monitors[1]          # primary monitor
        raw = sct.grab(monitor)
        img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")

    w = max(1, int(img.width  * scale))
    h = max(1, int(img.height * scale))
    img = img.resize((w, h), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    b64 = base64.b64encode(buf.getvalue()).decode()

    return {"type": "screenshot", "data": b64, "width": w, "height": h}


# ── Clipboard ──────────────────────────────────────────────────────────────

def clipboard_get() -> str:
    try:
        if IS_MAC:
            return subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=2).stdout
        for cmd in [["xclip", "-selection", "clipboard", "-o"],
                    ["xsel", "--clipboard", "--output"]]:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
            if r.returncode == 0:
                return r.stdout
    except Exception:
        pass
    return ""


def clipboard_set(text: str):
    try:
        if IS_MAC:
            subprocess.run(["pbcopy"], input=text.encode(), timeout=2)
            return
        for cmd in [["xclip", "-selection", "clipboard"],
                    ["xsel", "--clipboard", "--input"]]:
            r = subprocess.run(cmd, input=text.encode(), timeout=2)
            if r.returncode == 0:
                return
    except Exception:
        pass


# ── Input events ───────────────────────────────────────────────────────────

def resolve_key(key_str: str):
    lower = key_str.lower()
    if lower in SPECIAL_KEYS:
        return SPECIAL_KEYS[lower]
    if len(key_str) == 1:
        return key_str
    try:
        return keyboard.KeyCode.from_char(key_str)
    except Exception:
        return None


def handle_input(event: dict):
    t = event.get("type")
    if t == "move":
        mouse_ctrl.position = (event["x"], event["y"])
    elif t == "click":
        btn = MOUSE_BUTTONS.get(event.get("button", "left"), Button.left)
        mouse_ctrl.position = (event["x"], event["y"])
        (mouse_ctrl.press if event.get("pressed") else mouse_ctrl.release)(btn)
    elif t == "scroll":
        mouse_ctrl.position = (event["x"], event["y"])
        mouse_ctrl.scroll(event.get("dx", 0), event.get("dy", 0))
    elif t == "key":
        k = resolve_key(event.get("key", ""))
        if k:
            (kb_ctrl.press if event.get("pressed") else kb_ctrl.release)(k)
    elif t == "type":
        kb_ctrl.type(event.get("text", ""))


# ── Client session ─────────────────────────────────────────────────────────

def client_session(conn: socket.socket, addr: tuple, password_hash: str | None):
    tag = f"{addr[0]}:{addr[1]}"
    print(f"[+] {tag} connected")
    send_lock = threading.Lock()

    def _send(obj: dict):
        with send_lock:
            try:
                send_msg(conn, obj)
            except OSError:
                pass

    try:
        # ── Handshake ──────────────────────────────────────────────────────
        _send({"type": "hello", "version": PROTOCOL_VERSION})

        if password_hash:
            challenge = os.urandom(16).hex()
            _send({"type": "challenge", "challenge": challenge})
            msg = recv_msg(conn)
            if not msg:
                return
            expected = hashlib.sha256((challenge + password_hash).encode()).hexdigest()
            if msg.get("response") != expected:
                _send({"type": "auth", "status": "fail"})
                print(f"[-] {tag} auth failed")
                return
        _send({"type": "auth", "status": "ok",
               "hostname": socket.gethostname()})
        print(f"[+] {tag} authenticated")

        # ── Event loop ─────────────────────────────────────────────────────
        while True:
            msg = recv_msg(conn)
            if msg is None:
                break

            t = msg.get("type")

            if t in ("move", "click", "scroll", "key", "type"):
                handle_input(msg)

            elif t == "screenshot_request":
                scale   = float(msg.get("scale",   0.35))
                quality = int(msg.get("quality", 55))
                try:
                    _send(capture_screenshot(scale, quality))
                except Exception as e:
                    _send({"type": "error", "msg": f"screenshot failed: {e}"})

            elif t == "clipboard_pull":
                text = clipboard_get()
                _send({"type": "clipboard", "text": text})

            elif t == "clipboard_push":
                clipboard_set(msg.get("text", ""))
                _send({"type": "ack", "for": "clipboard_push"})

            elif t == "ping":
                _send({"type": "pong"})

    except (ConnectionResetError, BrokenPipeError, OSError):
        pass
    finally:
        conn.close()
        print(f"[-] {tag} disconnected")


# ── UDP discovery ──────────────────────────────────────────────────────────

def run_discovery_listener(tcp_port: int, stop_event: threading.Event):
    """Respond to UDP broadcast discovery packets from clients."""
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
        "type":     "announce",
        "port":     tcp_port,
        "hostname": socket.gethostname(),
        "version":  PROTOCOL_VERSION,
    }).encode()

    while not stop_event.is_set():
        try:
            data, addr = udp.recvfrom(1024)
            msg = json.loads(data.decode())
            if msg.get("type") == "discover":
                udp.sendto(response, addr)
        except socket.timeout:
            continue
        except Exception:
            pass
    udp.close()


# ── Main ───────────────────────────────────────────────────────────────────

def run_server(host: str, port: int, password: str | None):
    pw_hash = hashlib.sha256(password.encode()).hexdigest() if password else None
    stop = threading.Event()

    disc = threading.Thread(target=run_discovery_listener,
                            args=(port, stop), daemon=True)
    disc.start()

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, port))
    srv.listen(5)

    local_ip = socket.gethostbyname(socket.gethostname())
    print(f"[*] Remote Control Server on {host}:{port}")
    print(f"    Likely LAN IP : {local_ip}")
    print(f"    Auth          : {'enabled' if password else 'DISABLED'}")
    print(f"    Hostname      : {socket.gethostname()}")
    print("    Press Ctrl-C to stop.\n")

    try:
        while True:
            conn, addr = srv.accept()
            t = threading.Thread(target=client_session,
                                 args=(conn, addr, pw_hash), daemon=True)
            t.start()
    except KeyboardInterrupt:
        print("\n[*] Stopping server.")
    finally:
        stop.set()
        srv.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Remote Control Server")
    p.add_argument("--host",     default="0.0.0.0")
    p.add_argument("--port",     type=int, default=TCP_PORT_DEFAULT)
    p.add_argument("--password", default=None)
    args = p.parse_args()
    run_server(args.host, args.port, args.password)
