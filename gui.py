"""
EvilBot V3 by Blackberry — GUI for the EvilQuest automated bot.
"""

import os
import re
import sys
import queue
import logging
import asyncio
import threading
import tkinter as tk
from tkinter import ttk
from pathlib import Path

from PIL import Image, ImageTk, ImageDraw, ImageFont


# ── Load .env early so login fields can be pre-filled ────────────────────────

def _load_dotenv_early() -> None:
    env = Path(__file__).parent / ".env"
    if not env.exists():
        return
    with open(env) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            if k and k not in os.environ:
                os.environ[k] = v.strip()

_load_dotenv_early()


# ── Asset resolver (works both in dev and PyInstaller EXE) ───────────────────

def _res(rel: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


# ── Palette ───────────────────────────────────────────────────────────────────

C_BG      = "#0d0d18"
C_PANEL   = "#11111e"
C_HEADER  = "#090914"
C_ENTRY   = "#191928"
C_BORDER  = "#38304a"
C_TEXT    = "#cccce0"
C_DIM     = "#55556a"
C_GOLD    = "#c8a840"
C_GOLD2   = "#e8c860"
C_GREEN   = "#48c848"
C_CYAN    = "#58c8e8"
C_YELLOW  = "#e0c040"
C_RED     = "#e04848"
C_PURPLE  = "#9858d8"
C_ORANGE  = "#e08830"
C_LOG_BG  = "#06060e"
C_STONE   = "#18181f"


# ── Image helpers ─────────────────────────────────────────────────────────────

def _tile_stone(w: int, h: int, darken: int = 140) -> ImageTk.PhotoImage:
    """Tile the stone-dark texture and apply a dark overlay."""
    stone = Image.open(_res("gameassets/ui/stone-dark.png")).convert("RGBA")
    tile  = stone.resize((300, 300), Image.LANCZOS)
    bg    = Image.new("RGBA", (w, h))
    for x in range(0, w, tile.width):
        for y in range(0, h, tile.height):
            bg.paste(tile, (x, y))
    ov = Image.new("RGBA", (w, h), (4, 4, 12, darken))
    return ImageTk.PhotoImage(Image.alpha_composite(bg, ov).convert("RGB"))


def _load_sprite(filename: str, size: int) -> ImageTk.PhotoImage | None:
    try:
        img = Image.open(_res(f"gameassets/sprites/items/{filename}")).convert("RGBA")
        img = img.resize((size, size), Image.LANCZOS)
        bg  = Image.new("RGB", img.size, (int(C_PANEL[1:3], 16),
                                          int(C_PANEL[3:5], 16),
                                          int(C_PANEL[5:7], 16)))
        bg.paste(img, mask=img.split()[3])
        return ImageTk.PhotoImage(bg)
    except Exception:
        return None


def _make_btn_img(w: int, h: int, color_hex: str,
                  hover_hex: str | None = None) -> tuple:
    """Return (normal_img, hover_img) for a styled button."""
    def _draw(col: str) -> ImageTk.PhotoImage:
        img  = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        r    = int(col[1:3], 16)
        g    = int(col[3:5], 16)
        b    = int(col[5:7], 16)
        draw.rounded_rectangle([0, 0, w - 1, h - 1], radius=5,
                                fill=(r, g, b, 240),
                                outline=(min(r + 60, 255),
                                         min(g + 60, 255),
                                         min(b + 60, 255), 255),
                                width=1)
        return ImageTk.PhotoImage(img.convert("RGB"))
    return _draw(color_hex), _draw(hover_hex or color_hex)


# ── Queue logging handler ─────────────────────────────────────────────────────

class _QueueHandler(logging.Handler):
    def __init__(self, q: queue.Queue):
        super().__init__()
        self.q = q
        self.setFormatter(logging.Formatter(
            "%(asctime)s  %(levelname)-8s  %(message)s", datefmt="%H:%M:%S",
        ))

    def emit(self, record):
        try:
            self.q.put_nowait(self.format(record))
        except Exception:
            self.handleError(record)


# ── Skill / stat names ────────────────────────────────────────────────────────

SKILL_NAMES = {0: "Attack", 1: "Strength", 2: "Defence",
               3: "Ranged", 4: "Prayer", 5: "Magic",
               6: "HP", 7: "Woodcutting", 8: "Mining"}


# ── Application ───────────────────────────────────────────────────────────────

class EvilBotApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("EvilBot V3 by Blackberry")
        self.root.configure(bg=C_BG)
        self.root.resizable(False, False)

        # Shared state
        self._log_q:       queue.Queue                  = queue.Queue()
        self._bot_thread:  threading.Thread | None      = None
        self._bot_loop:    asyncio.AbstractEventLoop | None = None
        self._running      = False
        self._username     = ""
        self._password     = ""
        self._mode         = "woodcutting"
        self._handler:     _QueueHandler | None         = None

        # Live stats (updated by parsing log lines)
        self._kills   = 0
        self._chops   = 0
        self._xp:     dict[int, int] = {}

        # Cached images — must be kept alive or tkinter GCs them
        self._images: list = []

        self._build_login()
        self.root.mainloop()

    # ── Utility ───────────────────────────────────────────────────────────────

    def _center(self, w: int, h: int):
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")

    def _keep(self, img):
        """Prevent a PhotoImage from being garbage-collected."""
        self._images.append(img)
        return img

    # ── Login screen ──────────────────────────────────────────────────────────

    def _build_login(self):
        W, H = 460, 520
        self._center(W, H)

        canvas = tk.Canvas(self.root, width=W, height=H,
                           highlightthickness=0, bg=C_BG)
        canvas.pack(fill="both", expand=True)

        # Stone background
        try:
            bg_img = self._keep(_tile_stone(W, H, darken=155))
            canvas.create_image(0, 0, anchor="nw", image=bg_img)
        except Exception:
            canvas.configure(bg=C_STONE)

        # Dark card
        cx, cy = W // 2, H // 2
        pad = 30
        cw, ch = W - pad * 2, H - pad * 2
        canvas.create_rectangle(cx - cw // 2, cy - ch // 2,
                                 cx + cw // 2, cy + ch // 2,
                                 fill="#0c0c1a", outline=C_BORDER, width=2)
        # Gold accent line at top of card
        canvas.create_line(cx - cw // 2 + 12, cy - ch // 2 + 3,
                            cx + cw // 2 - 12, cy - ch // 2 + 3,
                            fill=C_GOLD, width=2)

        # Sprite — helm or axe
        sprite = (_load_sprite("helm base.png", 48)
                  or _load_sprite("axe base.png", 48))
        if sprite:
            self._keep(sprite)
            canvas.create_image(cx, cy - ch // 2 + 46, anchor="center",
                                 image=sprite)

        # Title
        canvas.create_text(cx, cy - ch // 2 + 80,
                            text="EvilBot V3",
                            font=("Segoe UI", 26, "bold"),
                            fill=C_GOLD)
        canvas.create_text(cx, cy - ch // 2 + 108,
                            text="by Blackberry",
                            font=("Segoe UI", 10),
                            fill=C_DIM)
        # Thin separator
        sep_y = cy - ch // 2 + 124
        canvas.create_line(cx - 80, sep_y, cx + 80, sep_y,
                            fill=C_BORDER, width=1)

        # ── Form widgets embedded in canvas ──────────────────────────────────
        form_y = sep_y + 20
        row_h  = 54

        def make_label(text, y):
            canvas.create_text(cx - cw // 2 + 24, y,
                                text=text, anchor="w",
                                font=("Segoe UI", 9),
                                fill=C_DIM)

        def make_entry(y, show=None):
            var = tk.StringVar()
            kw  = {"show": show} if show else {}
            ent = tk.Entry(canvas, textvariable=var,
                           font=("Segoe UI", 11),
                           bg=C_ENTRY, fg=C_TEXT,
                           insertbackground=C_TEXT,
                           selectbackground=C_GOLD, selectforeground="#000",
                           relief="flat", bd=6,
                           highlightthickness=1,
                           highlightbackground=C_BORDER,
                           highlightcolor=C_GOLD,
                           width=22, **kw)
            canvas.create_window(cx, y + 16, window=ent)
            return var, ent

        # Username
        make_label("Username", form_y + row_h * 0)
        self._uvar, self._uent = make_entry(form_y + row_h * 0 + 10)

        # Password
        make_label("Password", form_y + row_h * 1)
        self._pvar, self._pent = make_entry(form_y + row_h * 1 + 10, show="●")

        # Mode selector
        make_label("Mode", form_y + row_h * 2)
        self._mode_var = tk.StringVar(value="Woodcutting")
        mode_combo = ttk.Combobox(canvas, textvariable=self._mode_var,
                                  values=["Woodcutting", "Combat"],
                                  state="readonly", width=20,
                                  font=("Segoe UI", 10))
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TCombobox",
                         fieldbackground=C_ENTRY, background=C_ENTRY,
                         foreground=C_TEXT, selectbackground=C_GOLD,
                         selectforeground="#000",
                         bordercolor=C_BORDER, arrowcolor=C_GOLD)
        canvas.create_window(cx, form_y + row_h * 2 + 26, window=mode_combo)

        # Error label
        self._err_var = tk.StringVar()
        err_lbl = tk.Label(canvas, textvariable=self._err_var,
                           font=("Segoe UI", 9), bg="#0c0c1a", fg=C_RED)
        canvas.create_window(cx, form_y + row_h * 3 + 10, window=err_lbl)

        # Login button
        btn_y = form_y + row_h * 3 + 32
        self._login_btn = tk.Button(
            canvas,
            text="▶  Login & Start Bot",
            font=("Segoe UI", 11, "bold"),
            bg=C_GOLD, fg="#0a0a14",
            activebackground=C_GOLD2, activeforeground="#0a0a14",
            relief="flat", bd=0, padx=20, pady=9,
            cursor="hand2", command=self._on_login,
        )
        canvas.create_window(cx, btn_y, window=self._login_btn)

        # Bindings
        self._uent.bind("<Return>", lambda _: self._pent.focus())
        self._pent.bind("<Return>", lambda _: self._on_login())
        self._uent.focus()
        self._canvas_login = canvas

        # Pre-fill credentials from .env / environment if available
        env_user = os.environ.get("EVILQUEST_USER", "")
        env_pass = os.environ.get("EVILQUEST_PASSWORD", "")
        if env_user:
            self._uvar.set(env_user)
        if env_pass:
            self._pvar.set(env_pass)
        # If both are pre-filled, move focus to the mode selector
        if env_user and env_pass:
            mode_combo.focus()

    def _on_login(self):
        u = self._uvar.get().strip()
        p = self._pvar.get().strip()
        if not u or not p:
            self._err_var.set("Enter username and password.")
            return
        self._err_var.set("")
        self._login_btn.configure(state="disabled", text="Connecting…")
        self.root.update_idletasks()
        self._username = u
        self._password = p
        self._mode     = self._mode_var.get().lower()
        self._canvas_login.destroy()
        self._images.clear()
        self._build_console()
        self._launch_bot()

    # ── Console screen ────────────────────────────────────────────────────────

    def _build_console(self):
        self.root.resizable(True, True)
        self._center(920, 620)

        # ── Header bar ───────────────────────────────────────────────────────
        hdr = tk.Frame(self.root, bg=C_HEADER, pady=0)
        hdr.pack(fill="x", side="top")

        # Mode sprite
        sprite_file = ("axe base.png" if self._mode == "woodcutting"
                       else "chainmail.png")
        spr = _load_sprite(sprite_file, 28)
        if spr:
            self._keep(spr)
            tk.Label(hdr, image=spr, bg=C_HEADER).pack(side="left", padx=(10, 4), pady=6)

        # Title
        tk.Label(hdr, text="EvilBot V3",
                 font=("Segoe UI", 13, "bold"),
                 bg=C_HEADER, fg=C_GOLD).pack(side="left", padx=(0, 6))

        # Separator
        tk.Label(hdr, text="|", font=("Segoe UI", 11),
                 bg=C_HEADER, fg=C_BORDER).pack(side="left")

        # Player info
        tk.Label(hdr, text=f"  ● {self._username}",
                 font=("Segoe UI", 9, "bold"),
                 bg=C_HEADER, fg=C_GREEN).pack(side="left")

        mode_label = self._mode.capitalize()
        mode_color = C_CYAN if self._mode == "woodcutting" else C_ORANGE
        tk.Label(hdr, text=f"  {mode_label}",
                 font=("Segoe UI", 9),
                 bg=C_HEADER, fg=mode_color).pack(side="left")

        # Buttons — right side
        self._stop_btn = tk.Button(
            hdr, text="■  Stop",
            font=("Segoe UI", 9, "bold"),
            bg=C_RED, fg="white",
            activebackground="#b03030", activeforeground="white",
            relief="flat", bd=0, padx=14, pady=5,
            cursor="hand2", command=self._on_stop,
        )
        self._stop_btn.pack(side="right", padx=(4, 10), pady=6)

        self._start_btn = tk.Button(
            hdr, text="▶  Start",
            font=("Segoe UI", 9, "bold"),
            bg=C_DIM, fg="white",
            activebackground="#2a6a2a", activeforeground="white",
            relief="flat", bd=0, padx=14, pady=5,
            cursor="hand2", command=self._on_restart,
            state="disabled",
        )
        self._start_btn.pack(side="right", padx=(0, 4), pady=6)

        # Thin gold accent under header
        sep = tk.Frame(self.root, bg=C_GOLD, height=1)
        sep.pack(fill="x")

        # ── Body ─────────────────────────────────────────────────────────────
        body = tk.Frame(self.root, bg=C_BG)
        body.pack(fill="both", expand=True)

        # ── Stats sidebar (fixed 160px) ───────────────────────────────────────
        sidebar = tk.Frame(body, bg=C_PANEL, width=160)
        sidebar.pack(side="right", fill="y")
        sidebar.pack_propagate(False)

        tk.Frame(sidebar, bg=C_GOLD, height=1).pack(fill="x")

        tk.Label(sidebar, text="Session Stats",
                 font=("Segoe UI", 9, "bold"),
                 bg=C_PANEL, fg=C_GOLD).pack(pady=(8, 4))

        tk.Frame(sidebar, bg=C_BORDER, height=1).pack(fill="x", padx=8)

        # Kill / chop counter
        self._stat_action_var = tk.StringVar(
            value="Kills: 0" if self._mode == "combat" else "Chops: 0"
        )
        tk.Label(sidebar, textvariable=self._stat_action_var,
                 font=("Consolas", 9), bg=C_PANEL, fg=C_GREEN,
                 anchor="w").pack(fill="x", padx=12, pady=(6, 0))

        tk.Frame(sidebar, bg=C_BORDER, height=1).pack(fill="x", padx=8, pady=4)
        tk.Label(sidebar, text="XP Gained",
                 font=("Segoe UI", 8), bg=C_PANEL, fg=C_DIM).pack(anchor="w", padx=12)

        self._xp_labels: dict[int, tk.StringVar] = {}
        skills = ([0, 1, 2, 6] if self._mode == "combat" else [7, 6])
        for sk in skills:
            var = tk.StringVar(value=f"{SKILL_NAMES[sk]}: 0")
            self._xp_labels[sk] = var
            tk.Label(sidebar, textvariable=var,
                     font=("Consolas", 9), bg=C_PANEL, fg=C_CYAN,
                     anchor="w").pack(fill="x", padx=12)

        # Dynamic blocks counter (v3.1 — shows how many cliff tiles are known)
        tk.Frame(sidebar, bg=C_BORDER, height=1).pack(fill="x", padx=8, pady=4)
        tk.Label(sidebar, text="Map Learning",
                 font=("Segoe UI", 8), bg=C_PANEL, fg=C_DIM).pack(anchor="w", padx=12)
        self._blocks_var = tk.StringVar(value="Cliff blocks: —")
        tk.Label(sidebar, textvariable=self._blocks_var,
                 font=("Consolas", 9), bg=C_PANEL, fg=C_PURPLE,
                 anchor="w").pack(fill="x", padx=12)
        self._trunc_var = tk.StringVar(value="Truncations: 0")
        tk.Label(sidebar, textvariable=self._trunc_var,
                 font=("Consolas", 9), bg=C_PANEL, fg=C_YELLOW,
                 anchor="w").pack(fill="x", padx=12)
        self._truncations = 0

        # Mode sprite at bottom of sidebar
        spr2 = _load_sprite(sprite_file, 48)
        if spr2:
            self._keep(spr2)
            tk.Label(sidebar, image=spr2, bg=C_PANEL).pack(side="bottom", pady=12)

        # ── Log area ──────────────────────────────────────────────────────────
        log_wrap = tk.Frame(body, bg=C_LOG_BG)
        log_wrap.pack(side="left", fill="both", expand=True)

        self._log_box = tk.Text(
            log_wrap,
            font=("Consolas", 9),
            bg=C_LOG_BG, fg=C_TEXT,
            insertbackground=C_TEXT,
            relief="flat", bd=6,
            state="disabled", wrap="none", cursor="arrow",
        )
        self._log_box.pack(side="left", fill="both", expand=True)

        sb = tk.Scrollbar(log_wrap, orient="vertical",
                          command=self._log_box.yview,
                          bg=C_PANEL, troughcolor=C_LOG_BG, width=10)
        sb.pack(side="right", fill="y")
        self._log_box.configure(yscrollcommand=sb.set)

        # Tag styles
        self._log_box.tag_configure("INFO",    foreground="#7878a0")
        self._log_box.tag_configure("DEBUG",   foreground="#404055")
        self._log_box.tag_configure("WARNING", foreground=C_YELLOW)
        self._log_box.tag_configure("ERROR",   foreground=C_RED)
        self._log_box.tag_configure("CIPHER",  foreground=C_PURPLE)
        self._log_box.tag_configure("XP",      foreground=C_CYAN)
        self._log_box.tag_configure("LEVELUP", foreground=C_GOLD2)
        self._log_box.tag_configure("KILL",    foreground=C_GREEN)
        self._log_box.tag_configure("ATTACK",  foreground=C_ORANGE)
        self._log_box.tag_configure("CHOP",    foreground=C_GREEN)
        self._log_box.tag_configure("DEATH",   foreground=C_RED)
        self._log_box.tag_configure("MOVE",    foreground="#606080")
        self._log_box.tag_configure("PATH",    foreground=C_YELLOW)
        self._log_box.tag_configure("BLOCK",   foreground=C_PURPLE)
        self._log_box.tag_configure("READY",   foreground=C_GOLD)
        self._log_box.tag_configure("CONN",    foreground=C_GREEN)
        self._log_box.tag_configure("HEIGHT",  foreground="#7048a8")

        # ── Status bar ────────────────────────────────────────────────────────
        sbar = tk.Frame(self.root, bg=C_HEADER, pady=3)
        sbar.pack(fill="x", side="bottom")
        self._status_var = tk.StringVar(value="Starting…")
        tk.Label(sbar, textvariable=self._status_var,
                 font=("Segoe UI", 8), bg=C_HEADER, fg=C_DIM,
                 anchor="w").pack(side="left", padx=10)
        tk.Label(sbar, text="EvilBot V3 by Blackberry",
                 font=("Segoe UI", 8), bg=C_HEADER, fg=C_DIM,
                 anchor="e").pack(side="right", padx=10)

        self._poll_log()

    # ── Log helpers ───────────────────────────────────────────────────────────

    def _tag_for(self, line: str) -> str:
        lo = line.lower()
        if "level_up"            in lo: return "LEVELUP"
        if "xp_gain"             in lo: return "XP"
        if "defeated"            in lo: return "KILL"
        if "attacking cow"       in lo: return "ATTACK"
        if "skilling_stop"       in lo: return "CHOP"
        if "died"                in lo: return "DEATH"
        if "entity_death"        in lo: return "DEATH"
        if "respawned"           in lo: return "DEATH"
        if "player died"         in lo: return "DEATH"
        if "cipher active"       in lo: return "CIPHER"
        if "pathfinder ready"    in lo: return "READY"
        if "ready"               in lo: return "READY"
        if "websocket"           in lo: return "CONN"
        if "login_ok"            in lo: return "CONN"
        if "map_change"          in lo: return "CONN"
        if "http login"          in lo: return "CONN"
        if "loaded height"       in lo: return "HEIGHT"
        if "cliff threshold"     in lo: return "HEIGHT"
        if "dynamic block"       in lo: return "BLOCK"
        if "blocking"            in lo: return "BLOCK"
        if "path_truncated"      in lo: return "PATH"
        if "re-pathing"          in lo: return "PATH"
        if "moving to"           in lo: return "MOVE"
        if "walking"             in lo: return "MOVE"
        if "arrived"             in lo: return "MOVE"
        if "movement done"       in lo: return "MOVE"
        if "warning"             in lo: return "WARNING"
        if "error"               in lo: return "ERROR"
        return "INFO"

    def _update_stats(self, line: str):
        """Parse a log line and update sidebar counters."""
        # XP gain
        m = re.search(r"XP_GAIN skill=(\d+) xp=(\d+)", line)
        if m:
            sk, xp = int(m.group(1)), int(m.group(2))
            self._xp[sk] = self._xp.get(sk, 0) + xp
            if sk in self._xp_labels:
                self._xp_labels[sk].set(f"{SKILL_NAMES.get(sk, sk)}: {self._xp[sk]:,}")
            return

        # Kill detected
        if re.search(r"defeated", line, re.I):
            self._kills += 1
            self._stat_action_var.set(f"Kills: {self._kills}")
            self._status_var.set(f"Kill #{self._kills} ↑")
            return

        # Chop / log collected
        if "SKILLING_STOP" in line:
            self._chops += 1
            self._stat_action_var.set(f"Chops: {self._chops}")
            self._status_var.set(f"Chop #{self._chops} ↑")
            return

        # PATH_TRUNCATED counter
        if "PATH_TRUNCATED" in line:
            self._truncations += 1
            self._trunc_var.set(f"Truncations: {self._truncations}")

        # Dynamic blocks count from "Pathfinder ready" line
        m2 = re.search(r"(\d+) dynamic blocks", line)
        if m2:
            self._blocks_var.set(f"Cliff blocks: {m2.group(1)}")

        # Dynamic block added at runtime
        if re.search(r"blocking \(", line, re.I) or re.search(r"dynamic block \(", line, re.I):
            m3 = re.search(r"(\d+) dynamic blocks", line)
            if not m3:
                # Increment from current display
                cur = self._blocks_var.get()
                n_m = re.search(r"(\d+)", cur)
                if n_m:
                    self._blocks_var.set(f"Cliff blocks: {int(n_m.group(1)) + 1}")

        # Status line updates
        if "Attacking" in line:
            self._status_var.set(line.split("INFO")[-1].strip()[:70])
        elif "Moving to" in line:
            self._status_var.set(line.split("Moving to")[-1].strip()[:70])
        elif "Chopping" in line:
            self._status_var.set(line.split("INFO")[-1].strip()[:70])
        elif "Walking to" in line:
            self._status_var.set(line.split("INFO")[-1].strip()[:70])
        elif "Arrived" in line:
            self._status_var.set(line.split("INFO")[-1].strip()[:70])
        elif "Player died" in line:
            self._status_var.set("Player died — walking back…")

    def _append_log(self, line: str):
        self._update_stats(line)
        tag = self._tag_for(line)
        self._log_box.configure(state="normal")
        self._log_box.insert("end", line + "\n", tag)
        self._log_box.see("end")
        self._log_box.configure(state="disabled")

    def _poll_log(self):
        try:
            while True:
                self._append_log(self._log_q.get_nowait())
        except queue.Empty:
            pass
        self.root.after(80, self._poll_log)

    # ── Bot lifecycle ─────────────────────────────────────────────────────────

    def _launch_bot(self):
        import bot as bot_mod
        import pathfinder

        # Attach queue handler to both bot and pathfinder loggers (once)
        if self._handler is None:
            self._handler = _QueueHandler(self._log_q)
            for name in ("bot", "pathfinder"):
                lg = logging.getLogger(name)
                lg.addHandler(self._handler)
                lg.setLevel(logging.DEBUG)

        # Reset session stats
        self._kills       = 0
        self._chops       = 0
        self._truncations = 0
        self._xp.clear()
        for sk, var in self._xp_labels.items():
            var.set(f"{SKILL_NAMES.get(sk, sk)}: 0")
        self._stat_action_var.set(
            "Kills: 0" if self._mode == "combat" else "Chops: 0"
        )
        self._blocks_var.set("Cliff blocks: —")
        self._trunc_var.set("Truncations: 0")

        self._running = True
        self._set_btn_states(running=True)
        self._status_var.set("Connecting…")

        mode = self._mode

        def _thread():
            # Full pathfinder reset so a fresh session reloads everything
            pathfinder._loaded          = False
            pathfinder._tiles_loaded    = False
            pathfinder._heights_loaded  = False
            pathfinder._walls.clear()
            pathfinder._blocked_tiles.clear()
            pathfinder._heights.clear()
            # Dynamic blocks persist across restarts (intentional — cliff memory)
            pathfinder._dynamic_blocked.clear()

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._bot_loop = loop

            b = bot_mod.Bot(
                username    = self._username,
                password    = self._password,
                tree_entity = bot_mod.DEFAULT_TREE_ENTITY,
                tree_x      = bot_mod.DEFAULT_TREE_X,
                tree_y      = bot_mod.DEFAULT_TREE_Y,
                shop_option = 1,
                cow_type    = bot_mod.DEFAULT_COW_TYPE_ID,
                cow_x       = bot_mod.DEFAULT_COW_X,
                cow_y       = bot_mod.DEFAULT_COW_Y,
            )
            try:
                loop.run_until_complete(b.run(mode))
            except (RuntimeError, asyncio.CancelledError):
                pass
            except Exception as exc:
                logging.getLogger("bot").error(f"Bot stopped: {exc}")
            finally:
                self._running = False
                self.root.after(0, lambda: self._set_btn_states(running=False))
                self.root.after(0, lambda: self._status_var.set("Stopped."))

        self._bot_thread = threading.Thread(target=_thread, daemon=True)
        self._bot_thread.start()

    def _on_stop(self):
        if self._bot_loop and self._running:
            self._bot_loop.call_soon_threadsafe(self._bot_loop.stop)
        self._stop_btn.configure(state="disabled", text="Stopping…")
        self._status_var.set("Stopping…")

    def _on_restart(self):
        self._start_btn.configure(state="disabled")
        self._launch_bot()

    def _set_btn_states(self, running: bool):
        if running:
            self._start_btn.configure(state="disabled", bg=C_DIM)
            self._stop_btn.configure(state="normal", bg=C_RED, text="■  Stop")
        else:
            self._start_btn.configure(state="normal", bg="#285028", fg="white",
                                       activebackground="#3a703a")
            self._stop_btn.configure(state="disabled", bg=C_DIM, text="■  Stopped")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    EvilBotApp()
