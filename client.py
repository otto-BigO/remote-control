#!/usr/bin/env python3
"""
Remote Control Client

Modes:   Remote (full preview)  |  Home (compact relay bar)
New:     Delta frames · Multi-monitor · Zoom/pan · File transfer
         Auto-clipboard sync · Adaptive FPS · Saved profiles
         Full screen · Auto-reconnect

Install: pip3 install Pillow
"""

import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox, simpledialog, filedialog
import threading, socket, struct, json, hashlib
import io, base64, time, subprocess, platform, os, sys, uuid, re, webbrowser
import urllib.request, tempfile, zipfile
from pathlib import Path

try:
    from PIL import Image, ImageTk, ImageDraw, ImageFont
except ImportError:
    import sys; sys.exit("pip3 install Pillow")

__version__      = "1.5.1"
GITHUB_REPO      = "otto-BigO/remote-control"
UPDATE_ASSET     = "Remote-Control-macOS.zip"   # client build attached to releases
PROTOCOL_VERSION = "2"
DISCOVERY_PORT   = 5902
DEFAULT_PORT     = 5901
IS_MAC           = platform.system() == "Darwin"
PROFILES_FILE    = Path.home() / ".rc_profiles.json"
CHUNK_SIZE       = 65536          # 64 KB per file chunk

# ── Palette (dark) ──────────────────────────────────────────────────────────
BG        = "#0f1115"   # app background
SURFACE   = "#191c22"   # cards / panels / toolbars
SURFACE2  = "#21252e"   # inputs / raised elements
BORDER    = "#2b303a"
HOVER     = "#272c36"
TEXT      = "#eceef2"
TEXT2     = "#9aa1ad"
TEXT3     = "#6b7280"   # muted / disabled
BLUE      = "#0a84ff"
BLUE_H    = "#3b9bff"
RED       = "#ff453a"
GREEN     = "#30d158"
ORANGE    = "#ff9f0a"
PURPLE    = "#bf5af0"
SECONDARY = "#2a2f3a"   # neutral button fill
PILL_OK   = "#16351f"   # green-tinted status pill bg
PILL_BAD  = "#3a1714"   # red-tinted status pill bg
PILL_WARN = "#3a2a10"   # amber-tinted status pill bg
CANVAS_BG = "#0b0d10"   # preview backdrop
FONT      = "Helvetica"

# ── Framing ────────────────────────────────────────────────────────────────

def send_msg(s, obj):
    d = json.dumps(obj).encode()
    s.sendall(struct.pack(">I", len(d)) + d)

def recv_msg(s):
    h = _exact(s, 4)
    if not h: return None
    (n,) = struct.unpack(">I", h)
    if n > 50_000_000: return None
    b = _exact(s, n)
    return json.loads(b) if b else None

def _exact(s, n):
    buf = b""
    while len(buf) < n:
        try: c = s.recv(n - len(buf))
        except OSError: return None
        if not c: return None
        buf += c
    return buf

# ── LAN scan ──────────────────────────────────────────────────────────────

def scan_lan(timeout=2.5):
    out = []
    try:
        u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        u.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        u.settimeout(timeout)
        u.sendto(json.dumps({"type":"discover"}).encode(), ("<broadcast>", DISCOVERY_PORT))
        t = time.time()
        while time.time() - t < timeout:
            try:
                d, a = u.recvfrom(1024)
                info = json.loads(d)
                if info.get("type") == "announce":
                    info["ip"] = a[0]; out.append(info)
            except socket.timeout: break
    except: pass
    finally:
        try: u.close()
        except: pass
    return out

# ── Update check ───────────────────────────────────────────────────────────

def _parse_ver(s):
    nums = re.findall(r"\d+", s or "")
    return tuple(int(n) for n in nums[:3]) if nums else (0,)

def fetch_latest_release(timeout=6):
    """Return (tag, html_url, body, assets) for the newest release, or None.
    `assets` maps asset name → download URL."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "RemoteControl-UpdateCheck",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read().decode())
        assets = {a["name"]: a["browser_download_url"] for a in d.get("assets", [])}
        return d.get("tag_name"), d.get("html_url"), (d.get("body") or ""), assets
    except Exception:
        return None

def _download(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": "RemoteControl-Update"})
    with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
        while True:
            chunk = r.read(65536)
            if not chunk: break
            f.write(chunk)

# ── Clipboard ─────────────────────────────────────────────────────────────

def clip_get():
    try:
        if IS_MAC: return subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=2).stdout
        for c in [["xclip","-selection","clipboard","-o"],["xsel","--clipboard","--output"]]:
            r = subprocess.run(c, capture_output=True, text=True, timeout=2)
            if r.returncode == 0: return r.stdout
    except: pass
    return ""

def clip_set(text):
    try:
        if IS_MAC: subprocess.run(["pbcopy"], input=text.encode(), timeout=2); return
        for c in [["xclip","-selection","clipboard"],["xsel","--clipboard","--input"]]:
            if subprocess.run(c, input=text.encode(), timeout=2).returncode == 0: return
    except: pass

# ── Profiles ───────────────────────────────────────────────────────────────

def load_profiles():
    try:
        if PROFILES_FILE.exists(): return json.loads(PROFILES_FILE.read_text())
    except: pass
    return {"profiles": []}

def save_profiles(data):
    try: PROFILES_FILE.write_text(json.dumps(data, indent=2))
    except: pass

# ── Key map ────────────────────────────────────────────────────────────────

TK_KEY = {
    "Return":"enter","BackSpace":"backspace","Delete":"delete","Escape":"esc",
    "Tab":"tab","space":"space","Left":"left","Right":"right","Up":"up","Down":"down",
    "Home":"home","End":"end","Prior":"page_up","Next":"page_down","Insert":"insert",
    "F1":"f1","F2":"f2","F3":"f3","F4":"f4","F5":"f5","F6":"f6",
    "F7":"f7","F8":"f8","F9":"f9","F10":"f10","F11":"f11","F12":"f12",
    "Control_L":"ctrl_l","Control_R":"ctrl_r",
    "Alt_L":"alt_l","Alt_R":"alt_r",
    "Shift_L":"shift_l","Shift_R":"shift_r",
    "Super_L":"cmd_l","Super_R":"cmd_r","Meta_L":"cmd_l","Meta_R":"cmd_r",
    "Caps_Lock":"caps_lock",
}

def ev_to_key(e):
    if e.keysym in TK_KEY: return TK_KEY[e.keysym]
    if e.char and e.char.isprintable(): return e.char
    return None

# ── Visual helpers ───────────────────────────────────────────────────────

_FONT_CACHE = {}

def load_font(size):
    if size in _FONT_CACHE: return _FONT_CACHE[size]
    f = None
    for p in ("/System/Library/Fonts/Helvetica.ttc",
              "/System/Library/Fonts/SFNS.ttf",
              "/Library/Fonts/Arial.ttf"):
        try: f = ImageFont.truetype(p, size); break
        except: pass
    if f is None: f = ImageFont.load_default()
    _FONT_CACHE[size] = f
    return f

def lighten(hexc, f=0.10):
    """Blend a #rrggbb colour toward white by fraction f (0-1)."""
    try:
        h = hexc.lstrip("#")
        r, g, b = int(h[0:2],16), int(h[2:4],16), int(h[4:6],16)
        r = int(r + (255-r)*f); g = int(g + (255-g)*f); b = int(b + (255-b)*f)
        return f"#{r:02x}{g:02x}{b:02x}"
    except: return hexc

def darken(hexc, f=0.12):
    """Blend a #rrggbb colour toward black by fraction f (0-1)."""
    try:
        h = hexc.lstrip("#")
        r, g, b = int(h[0:2],16), int(h[2:4],16), int(h[4:6],16)
        return f"#{int(r*(1-f)):02x}{int(g*(1-f)):02x}{int(b*(1-f)):02x}"
    except: return hexc

def round_rect(c, x1, y1, x2, y2, r, **kw):
    """Draw a smooth rounded rectangle on a tk.Canvas, return the item id."""
    r = max(0, min(r, (x2-x1)//2, (y2-y1)//2))
    pts = [x1+r,y1, x2-r,y1, x2,y1, x2,y1+r, x2,y2-r, x2,y2,
           x2-r,y2, x1+r,y2, x1,y2, x1,y2-r, x1,y1+r, x1,y1]
    return c.create_polygon(pts, smooth=True, **kw)

# ── Widget helpers ─────────────────────────────────────────────────────────

class RoundButton(tk.Canvas):
    """Flat, rounded, modern button drawn on a canvas (renders identically on
    every platform, unlike native tk.Button backgrounds on macOS).
    Supports .config(text=, bg=, fg=, state=, command=) like a tk.Button."""

    def __init__(self, parent, text, command=None, bg=BLUE, fg="white",
                 size=13, bold=True, radius=11, pad_x=18, pad_y=10,
                 host_bg=None, **kw):
        self._text = text; self._bg = bg; self._fg = fg; self._cmd = command
        self._state = "normal"; self._hover = False; self._press = False
        self._radius = radius; self._pad_x = pad_x; self._pad_y = pad_y
        self._font = tkfont.Font(family=FONT, size=size,
                                 weight="bold" if bold else "normal")
        try: host_bg = host_bg or parent.cget("bg")
        except Exception: host_bg = host_bg or BG
        self._measure()
        super().__init__(parent, width=self._w0, height=self._h0, bg=host_bg,
                         highlightthickness=0, bd=0, cursor="hand2", **kw)
        self.bind("<Enter>",            self._on_enter)
        self.bind("<Leave>",            self._on_leave)
        self.bind("<ButtonPress-1>",    self._on_press)
        self.bind("<ButtonRelease-1>",  self._on_release)
        self.bind("<Configure>",        lambda _e: self._render())
        self._render()

    def _measure(self):
        self._w0 = self._font.measure(self._text) + self._pad_x*2
        self._h0 = self._font.metrics("linespace") + self._pad_y*2

    def _fill(self):
        if self._state == "disabled": return SECONDARY
        c = self._bg
        if self._press: return darken(c, 0.10)
        if self._hover: return lighten(c, 0.14)
        return c

    def _render(self):
        self.delete("all")
        w = self.winfo_width()  or self._w0
        h = self.winfo_height() or self._h0
        round_rect(self, 1, 1, w-1, h-1, self._radius, fill=self._fill(), outline="")
        fg = self._fg if self._state != "disabled" else TEXT3
        self.create_text(w//2, h//2, text=self._text, fill=fg, font=self._font)

    def _on_enter(self, _):
        if self._state != "disabled": self._hover = True; self._render()
    def _on_leave(self, _):
        self._hover = self._press = False; self._render()
    def _on_press(self, _):
        if self._state != "disabled": self._press = True; self._render()
    def _on_release(self, e):
        fire = self._press and self._state != "disabled"
        self._press = False; self._render()
        if fire and self._cmd and 0 <= e.x <= self.winfo_width() and 0 <= e.y <= self.winfo_height():
            self._cmd()

    def configure(self, cnf=None, **kw):
        if cnf: kw.update(cnf)
        text_changed = False
        if "text" in kw: self._text = str(kw.pop("text")); text_changed = True
        for src in ("bg", "background"):
            if src in kw: self._bg = kw.pop(src)
        for src in ("fg", "foreground"):
            if src in kw: self._fg = kw.pop(src)
        if "state"   in kw: self._state = kw.pop("state")
        if "command" in kw: self._cmd   = kw.pop("command")
        for dead in ("activebackground", "activeforeground", "relief", "bd", "padx", "pady"):
            kw.pop(dead, None)
        if text_changed:
            self._measure(); super().configure(width=self._w0, height=self._h0)
        if kw:
            try: super().configure(**kw)
            except Exception: pass
        self._render()
    config = configure


def btn(parent, text, cmd, color=BLUE, fg="white", size=13, **kw):
    kw.pop("activebackground", None); kw.pop("activeforeground", None)
    return RoundButton(parent, text, command=cmd, bg=color, fg=fg, size=size, **kw)

def sbtn(parent, text, cmd):
    """Secondary (neutral) button."""
    return btn(parent, text, cmd, color=SECONDARY, fg=TEXT)

def lbl(parent, text, size=13, color=TEXT, bold=False, **kw):
    kw.setdefault("bg", BG)
    return tk.Label(parent, text=text, fg=color,
                    font=(FONT, size, "bold" if bold else "normal"), **kw)

def entry(parent, var, width=18, show=None):
    kw = {"show": show} if show else {}
    return tk.Entry(parent, textvariable=var, width=width,
                    bg=SURFACE2, fg=TEXT, insertbackground=BLUE,
                    font=(FONT,13), relief="flat", bd=0,
                    highlightthickness=1, highlightbackground=BORDER,
                    highlightcolor=BLUE, **kw)

def hdiv(parent): return tk.Frame(parent, bg=BORDER, height=1)
def vdiv(parent): return tk.Frame(parent, bg=BORDER, width=1)

# ── Connection ─────────────────────────────────────────────────────────────

class Conn:
    def __init__(self):
        self.sock = None; self.connected = False
        self._lock = threading.Lock(); self._h = {}
        self.hostname = ""

    def on(self, t, fn): self._h.setdefault(t, []).append(fn)

    def _fire(self, msg):
        for fn in self._h.get(msg.get("type",""), []):
            try: fn(msg)
            except Exception as e: print(f"handler [{msg.get('type')}]: {e}")

    def connect(self, host, port, pw):
        try:
            s = socket.socket(); s.settimeout(8); s.connect((host, port))
        except OSError as e: return str(e)
        try:
            m = recv_msg(s)
            if not m or m.get("version") != PROTOCOL_VERSION:
                s.close(); return "Protocol mismatch"
            m = recv_msg(s)
            if not m: s.close(); return "No handshake"
            if m.get("type") == "challenge":
                ph = hashlib.sha256(pw.encode()).hexdigest() if pw else ""
                r  = hashlib.sha256((m["challenge"]+ph).encode()).hexdigest()
                send_msg(s, {"response": r}); m = recv_msg(s)
            if not m or m.get("status") == "fail":
                s.close(); return "Wrong password"
            self.hostname = m.get("hostname", host)
        except Exception as e: s.close(); return str(e)
        s.settimeout(None); self.sock = s; self.connected = True
        threading.Thread(target=self._loop, daemon=True).start()
        return None

    def _loop(self):
        while self.connected:
            m = recv_msg(self.sock)
            if m is None:
                self.connected = False; self._fire({"type":"_disc"}); break
            self._fire(m)

    def send(self, obj):
        if not self.connected: return
        with self._lock:
            try: send_msg(self.sock, obj)
            except OSError: self.connected = False

    def close(self):
        self.connected = False
        try:
            if self.sock: self.sock.close()
        except: pass
        self.sock = None

# ══════════════════════════════════════════════════════════════════════════
# App
# ══════════════════════════════════════════════════════════════════════════

class App(tk.Tk):
    MODE_REMOTE = "remote"
    MODE_HOME   = "home"
    PW, PH      = 700, 394

    def __init__(self):
        super().__init__()
        self.title(f"Remote Control v{__version__}")
        self.configure(bg=BG); self.minsize(820, 540)
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h = 1020, 680
        self.geometry(f"{w}x{h}+{max(0,(sw-w)//2)}+{max(0,(sh-h)//3)}")

        self.conn = Conn()
        for t, fn in [
            ("frame_full",      self._on_frame_full),
            ("frame_patch",     self._on_frame_patch),
            ("screenshot",      self._on_frame_full),     # legacy compat
            ("clipboard",       self._on_clip),
            ("clipboard_auto",  self._on_clip_auto),
            ("monitor_list",    self._on_monitor_list),
            ("monitor_set",     lambda _: None),
            ("file_ack",        self._on_file_ack),
            ("file_done",       self._on_file_done),
            ("term_output",     self._on_term_output),
            ("_disc",           lambda _: self.after(0, self._on_disc)),
        ]:
            self.conn.on(t, fn)

        # Mode
        self._mode = self.MODE_REMOTE

        # Preview / delta
        self._preview_on    = True
        self._ptimer        = None
        self._pimg          = None
        self._base_frame    = None   # PIL Image: last full frame (for patch compositing)
        self._last_t        = 0.0
        self._last_activity = 0.0
        self._remote_w      = 1920
        self._remote_h      = 1080

        # Zoom / pan
        self._zoom  = 1.0
        self._pan_x = 0.5    # centre of image (0-1)
        self._pan_y = 0.5
        self._pan_drag_start = None

        # Monitors
        self._monitors     = []
        self._monitor_id   = 1

        # Clipboard auto-sync
        self._auto_clip      = False
        self._last_clip_hash = None

        # Profiles
        self._profiles_data = load_profiles()

        # Full screen
        self._fs_win    = None
        self._fs_canvas = None
        self._fs_cid    = None
        self._fs_pimg   = None
        self._fs_offset = (0, 0, self.PW, self.PH)

        # Focus
        self._focused = False

        # File transfer pending
        self._file_pending = {}   # fid → path

        # Terminal window
        self._term_win  = None
        self._term_text = None

        # Root key bindings
        self.bind("<KeyPress>",   self._key_down)
        self.bind("<KeyRelease>", self._key_up)

        # App shortcuts (ignored while mirroring input to the remote)
        for seq in ("<Command-k>", "<Control-k>"):
            self.bind(seq, self._sc_toggle_conn)
        for seq in ("<Command-l>", "<Control-l>"):
            self.bind(seq, self._sc_scan)

        self._build_remote_ui()
        self._build_home_ui()
        self._apply_mode(self.MODE_REMOTE, init=True)
        self._placeholder("Not connected")

        self.after(1500, self._check_updates_async)   # quiet GitHub update check

    # ══════════════════════════════════════════════════════════════════════
    # Mode switching
    # ══════════════════════════════════════════════════════════════════════

    def _apply_mode(self, mode, init=False):
        self._mode = mode
        if mode == self.MODE_REMOTE:
            self._home_win_hide(); self.deiconify()
            self.geometry("1020x680"); self.minsize(820,540)
            self._remote_frame.pack(fill="both", expand=True)
            self._update_mode_btns()
            if self.conn.connected and not init:
                self._preview_on = True; self._sched()
        else:
            self._preview_on = False
            if self._ptimer: self.after_cancel(self._ptimer); self._ptimer = None
            self.withdraw(); self._home_win_show()

    def _switch_mode(self, mode):
        if mode == self._mode: return
        self._apply_mode(mode)

    def _update_mode_btns(self):
        rm = self._mode == self.MODE_REMOTE
        self._btn_remote.config(bg=BLUE   if rm     else SECONDARY,
                                fg="white" if rm     else TEXT2)
        self._btn_home.config(bg=ORANGE   if not rm else SECONDARY,
                              fg="white"   if not rm else TEXT2)

    # ══════════════════════════════════════════════════════════════════════
    # Remote mode UI
    # ══════════════════════════════════════════════════════════════════════

    def _build_remote_ui(self):
        self._remote_frame = tk.Frame(self, bg=BG)

        # ── Toolbar ────────────────────────────────────────────────────────
        tb = tk.Frame(self._remote_frame, bg=SURFACE, pady=12,
                      highlightthickness=1, highlightbackground=BORDER)
        tb.pack(fill="x")
        lbl(tb, "◉", 15, color=BLUE, bg=SURFACE).pack(side="left", padx=(18,0))
        lbl(tb, "Remote Control", 17, bold=True, bg=SURFACE).pack(side="left", padx=(8,0))

        # Segmented mode control
        mf = tk.Frame(tb, bg=SURFACE2, padx=4, pady=4); mf.pack(side="left", padx=16)
        self._btn_remote = RoundButton(mf, "🖥  Remote",
            command=lambda: self._switch_mode(self.MODE_REMOTE),
            bg=BLUE, fg="white", size=12, radius=8, pad_x=14, pad_y=6, host_bg=SURFACE2)
        self._btn_remote.pack(side="left", padx=(0,4))
        self._btn_home = RoundButton(mf, "🏠  Home",
            command=lambda: self._switch_mode(self.MODE_HOME),
            bg=SECONDARY, fg=TEXT2, size=12, radius=8, pad_x=14, pad_y=6, host_bg=SURFACE2)
        self._btn_home.pack(side="left")

        # Status pill (dot + text)
        self._rpill_f = tk.Frame(tb, bg=PILL_BAD, padx=12, pady=5); self._rpill_f.pack(side="left", padx=8)
        self._rpill_l = tk.Label(self._rpill_f, text="●  Disconnected", bg=PILL_BAD, fg=RED, font=(FONT,12,"bold"))
        self._rpill_l.pack()

        # ── Connection bar ─────────────────────────────────────────────────
        cb = tk.Frame(self._remote_frame, bg=BG, pady=10); cb.pack(fill="x", padx=18)

        def _field(label_text, var, w=16, show=None):
            f = tk.Frame(cb, bg=BG); f.pack(side="left", padx=(0,12))
            lbl(f, label_text, 11, TEXT2, bg=BG).pack(anchor="w")
            entry(f, var, width=w, show=show).pack(); return f

        self.host_var = tk.StringVar()
        self.port_var = tk.StringVar(value=str(DEFAULT_PORT))
        self.pass_var = tk.StringVar()
        _field("Host / IP", self.host_var, 20)
        _field("Port", self.port_var, 6)
        _field("Password", self.pass_var, 14, show="●")

        bf = tk.Frame(cb, bg=BG); bf.pack(side="left", pady=14)
        self._rbtn_conn = btn(bf, "Connect", self._toggle_conn)
        self._rbtn_conn.pack(side="left")
        sbtn(bf, "Scan LAN", self._scan).pack(side="left", padx=(6,0))
        sbtn(bf, "💾 Save", self._save_profile).pack(side="left", padx=(6,0))

        # Profile picker
        pf = tk.Frame(cb, bg=BG); pf.pack(side="right")
        lbl(pf, "Profile", 11, TEXT2, bg=BG).pack(anchor="w")
        self._profile_var = tk.StringVar(value="Select…")
        self._profile_menu = tk.OptionMenu(pf, self._profile_var, "Select…")
        self._profile_menu.config(bg=SURFACE2, fg=TEXT, font=(FONT,12),
                                  relief="flat", bd=0, highlightthickness=1,
                                  highlightbackground=BORDER, highlightcolor=BORDER,
                                  activebackground=HOVER, activeforeground=TEXT,
                                  cursor="hand2")
        self._profile_menu["menu"].config(bg=SURFACE2, fg=TEXT, font=(FONT,12),
                                  activebackground=BLUE, activeforeground="white",
                                  bd=0, relief="flat")
        self._profile_menu.pack()
        self._refresh_profile_menu()

        hdiv(self._remote_frame).pack(fill="x")

        # ── Body ───────────────────────────────────────────────────────────
        body = tk.Frame(self._remote_frame, bg=BG); body.pack(fill="both", expand=True, padx=18, pady=12)

        # Preview pane
        pane = tk.Frame(body, bg=BG); pane.pack(side="left", fill="both", expand=True)

        # Zoom controls
        zf = tk.Frame(pane, bg=BG); zf.pack(fill="x", pady=(0,4))
        self._hint_lbl = lbl(zf, "⌘K connect  •  ⌘L scan  •  Double-click preview for full screen", 10, TEXT2, bg=BG)
        self._hint_lbl.pack(side="left")
        self._zoom_lbl = lbl(zf, "", 10, TEXT2, bg=BG); self._zoom_lbl.pack(side="right")

        # Canvas with border
        self._border_f = tk.Frame(pane, bg=BORDER, padx=1, pady=1); self._border_f.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(self._border_f, bg=CANVAS_BG, width=self.PW, height=self.PH,
                                highlightthickness=0, cursor="arrow")
        self.canvas.pack(fill="both", expand=True); self.canvas.config(takefocus=True)
        self._cid = None

        for seq, fn in [
            ("<Button-1>",        lambda e: self._mc(e,"left",True)),
            ("<ButtonRelease-1>", lambda e: self._mc(e,"left",False)),
            ("<Button-2>",        lambda e: self._ms_pan_start(e)),
            ("<ButtonRelease-2>", lambda e: self._ms_pan_end(e)),
            ("<Button-3>",        lambda e: self._mc(e,"right",True)),
            ("<ButtonRelease-3>", lambda e: self._mc(e,"right",False)),
            ("<Motion>",          self._mm),
            ("<B2-Motion>",       self._ms_pan_drag),
            ("<MouseWheel>",      self._mscroll),
            ("<Button-4>",        self._mscroll),
            ("<Button-5>",        self._mscroll),
            ("<FocusIn>",         self._focus_in),
            ("<FocusOut>",        self._focus_out),
            ("<Double-Button-1>", lambda e: self._open_fullscreen()),
        ]:
            self.canvas.bind(seq, fn)

        self._fps_lbl = lbl(pane, "", 11, TEXT2, bg=BG); self._fps_lbl.pack(anchor="w", pady=(4,0))

        # ── Sidebar (scrollable so nothing gets clipped on short windows) ───
        sb_outer = tk.Frame(body, bg=SURFACE, width=232,
                            highlightthickness=1, highlightbackground=BORDER)
        sb_outer.pack(side="right", fill="y", padx=(14,0)); sb_outer.pack_propagate(False)
        sb_canvas = tk.Canvas(sb_outer, bg=SURFACE, highlightthickness=0)
        sb_scroll = tk.Scrollbar(sb_outer, orient="vertical", command=sb_canvas.yview)
        sb_canvas.configure(yscrollcommand=sb_scroll.set)
        sb_scroll.pack(side="right", fill="y")
        sb_canvas.pack(side="left", fill="both", expand=True)
        sb = tk.Frame(sb_canvas, bg=SURFACE)
        sb_win = sb_canvas.create_window((0, 0), window=sb, anchor="nw")
        sb.bind("<Configure>", lambda e: sb_canvas.configure(scrollregion=sb_canvas.bbox("all")))
        sb_canvas.bind("<Configure>", lambda e: sb_canvas.itemconfig(sb_win, width=e.width))

        def _sb_wheel(e):
            d = 1 if getattr(e, "num", None) == 5 else -1 if getattr(e, "num", None) == 4 \
                else (-1 if e.delta > 0 else 1)
            sb_canvas.yview_scroll(d, "units")
        def _sb_bind(_):
            for s in ("<MouseWheel>", "<Button-4>", "<Button-5>"): sb_canvas.bind_all(s, _sb_wheel)
        def _sb_unbind(_):
            for s in ("<MouseWheel>", "<Button-4>", "<Button-5>"): sb_canvas.unbind_all(s)
        sb_outer.bind("<Enter>", _sb_bind); sb_outer.bind("<Leave>", _sb_unbind)

        def _sec(t):
            hdiv(sb).pack(fill="x")
            lbl(sb, t, 10, TEXT2, bold=True, bg=SURFACE).pack(anchor="w", padx=12, pady=(10,4))

        # Monitor picker
        _sec("MONITOR")
        self._monitor_frame = tk.Frame(sb, bg=SURFACE); self._monitor_frame.pack(fill="x", padx=12, pady=(0,4))
        lbl(self._monitor_frame, "Connect to see monitors", 11, TEXT2, bg=SURFACE).pack()

        # Preview
        _sec("PREVIEW")
        self._live_btn = sbtn(sb, "⏸  Pause Preview", self._toggle_live)
        self._live_btn.pack(padx=12, pady=(0,4), fill="x")

        # Zoom
        _sec("ZOOM")
        zrow = tk.Frame(sb, bg=SURFACE); zrow.pack(fill="x", padx=12, pady=(0,4))
        btn(zrow, "＋", lambda: self._set_zoom(self._zoom * 1.5), size=14).pack(side="left")
        btn(zrow, "－", lambda: self._set_zoom(self._zoom / 1.5), size=14).pack(side="left", padx=4)
        btn(zrow, "1:1", lambda: self._set_zoom(1.0), color=SECONDARY, fg=TEXT, size=12).pack(side="left")
        lbl(sb, "Ctrl+Scroll to zoom  •  Middle-drag to pan", 10, TEXT2, bg=SURFACE).pack(padx=12, anchor="w")

        # Clipboard
        _sec("CLIPBOARD")
        self._auto_clip_btn = sbtn(sb, "⟳  Auto-sync: OFF", self._toggle_auto_clip)
        self._auto_clip_btn.pack(padx=12, pady=(0,3), fill="x")
        sbtn(sb, "⬆  Push local → remote", self._push_clip).pack(padx=12, pady=(0,3), fill="x")
        sbtn(sb, "⬇  Pull remote → local", self._pull_clip).pack(padx=12, pady=(0,3), fill="x")
        self._clip_lbl = lbl(sb, "", 10, TEXT2, bg=SURFACE, wraplength=188, justify="left")
        self._clip_lbl.pack(padx=12, anchor="w")

        # File transfer
        _sec("FILE TRANSFER")
        sbtn(sb, "📁  Send file to remote", self._send_file).pack(padx=12, pady=(0,4), fill="x")
        self._file_lbl = lbl(sb, "", 10, TEXT2, bg=SURFACE, wraplength=188, justify="left")
        self._file_lbl.pack(padx=12, anchor="w")

        # Terminal
        _sec("TERMINAL")
        sbtn(sb, "🖥  Open Terminal", self._open_terminal).pack(padx=12, pady=(0,10), fill="x")

        # Status bar
        hdiv(self._remote_frame).pack(fill="x")
        sbar = tk.Frame(self._remote_frame, bg=SURFACE, pady=7); sbar.pack(fill="x")
        self._status_lbl = lbl(sbar, "Not connected", 12, TEXT2, bg=SURFACE)
        self._status_lbl.pack(side="left", padx=16)

    # ══════════════════════════════════════════════════════════════════════
    # Home mode (floating bar)
    # ══════════════════════════════════════════════════════════════════════

    def _build_home_ui(self):
        self._home = tk.Toplevel(self); self._home.withdraw()
        self._home.title("Remote Control Home"); self._home.configure(bg=SURFACE)
        self._home.resizable(False, False)
        self._home.attributes("-topmost", True)
        self._home.protocol("WM_DELETE_WINDOW", lambda: self._switch_mode(self.MODE_REMOTE))
        self._overlay = None   # transparent full-screen capture window

        outer = tk.Frame(self._home, bg=SURFACE, highlightthickness=1, highlightbackground=BORDER)
        outer.pack(fill="both", expand=True)

        # Header
        hdr = tk.Frame(outer, bg=SURFACE, pady=10, padx=14); hdr.pack(fill="x")
        lbl(hdr, "🏠", 16, bg=SURFACE).pack(side="left")
        lbl(hdr, "Home Mode", 14, bold=True, bg=SURFACE).pack(side="left", padx=(6,0))
        self._home_pill = tk.Label(hdr, text="●  Disconnected", bg=PILL_BAD, fg=RED,
                                   font=(FONT,11,"bold"), padx=10, pady=3)
        self._home_pill.pack(side="left", padx=10)
        btn(hdr, "🖥  Remote mode",
            lambda: self._switch_mode(self.MODE_REMOTE), color=SECONDARY, fg=TEXT).pack(side="right")

        hdiv(outer).pack(fill="x")

        # Connection row
        cf = tk.Frame(outer, bg=BG, pady=8, padx=14); cf.pack(fill="x")
        lbl(cf, "Host", 11, TEXT2, bg=BG).pack(side="left")
        self._home_host_lbl = lbl(cf, "…", 12, TEXT, bg=BG)
        self._home_host_lbl.pack(side="left", padx=(6,14))
        self._home_conn_btn = btn(cf, "Connect", self._toggle_conn)
        self._home_conn_btn.pack(side="left")
        sbtn(cf, "Scan LAN", self._scan).pack(side="left", padx=(6,0))

        hdiv(outer).pack(fill="x")

        # Grab Input button (full width, prominent)
        gf = tk.Frame(outer, bg=SURFACE, pady=12, padx=14); gf.pack(fill="x")
        self._home_focus_btn = btn(gf, "⌨️  Grab Input: Mirror mouse & keyboard",
                                   self._home_toggle_focus, color=GREEN, size=14)
        self._home_focus_btn.pack(fill="x")

        hdiv(outer).pack(fill="x")

        # Clipboard row
        cf2 = tk.Frame(outer, bg=SURFACE, pady=8, padx=14); cf2.pack(fill="x")
        sbtn(cf2, "⬆ Push clip", self._push_clip).pack(side="left")
        sbtn(cf2, "⬇ Pull clip", self._pull_clip).pack(side="left", padx=(6,0))
        self._home_clip_lbl = lbl(cf2, "", 11, TEXT2, bg=SURFACE)
        self._home_clip_lbl.pack(side="left", padx=(10,0))

        hdiv(outer).pack(fill="x")
        self._home_hint = lbl(outer,
            "  Click 'Grab Input', your mouse & keyboard mirror to Mac Mini",
            11, TEXT2, bg=SURFACE)
        self._home_hint.pack(anchor="w", padx=14, pady=6)

    def _home_win_show(self):
        self._home.deiconify(); self._home.update_idletasks()
        sw = self._home.winfo_screenwidth(); w = self._home.winfo_reqwidth()
        self._home.geometry(f"+{(sw-w)//2}+30")

    def _home_win_hide(self):
        self._stop_overlay()
        self._home.withdraw()

    # ── Transparent overlay (the actual KVM magic) ─────────────────────────

    def _home_toggle_focus(self):
        if self._overlay and self._overlay.winfo_exists():
            self._stop_overlay()
        else:
            if not self.conn.connected:
                messagebox.showinfo("Not connected",
                    "Connect to the Mac Mini first, then grab input.")
                return
            self._start_overlay()

    def _start_overlay(self):
        """
        Home mode capture.

        A nearly-invisible fullscreen window handles clicks, scroll, keyboard.
        Mouse POSITION is polled every 16 ms via winfo_pointerx/y(); the OS
        always exposes the cursor location, no click-to-activate needed.
        """
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        self._ov_screen_w = sw
        self._ov_screen_h = sh

        ov = tk.Toplevel(self)
        ov.geometry(f"{sw}x{sh}+0+0")
        ov.overrideredirect(True)
        ov.attributes("-topmost", True)
        ov.attributes("-alpha", 0.01)
        ov.configure(bg="black")
        ov.focus_set()
        self._overlay = ov
        self._focused = True

        # Clicks / scroll
        ov.bind("<Button-1>",        lambda e: self._ov_click(e,"left",True))
        ov.bind("<ButtonRelease-1>", lambda e: self._ov_click(e,"left",False))
        ov.bind("<Button-2>",        lambda e: self._ov_click(e,"middle",True))
        ov.bind("<ButtonRelease-2>", lambda e: self._ov_click(e,"middle",False))
        ov.bind("<Button-3>",        lambda e: self._ov_click(e,"right",True))
        ov.bind("<ButtonRelease-3>", lambda e: self._ov_click(e,"right",False))
        ov.bind("<MouseWheel>",      self._ov_scroll)
        ov.bind("<Button-4>",        self._ov_scroll)
        ov.bind("<Button-5>",        self._ov_scroll)

        # Keyboard
        ov.bind("<KeyPress>",   self._ov_key_down)
        ov.bind("<KeyRelease>", self._ov_key_up)
        ov.bind("<Escape>",     lambda e: self._stop_overlay())

        # Mouse POSITION, polled (works without any click first)
        self._ov_poll_stop = threading.Event()
        threading.Thread(target=self._ov_poll_mouse, daemon=True).start()

        self._home_focus_btn.config(
            text="⏹  Release Input  (or press Esc)",
            bg=RED, fg="white", activebackground="#e0352c")
        self._home_hint.config(
            text="  Mouse & keyboard → Mac Mini  •  Press Esc to release",
            fg=BLUE)

    def _ov_poll_mouse(self):
        """
        Read absolute screen cursor position every 16 ms and mirror to Mac Mini.
        winfo_pointerx/y() reads straight from the OS, no window focus needed.
        """
        last = (-1, -1)
        stop = self._ov_poll_stop
        while not stop.is_set():
            try:
                ax = self.winfo_pointerx()
                ay = self.winfo_pointery()
                if (ax, ay) != last and self.conn.connected:
                    last = (ax, ay)
                    rx, ry = self._ov_abs_scale(ax, ay)
                    self.conn.send({"type": "move", "x": rx, "y": ry})
            except Exception:
                pass
            stop.wait(0.016)

    def _stop_overlay(self):
        self._focused = False
        if hasattr(self, "_ov_poll_stop"):
            self._ov_poll_stop.set()
        if self._overlay and self._overlay.winfo_exists():
            self._overlay.destroy()
        self._overlay = None
        self._home_focus_btn.config(
            text="⌨️  Grab Input: Mirror mouse & keyboard",
            bg=GREEN, fg="white", activebackground="#2db84d")
        self._home_hint.config(
            text="  Click 'Grab Input', your mouse & keyboard mirror to Mac Mini",
            fg=TEXT2)
        self._home.focus_set()

    # ── Overlay event handlers ────────────────────────────────────────────

    def _ov_abs_scale(self, ax, ay):
        """Absolute screen coords → Mac Mini screen coords."""
        sw = getattr(self, "_ov_screen_w", self.winfo_screenwidth())
        sh = getattr(self, "_ov_screen_h", self.winfo_screenheight())
        rx = int(ax / sw * self._remote_w)
        ry = int(ay / sh * self._remote_h)
        return max(0, min(self._remote_w, rx)), max(0, min(self._remote_h, ry))

    def _ov_click(self, e, button, pressed):
        if not self.conn.connected: return
        self._last_activity = time.time()
        # Click position comes from event coords (reliable after first click)
        # but we already have continuous position from polling, so just send the button
        rx, ry = self._ov_abs_scale(e.x_root, e.y_root)
        self.conn.send({"type":"click","x":rx,"y":ry,"button":button,"pressed":pressed})

    def _ov_scroll(self, e):
        if not self.conn.connected: return
        rx, ry = self._ov_abs_scale(self.winfo_pointerx(), self.winfo_pointery())
        dy = 3 if e.num == 4 else -3 if e.num == 5 else int(e.delta / 40)
        self.conn.send({"type":"scroll","x":rx,"y":ry,"dx":0,"dy":dy})

    def _ov_key_down(self, e):
        if e.keysym == "Escape" or not self.conn.connected: return
        self._last_activity = time.time()
        k = ev_to_key(e)
        if k: self.conn.send({"type":"key","key":k,"pressed":True})

    def _ov_key_up(self, e):
        if e.keysym == "Escape" or not self.conn.connected: return
        k = ev_to_key(e)
        if k: self.conn.send({"type":"key","key":k,"pressed":False})

    # ══════════════════════════════════════════════════════════════════════
    # Connect / disconnect
    # ══════════════════════════════════════════════════════════════════════

    def _sc_toggle_conn(self, _e):
        if self._focused: return            # don't hijack input that's mirroring
        self._toggle_conn(); return "break"

    def _sc_scan(self, _e):
        if self._focused: return
        self._scan(); return "break"

    def _toggle_conn(self):
        (self._disc if self.conn.connected else self._connect)()

    def _connect(self):
        host = self.host_var.get().strip()
        if not host: messagebox.showwarning("No host", "Enter an IP address first."); return
        try: port = int(self.port_var.get())
        except ValueError: messagebox.showwarning("Bad port", "Port must be a number."); return
        pw = self.pass_var.get() or None
        for b in (self._rbtn_conn, self._home_conn_btn):
            b.config(text="Connecting…", state="disabled")
        self._status("Connecting…")
        def worker():
            err = self.conn.connect(host, port, pw)   # blocking, stays off the UI thread
            self.after(0, lambda: self._conn_result(err))
        threading.Thread(target=worker, daemon=True).start()

    def _conn_result(self, err):
        for b in (self._rbtn_conn, self._home_conn_btn):
            b.config(state="normal")
        if err:
            self._rbtn_conn.config(text="Connect"); self._home_conn_btn.config(text="Connect")
            self._status(f"Failed: {err}"); messagebox.showerror("Connection failed", err); return

        hn = self.conn.hostname
        for b in (self._rbtn_conn, self._home_conn_btn):
            b.config(text="Disconnect", bg=RED, activebackground="#e0352c")
        self._set_pill(f"Connected  •  {hn}", GREEN, PILL_OK)
        self._home_pill.config(text=f"●  Connected  •  {hn}", bg=PILL_OK, fg=GREEN)
        self._home_host_lbl.config(text=hn)
        self._status(f"Connected to {hn}  •  Click preview to control  •  Ctrl+scroll to zoom")

        # Query monitors
        self.conn.send({"type": "list_monitors"})

        if self._mode == self.MODE_REMOTE:
            self._preview_on = True; self._sched()

        # Auto-clipboard
        if self._auto_clip:
            self.conn.send({"type": "clipboard_auto_enable"})

    def _disc(self):
        if self._ptimer: self.after_cancel(self._ptimer); self._ptimer = None
        self._focused = False; self.conn.close(); self._on_disc()

    def _on_disc(self):
        if self._ptimer: self.after_cancel(self._ptimer); self._ptimer = None
        self._focused = False; self._base_frame = None
        self._stop_overlay()   # release overlay if connection drops mid-grab
        for b in (self._rbtn_conn, self._home_conn_btn):
            b.config(text="Connect", bg=BLUE, activebackground=BLUE_H, state="normal")
        self._set_pill("Disconnected", RED, PILL_BAD)
        self._home_pill.config(text="●  Disconnected", bg=PILL_BAD, fg=RED)
        self._home_host_lbl.config(text="…")
        self._placeholder("Disconnected"); self._fps_lbl.config(text="")
        self._status("Disconnected")
        self._clear_monitor_picker()
        if self._term_win and self._term_win.winfo_exists():
            self._term_win.destroy()
        self._term_win = None; self._term_text = None
        # overlay already released above via _stop_overlay()

    def _set_pill(self, text, fg, bg):
        self._rpill_f.config(bg=bg); self._rpill_l.config(text="●  "+text, fg=fg, bg=bg)

    # ══════════════════════════════════════════════════════════════════════
    # Scan / status / profiles
    # ══════════════════════════════════════════════════════════════════════

    def _scan(self):
        self._status("Scanning LAN…")
        def worker():
            results = scan_lan()                       # blocking, stays off the UI thread
            self.after(0, lambda: self._scan_done(results))
        threading.Thread(target=worker, daemon=True).start()

    def _scan_done(self, results):
        if not results:
            self._status("No servers found")
            messagebox.showinfo("Scan LAN", "No servers found.\nMake sure server.py is running."); return
        r = results[0]
        self.host_var.set(r["ip"]); self.port_var.set(str(r["port"]))
        self._status(f"Found: {r.get('hostname', r['ip'])}  ({r['ip']})")

    def _status(self, msg): self._status_lbl.config(text=msg)

    def _refresh_profile_menu(self):
        menu = self._profile_menu["menu"]; menu.delete(0, "end")
        menu.add_command(label="Select…", command=lambda: self._profile_var.set("Select…"))
        for p in self._profiles_data.get("profiles", []):
            n = p["name"]
            menu.add_command(label=n, command=lambda x=n: self._load_profile(x))
        if self._profiles_data.get("profiles"):
            menu.add_separator()
            for p in self._profiles_data.get("profiles", []):
                n = p["name"]
                menu.add_command(label=f'✕ Delete "{n}"', command=lambda x=n: self._delete_profile(x))

    def _load_profile(self, name):
        for p in self._profiles_data.get("profiles", []):
            if p["name"] == name:
                self.host_var.set(p.get("host",""))
                self.port_var.set(str(p.get("port", DEFAULT_PORT)))
                self.pass_var.set(p.get("password",""))
                self._profile_var.set(name); self._status(f"Loaded: {name}"); return

    def _save_profile(self):
        host = self.host_var.get().strip()
        if not host: messagebox.showwarning("Nothing to save", "Enter a host IP first."); return
        name = simpledialog.askstring("Save profile", "Name for this connection:",
                                      initialvalue=self.conn.hostname or host, parent=self)
        if not name: return
        profiles = [p for p in self._profiles_data.get("profiles",[]) if p["name"] != name]
        profiles.append({"name":name,"host":host,
                          "port":int(self.port_var.get() or DEFAULT_PORT),
                          "password":self.pass_var.get()})
        self._profiles_data["profiles"] = profiles
        save_profiles(self._profiles_data); self._refresh_profile_menu()
        self._profile_var.set(name); self._status(f"Saved: {name}")

    def _delete_profile(self, name):
        self._profiles_data["profiles"] = [
            p for p in self._profiles_data.get("profiles",[]) if p["name"] != name]
        save_profiles(self._profiles_data); self._refresh_profile_menu()
        self._profile_var.set("Select…"); self._status(f"Deleted: {name}")

    # ══════════════════════════════════════════════════════════════════════
    # Monitor picker
    # ══════════════════════════════════════════════════════════════════════

    def _on_monitor_list(self, msg):
        self._monitors = msg.get("monitors", [])
        self.after(0, self._rebuild_monitor_picker)

    def _rebuild_monitor_picker(self):
        for w in self._monitor_frame.winfo_children(): w.destroy()
        if not self._monitors:
            lbl(self._monitor_frame, "No monitors found", 11, TEXT2, bg=SURFACE).pack(); return
        for m in self._monitors:
            mid = m["id"]
            label = f"🖥  {m['name']}  ({m['w']}×{m['h']})"
            is_sel = mid == self._monitor_id
            b = btn(self._monitor_frame, label,
                    lambda i=mid: self._pick_monitor(i),
                    color=BLUE if is_sel else SECONDARY,
                    fg="white" if is_sel else TEXT2, size=11)
            b.pack(fill="x", pady=2)

    def _pick_monitor(self, monitor_id):
        self._monitor_id = monitor_id
        self._base_frame = None
        self.conn.send({"type": "set_monitor", "id": monitor_id})
        self._rebuild_monitor_picker()
        self._status(f"Switched to Monitor {monitor_id}")

    def _clear_monitor_picker(self):
        for w in self._monitor_frame.winfo_children(): w.destroy()
        lbl(self._monitor_frame, "Connect to see monitors", 11, TEXT2, bg=SURFACE).pack()

    # ══════════════════════════════════════════════════════════════════════
    # Preview + delta compositing
    # ══════════════════════════════════════════════════════════════════════

    def _placeholder(self, msg="", sub=None):
        img = Image.new("RGB", (self.PW, self.PH), CANVAS_BG)
        d = ImageDraw.Draw(img)
        if sub is None:
            sub = ("Enter an IP and press Connect, or hit Scan LAN"
                   if msg == "Not connected" else
                   "Press Connect to reconnect")
        title_f, sub_f = load_font(26), load_font(13)

        def center(text, font, y, fill):
            box = d.textbbox((0, 0), text, font=font)
            w = box[2] - box[0]
            d.text(((self.PW - w)//2, y), text, font=font, fill=fill)

        center(msg, title_f, self.PH//2 - 30, "#8e8e93")
        center(sub,  sub_f,  self.PH//2 + 12, "#5a5a5e")
        self._base_frame = None; self._show(img)

    def _show(self, img: Image.Image):
        cw = self.canvas.winfo_width()  or self.PW
        ch = self.canvas.winfo_height() or self.PH
        display = self._apply_zoom(img, cw, ch)
        ph = ImageTk.PhotoImage(display); self._pimg = ph
        if self._cid: self.canvas.itemconfig(self._cid, image=ph)
        else: self._cid = self.canvas.create_image(0, 0, anchor="nw", image=ph)
        if self._fs_canvas: self._show_fs(img)

    def _apply_zoom(self, img: Image.Image, cw: int, ch: int) -> Image.Image:
        if self._zoom <= 1.01:
            return img.resize((cw, ch), Image.LANCZOS)
        iw, ih = img.size
        vw = 1.0 / self._zoom; vh = 1.0 / self._zoom
        x0 = max(0.0, min(self._pan_x - vw/2, 1.0 - vw))
        y0 = max(0.0, min(self._pan_y - vh/2, 1.0 - vh))
        crop = img.crop((int(x0*iw), int(y0*ih),
                         int((x0+vw)*iw), int((y0+vh)*ih)))
        return crop.resize((cw, ch), Image.LANCZOS)

    def _toggle_live(self):
        self._preview_on = not self._preview_on
        if self._preview_on:
            self._live_btn.config(text="⏸  Pause Preview"); self._sched()
        else:
            self._live_btn.config(text="▶  Resume Preview")
            if self._ptimer: self.after_cancel(self._ptimer); self._ptimer = None

    def _adaptive_ms(self):
        idle = time.time() - self._last_activity
        if idle < 2: return 100
        if idle < 8: return 333
        return 1200

    def _sched(self, ms=None):
        if self._preview_on and self.conn.connected and self._mode == self.MODE_REMOTE:
            self._ptimer = self.after(ms if ms is not None else self._adaptive_ms(), self._req)

    def _req(self):
        if not (self._preview_on and self.conn.connected and self._mode == self.MODE_REMOTE): return
        self._last_t = time.time()
        self.conn.send({"type":"screenshot_request","scale":0.4,"quality":62})

    def _on_frame_full(self, msg):
        if self._mode != self.MODE_REMOTE: return
        try: img = Image.open(io.BytesIO(base64.b64decode(msg["data"])))
        except: self._sched(2000); return
        if msg.get("orig_width"):
            self._remote_w = msg["orig_width"]; self._remote_h = msg["orig_height"]
        self._base_frame = img
        el = time.time() - self._last_t
        fps = f"{1/el:.1f}" if el > 0 else "?"; ms = int(el*1000)
        ow, oh = msg.get("orig_width","?"), msg.get("orig_height","?")
        sw, sh = msg.get("width","?"), msg.get("height","?")
        delta_tag = " [full]" if msg.get("type") == "frame_full" else ""
        self.after(0, lambda i=img: (
            self._show(i),
            self._fps_lbl.config(text=f"Remote: {ow}×{oh}  →  {sw}×{sh}  •  {fps} fps  •  {ms} ms{delta_tag}  •  Zoom: {self._zoom:.1f}×"),
        ))
        self._sched()

    def _on_frame_patch(self, msg):
        if self._mode != self.MODE_REMOTE: return
        if self._base_frame is None: self._sched(200); return
        try:
            patch = Image.open(io.BytesIO(base64.b64decode(msg["data"])))
        except: self._sched(2000); return
        if msg.get("orig_width"):
            self._remote_w = msg["orig_width"]; self._remote_h = msg["orig_height"]
        x, y = msg.get("x",0), msg.get("y",0)
        el = time.time() - self._last_t
        fps = f"{1/el:.1f}" if el > 0 else "?"; ms = int(el*1000)
        def _apply(p=patch, px=x, py=y):
            if self._base_frame is None: return
            self._base_frame.paste(p, (px, py))
            ow = msg.get("orig_width","?"); oh = msg.get("orig_height","?")
            pw = msg.get("w","?"); ph2 = msg.get("h","?")
            self._show(self._base_frame)
            self._fps_lbl.config(text=f"Remote: {ow}×{oh}  •  {fps} fps  •  {ms} ms  [patch {pw}×{ph2}]  •  Zoom: {self._zoom:.1f}×")
        self.after(0, _apply)
        self._sched()

    # ══════════════════════════════════════════════════════════════════════
    # Zoom & pan
    # ══════════════════════════════════════════════════════════════════════

    def _set_zoom(self, z):
        self._zoom = max(1.0, min(8.0, z))
        if self._zoom <= 1.01:
            self._zoom = 1.0; self._pan_x = 0.5; self._pan_y = 0.5
        self._zoom_lbl.config(text=f"Zoom {self._zoom:.1f}×" if self._zoom > 1 else "")
        if self._base_frame: self._show(self._base_frame)

    def _mscroll(self, e):
        if not self.conn.connected: return
        # Ctrl held → zoom; otherwise → scroll
        ctrl = e.state & 0x4
        if ctrl:
            z = self._zoom * (1.15 if (e.num == 4 or e.delta > 0) else 0.87)
            self._set_zoom(z)
        elif self._focused:
            rx, ry = self._scale(e.x, e.y)
            dy = 3 if e.num == 4 else -3 if e.num == 5 else int(e.delta/40)
            self.conn.send({"type":"scroll","x":rx,"y":ry,"dx":0,"dy":dy})

    def _ms_pan_start(self, e):
        self._pan_drag_start = (e.x, e.y, self._pan_x, self._pan_y)

    def _ms_pan_end(self, e):
        self._pan_drag_start = None

    def _ms_pan_drag(self, e):
        if not self._pan_drag_start or self._zoom <= 1.01: return
        sx, sy, px0, py0 = self._pan_drag_start
        cw = self.canvas.winfo_width() or self.PW
        ch = self.canvas.winfo_height() or self.PH
        dx = (e.x - sx) / cw / self._zoom
        dy = (e.y - sy) / ch / self._zoom
        self._pan_x = max(0.0, min(1.0, px0 - dx))
        self._pan_y = max(0.0, min(1.0, py0 - dy))
        if self._base_frame: self._show(self._base_frame)

    # ══════════════════════════════════════════════════════════════════════
    # Focus / mouse / keyboard
    # ══════════════════════════════════════════════════════════════════════

    def _focus_in(self, e):
        self._focused = True; self._border_f.config(bg=BLUE)
        self.canvas.config(cursor="crosshair")
        self._hint_lbl.config(text="Controlling Mac Mini  •  Esc to release  •  Ctrl+scroll to zoom", fg=BLUE)

    def _focus_out(self, e):
        self._focused = False; self._border_f.config(bg=BORDER)
        self.canvas.config(cursor="arrow")
        self._hint_lbl.config(text="Click preview to control  •  Double-click for full screen", fg=TEXT2)

    def _scale(self, cx, cy):
        cw = self.canvas.winfo_width() or self.PW
        ch = self.canvas.winfo_height() or self.PH
        if self._zoom > 1.01:
            vw = 1.0 / self._zoom; vh = 1.0 / self._zoom
            x0 = max(0.0, min(self._pan_x - vw/2, 1.0 - vw))
            y0 = max(0.0, min(self._pan_y - vh/2, 1.0 - vh))
            rx = (x0 + (cx/cw) * vw) * self._remote_w
            ry = (y0 + (cy/ch) * vh) * self._remote_h
        else:
            rx = cx / cw * self._remote_w; ry = cy / ch * self._remote_h
        return int(rx), int(ry)

    def _mc(self, e, b, pressed):
        if not self.conn.connected: return
        if not self._focused: self.canvas.focus_set(); return
        self._last_activity = time.time()
        rx, ry = self._scale(e.x, e.y)
        self.conn.send({"type":"click","x":rx,"y":ry,"button":b,"pressed":pressed})

    def _mm(self, e):
        if not (self.conn.connected and self._focused): return
        self._last_activity = time.time()
        rx, ry = self._scale(e.x, e.y)
        self.conn.send({"type":"move","x":rx,"y":ry})

    def _key_down(self, e):
        # Never intercept keys when a text entry box has focus
        fw = self.focus_get()
        if isinstance(fw, (tk.Entry, tk.Text)): return

        if self._focused: self._last_activity = time.time()
        if e.keysym == "Escape" and self._focused:
            self._focused = False
            if self._mode == self.MODE_REMOTE:
                self.focus_set(); self._focus_out(None)
            else:
                self._home_toggle_focus()
            return
        if not (self.conn.connected and self._focused): return
        k = ev_to_key(e)
        if k: self.conn.send({"type":"key","key":k,"pressed":True})

    def _key_up(self, e):
        if not (self.conn.connected and self._focused) or e.keysym == "Escape": return
        k = ev_to_key(e)
        if k: self.conn.send({"type":"key","key":k,"pressed":False})

    # ══════════════════════════════════════════════════════════════════════
    # Full screen
    # ══════════════════════════════════════════════════════════════════════

    def _open_fullscreen(self):
        if not self.conn.connected: return
        if self._fs_win and self._fs_win.winfo_exists(): return
        sw = self.winfo_screenwidth(); sh = self.winfo_screenheight()
        win = tk.Toplevel(self); win.title("")
        win.configure(bg="#000"); win.geometry(f"{sw}x{sh}+0+0")
        win.attributes("-fullscreen", True); win.attributes("-topmost", True)
        win.focus_set(); self._fs_win = win
        c = tk.Canvas(win, bg="#000", highlightthickness=0, cursor="crosshair")
        c.pack(fill="both", expand=True); c.config(takefocus=True); c.focus_set()
        self._fs_canvas = c; self._fs_cid = None
        for seq, fn in [
            ("<Button-1>",        lambda e: self._fs_click(e,"left",True)),
            ("<ButtonRelease-1>", lambda e: self._fs_click(e,"left",False)),
            ("<Button-3>",        lambda e: self._fs_click(e,"right",True)),
            ("<ButtonRelease-3>", lambda e: self._fs_click(e,"right",False)),
            ("<Motion>",          self._fs_move),
            ("<MouseWheel>",      self._fs_scroll),
            ("<Button-4>",        self._fs_scroll),
            ("<Button-5>",        self._fs_scroll),
            ("<Double-Button-1>", lambda e: self._close_fullscreen()),
        ]:
            c.bind(seq, fn)
        win.bind("<KeyPress>",   self._key_down)
        win.bind("<KeyRelease>", self._key_up)
        win.bind("<Escape>",     lambda e: self._close_fullscreen())
        # Hint overlay
        hid = c.create_text(sw//2, 36, text="Esc or double-click to exit full screen",
                            fill="white", font=(FONT,14), tags="hint")
        bbox = c.bbox(hid)
        if bbox:
            c.create_rectangle(bbox[0]-12,bbox[1]-8,bbox[2]+12,bbox[3]+8,
                               fill=SURFACE, outline="", tags="hint")
            c.tag_raise(hid)
        win.after(3000, lambda: c.delete("hint"))
        self._focused = True
        win.protocol("WM_DELETE_WINDOW", self._close_fullscreen)
        if self._base_frame: self._show_fs(self._base_frame)

    def _close_fullscreen(self):
        if self._fs_win and self._fs_win.winfo_exists(): self._fs_win.destroy()
        self._fs_win = None; self._fs_canvas = None; self._fs_cid = None; self._fs_pimg = None
        self.canvas.focus_set()

    def _show_fs(self, img: Image.Image):
        if not self._fs_canvas or not (self._fs_win and self._fs_win.winfo_exists()): return
        w = self._fs_canvas.winfo_width()  or self.winfo_screenwidth()
        h = self._fs_canvas.winfo_height() or self.winfo_screenheight()
        aspect = self._remote_w / max(self._remote_h, 1)
        if w / h > aspect: dh=h; dw=int(h*aspect)
        else: dw=w; dh=int(w/aspect)
        # Apply zoom to FS too
        display_img = self._apply_zoom(img, dw, dh)
        ph = ImageTk.PhotoImage(display_img); self._fs_pimg = ph
        x, y = (w-dw)//2, (h-dh)//2
        if self._fs_cid:
            self._fs_canvas.itemconfig(self._fs_cid, image=ph)
            self._fs_canvas.coords(self._fs_cid, x, y)
        else: self._fs_cid = self._fs_canvas.create_image(x, y, anchor="nw", image=ph)
        self._fs_offset = (x, y, dw, dh)

    def _fs_scale(self, cx, cy):
        x0,y0,dw,dh = getattr(self,"_fs_offset",(0,0,self.winfo_screenwidth(),self.winfo_screenheight()))
        if self._zoom > 1.01:
            vw=1/self._zoom; vh=1/self._zoom
            ix=max(0,min(self._pan_x-vw/2,1-vw)); iy=max(0,min(self._pan_y-vh/2,1-vh))
            rx=(ix+((cx-x0)/dw)*vw)*self._remote_w
            ry=(iy+((cy-y0)/dh)*vh)*self._remote_h
        else:
            rx=(cx-x0)/dw*self._remote_w; ry=(cy-y0)/dh*self._remote_h
        return int(max(0,rx)), int(max(0,ry))

    def _fs_click(self,e,b,p):
        if not self.conn.connected: return
        self._last_activity = time.time()
        rx,ry = self._fs_scale(e.x,e.y)
        self.conn.send({"type":"click","x":rx,"y":ry,"button":b,"pressed":p})

    def _fs_move(self,e):
        if not self.conn.connected: return
        self._last_activity = time.time()
        rx,ry = self._fs_scale(e.x,e.y)
        self.conn.send({"type":"move","x":rx,"y":ry})

    def _fs_scroll(self,e):
        if not self.conn.connected: return
        rx,ry = self._fs_scale(e.x,e.y)
        dy=3 if e.num==4 else -3 if e.num==5 else int(e.delta/40)
        self.conn.send({"type":"scroll","x":rx,"y":ry,"dx":0,"dy":dy})

    # ══════════════════════════════════════════════════════════════════════
    # Clipboard
    # ══════════════════════════════════════════════════════════════════════

    def _toggle_auto_clip(self):
        self._auto_clip = not self._auto_clip
        if self._auto_clip:
            self._auto_clip_btn.config(text="⟳  Auto-sync: ON", bg=GREEN, fg="white")
            self._last_clip_hash = hash(clip_get())
            if self.conn.connected: self.conn.send({"type":"clipboard_auto_enable"})
            self._clip_watcher_stop = threading.Event()
            threading.Thread(target=self._clip_watch_loop, daemon=True).start()
            self._clip_status("Auto-sync ON")
        else:
            self._auto_clip_btn.config(text="⟳  Auto-sync: OFF", bg=SECONDARY, fg=TEXT)
            if hasattr(self,"_clip_watcher_stop"): self._clip_watcher_stop.set()
            if self.conn.connected: self.conn.send({"type":"clipboard_auto_disable"})
            self._clip_status("Auto-sync OFF")

    def _clip_watch_loop(self):
        stop = self._clip_watcher_stop
        while not stop.wait(1.0):
            if not self.conn.connected: continue
            try:
                text = clip_get(); h = hash(text)
                if h != self._last_clip_hash and text:
                    self._last_clip_hash = h
                    self.conn.send({"type":"clipboard_push","text":text})
                    self.after(0, lambda t=text: self._clip_status(f'Auto-pushed "{t[:22]}{"…" if len(t)>22 else ""}"'))
            except: pass

    def _on_clip_auto(self, msg):
        text = msg.get("text","")
        if not text: return
        clip_set(text); self._last_clip_hash = hash(text)
        self.after(0, lambda: self._clip_status(f'Auto-pulled "{text[:22]}{"…" if len(text)>22 else ""}"'))

    def _push_clip(self):
        if not self.conn.connected: self._clip_status("Not connected"); return
        t = clip_get()
        if t:
            self.conn.send({"type":"clipboard_push","text":t})
            self._clip_status(f'Pushed "{t[:22]}{"…" if len(t)>22 else ""}"')
        else: self._clip_status("Clipboard empty")

    def _pull_clip(self):
        if not self.conn.connected: self._clip_status("Not connected"); return
        self.conn.send({"type":"clipboard_pull"})

    def _on_clip(self, msg):
        t = msg.get("text",""); clip_set(t)
        self.after(0, lambda: self._clip_status(f'Pulled "{t[:22]}{"…" if len(t)>22 else ""}"'))

    def _clip_status(self, msg):
        self._clip_lbl.config(text=msg); self._home_clip_lbl.config(text=msg)

    # ══════════════════════════════════════════════════════════════════════
    # File transfer
    # ══════════════════════════════════════════════════════════════════════

    def _send_file(self):
        if not self.conn.connected: self._file_lbl.config(text="Not connected"); return
        path = filedialog.askopenfilename(parent=self, title="Select file to send")
        if not path: return
        p = Path(path)
        if not p.exists(): return
        size = p.stat().st_size
        fid  = uuid.uuid4().hex[:8]
        self._file_pending[fid] = p
        self.conn.send({"type":"file_start","id":fid,"name":p.name,"size":size})
        self._file_lbl.config(text=f"Sending {p.name}…")
        threading.Thread(target=self._send_file_chunks, args=(fid,p,size), daemon=True).start()

    def _send_file_chunks(self, fid, path, size):
        try:
            sent = 0
            with open(path, "rb") as f:
                seq = 0
                while True:
                    chunk = f.read(CHUNK_SIZE)
                    if not chunk: break
                    sent += len(chunk)
                    final = (sent >= size)
                    self.conn.send({
                        "type": "file_chunk",
                        "id": fid, "seq": seq,
                        "data": base64.b64encode(chunk).decode(),
                        "final": final,
                    })
                    pct = int(sent/size*100)
                    self.after(0, lambda p=pct: self._file_lbl.config(text=f"Sending… {p}%"))
                    seq += 1
        except Exception as e:
            self.after(0, lambda: self._file_lbl.config(text=f"Error: {e}"))

    def _on_file_ack(self, msg):
        pass  # server ready, chunks already sending

    def _on_file_done(self, msg):
        name = msg.get("name","file")
        path = msg.get("path","")
        self.after(0, lambda: self._file_lbl.config(text=f"✓ Saved: {name}"))

    # ══════════════════════════════════════════════════════════════════════
    # Terminal (live shell on the remote machine)
    # ══════════════════════════════════════════════════════════════════════

    _ANSI_RE = re.compile(
        r"\x1b\[[0-9;?]*[ -/]*[@-~]"      # CSI sequences
        r"|\x1b\][^\x07]*(?:\x07|\x1b\\)" # OSC sequences
        r"|\x1b[@-Z\\-_]"                 # other escapes
        r"|[\x00-\x08\x0b\x0c\x0e-\x1f]"  # control chars (keep \t and \n)
    )

    def _open_terminal(self):
        if not self.conn.connected:
            messagebox.showinfo("Terminal", "Connect to a server first."); return
        if self._term_win and self._term_win.winfo_exists():
            self._term_win.lift(); self._term_win.focus_force(); return

        win = tk.Toplevel(self); win.title(f"Terminal: {self.conn.hostname}")
        win.configure(bg=CANVAS_BG); win.geometry("780x480"); win.minsize(480, 280)
        self._term_win = win
        win.protocol("WM_DELETE_WINDOW", self._close_terminal)

        hdr = tk.Frame(win, bg=SURFACE, highlightthickness=1, highlightbackground=BORDER)
        hdr.pack(fill="x")
        lbl(hdr, f"🖥  {self.conn.hostname}", 12, bold=True, bg=SURFACE).pack(side="left", padx=12, pady=6)
        sbtn(hdr, "Ctrl-C", lambda: self.conn.send({"type": "term_signal", "sig": "int"})
             ).pack(side="right", padx=(0, 10), pady=5)
        sbtn(hdr, "Clear", self._term_clear).pack(side="right", padx=(0, 6), pady=5)

        body = tk.Frame(win, bg=CANVAS_BG); body.pack(fill="both", expand=True)
        scr = tk.Scrollbar(body)
        txt = tk.Text(body, bg=CANVAS_BG, fg="#d6d6d6", insertbackground="#d6d6d6",
                      font=("Menlo", 12), relief="flat", bd=0, wrap="char",
                      highlightthickness=0, padx=8, pady=6, yscrollcommand=scr.set)
        scr.config(command=txt.yview); scr.pack(side="right", fill="y")
        txt.pack(side="left", fill="both", expand=True)
        txt.config(state="disabled"); self._term_text = txt

        row = tk.Frame(win, bg=SURFACE, highlightthickness=1, highlightbackground=BORDER)
        row.pack(fill="x")
        lbl(row, "❯", 13, color=GREEN, bg=SURFACE).pack(side="left", padx=(10, 4), pady=6)
        self._term_var = tk.StringVar()
        ent = tk.Entry(row, textvariable=self._term_var, bg=SURFACE, fg=TEXT,
                       insertbackground=TEXT, font=("Menlo", 12), relief="flat",
                       bd=0, highlightthickness=0)
        ent.pack(side="left", fill="x", expand=True, pady=6, padx=(0, 10))
        ent.bind("<Return>", self._term_send)
        ent.focus_set()

        self.conn.send({"type": "term_start"})

    def _term_send(self, _e=None):
        if not (self.conn.connected and self._term_win): return
        self.conn.send({"type": "term_input", "data": self._term_var.get() + "\n"})
        self._term_var.set("")

    def _term_clear(self):
        if not self._term_text: return
        self._term_text.config(state="normal")
        self._term_text.delete("1.0", "end")
        self._term_text.config(state="disabled")

    def _on_term_output(self, msg):
        data = msg.get("data", "")
        if data:
            self.after(0, lambda: self._term_append(data))

    def _term_append(self, data):
        t = self._term_text
        if not (t and self._term_win and self._term_win.winfo_exists()): return
        # Strip escape sequences but keep \t \n \r, then apply carriage returns:
        # a lone \r rewrites the current line (how shells redraw prompts/input).
        clean = self._ANSI_RE.sub("", data)
        t.config(state="normal")
        for part in re.split(r"(\r\n|\r|\n)", clean):
            if part == "\r":
                t.delete("end-1c linestart", "end-1c")     # overwrite current line
            elif part in ("\n", "\r\n"):
                t.insert("end", "\n")
            elif part:
                t.insert("end", part)
        t.see("end")
        if int(t.index("end-1c").split(".")[0]) > 6000:    # cap the scrollback
            t.delete("1.0", "1500.0")
        t.config(state="disabled")

    def _close_terminal(self):
        if self.conn.connected:
            self.conn.send({"type": "term_close"})
        if self._term_win and self._term_win.winfo_exists():
            self._term_win.destroy()
        self._term_win = None; self._term_text = None

    # ══════════════════════════════════════════════════════════════════════
    # Update check
    # ══════════════════════════════════════════════════════════════════════

    def _check_updates_async(self, manual=False):
        def worker():
            res = fetch_latest_release()
            self.after(0, lambda: self._on_update_result(res, manual))
        threading.Thread(target=worker, daemon=True).start()

    def _on_update_result(self, res, manual):
        if not res:
            if manual:
                messagebox.showinfo("Updates", "Couldn't reach GitHub to check for updates.")
            return
        tag, url, body, assets = res
        if _parse_ver(tag) > _parse_ver(__version__):
            self._show_update_dialog(tag, url, body, assets)
        elif manual:
            messagebox.showinfo("Updates", f"You're on the latest version (v{__version__}).")

    def _can_inplace_update(self, assets):
        # Only the packaged macOS .app can swap itself in place.
        return getattr(sys, "frozen", False) and IS_MAC and UPDATE_ASSET in (assets or {})

    def _show_update_dialog(self, tag, url, body, assets):
        win = tk.Toplevel(self); win.title("Update available")
        win.configure(bg=BG); win.transient(self); win.resizable(False, False)
        win.attributes("-topmost", True)
        pad = tk.Frame(win, bg=BG); pad.pack(fill="both", expand=True, padx=20, pady=18)
        lbl(pad, "Update available", 17, bold=True).pack(anchor="w")
        lbl(pad, f"{tag} is available. You have v{__version__}", 12, TEXT2).pack(
            anchor="w", pady=(4, 10))

        box = tk.Frame(pad, bg=SURFACE, highlightthickness=1, highlightbackground=BORDER)
        box.pack(fill="both", expand=True)
        txt = tk.Text(box, bg=SURFACE, fg=TEXT, font=(FONT, 11), relief="flat", bd=0,
                      wrap="word", height=11, width=54, padx=12, pady=10,
                      highlightthickness=0, insertbackground=TEXT)
        txt.insert("1.0", (body or "").strip() or "No release notes.")
        txt.config(state="disabled"); txt.pack(fill="both", expand=True)

        row = tk.Frame(pad, bg=BG); row.pack(fill="x", pady=(14, 0))
        sbtn(row, "Later", win.destroy).pack(side="right", padx=(0, 8))
        if self._can_inplace_update(assets):
            btn(row, "Update & Restart",
                lambda: self._start_inplace_update(assets[UPDATE_ASSET], url, win, pad)
                ).pack(side="right")
        else:
            btn(row, "Download",
                lambda: (webbrowser.open(url), win.destroy())).pack(side="right")

        win.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() - win.winfo_reqwidth()) // 2
        win.geometry(f"+{max(0, x)}+{self.winfo_rooty() + 90}")
        win.lift(); win.focus_force()

    def _start_inplace_update(self, asset_url, fallback_url, win, pad):
        for w in pad.winfo_children():
            w.destroy()
        lbl(pad, "Updating…", 16, bold=True).pack(anchor="w")
        status = lbl(pad, "Downloading the new version…", 12, TEXT2)
        status.pack(anchor="w", pady=(10, 16))

        def fail(msg):
            status.config(text=msg, fg=ORANGE)
            r = tk.Frame(pad, bg=BG); r.pack(anchor="e", pady=(8, 0))
            sbtn(r, "Close", win.destroy).pack(side="right", padx=(0, 8))
            btn(r, "Open download page",
                lambda: (webbrowser.open(fallback_url), win.destroy())).pack(side="right")

        def worker():
            try:
                tmp = Path(tempfile.mkdtemp(prefix="rcupd_"))
                zpath = tmp / "update.zip"
                _download(asset_url, zpath)
                self.after(0, lambda: status.config(text="Installing…"))
                subprocess.run(["ditto", "-x", "-k", str(zpath), str(tmp / "x")], check=True)
                new_app = tmp / "x" / "Remote Control.app"
                if not (new_app / "Contents" / "MacOS").exists():
                    raise RuntimeError("downloaded app looks malformed")
                app_path = Path(sys.executable).resolve().parents[2]   # …/Remote Control.app
                pid = os.getpid()
                script = tmp / "swap.sh"
                script.write_text(
                    "#!/bin/bash\n"
                    f'APP="{app_path}"\nNEW="{new_app}"\n'
                    f'while kill -0 {pid} 2>/dev/null; do sleep 0.3; done\n'
                    'rm -rf "$APP.bak"\n'
                    'mv "$APP" "$APP.bak" || exit 1\n'
                    'if ! mv "$NEW" "$APP"; then mv "$APP.bak" "$APP"; open "$APP"; exit 1; fi\n'
                    'xattr -dr com.apple.quarantine "$APP" 2>/dev/null\n'
                    'open "$APP"\n'
                    'rm -rf "$APP.bak"\n')
                os.chmod(script, 0o755)
                subprocess.Popen(["/bin/bash", str(script)], start_new_session=True)
                self.after(0, self._quit_for_update)
            except Exception as e:
                self.after(0, lambda: fail(f"Update failed: {e}"))

        threading.Thread(target=worker, daemon=True).start()

    def _quit_for_update(self):
        try: self.conn.close()
        except Exception: pass
        self.destroy()

    def destroy(self):
        self._disc(); super().destroy()

if __name__ == "__main__":
    App().mainloop()
