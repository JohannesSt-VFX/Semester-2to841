r"""
================================================================================
 Lumina Widget — a lightweight Windows 11 desktop widget
================================================================================

A dark, frameless, always-on-top floating widget that stacks small modules:
    1. Analog clock   — minimal, thin stroke, yellow second hand, no numbers
    2. CPU temperature — live readout + thin progress arc
    3. Network activity — live up/down rates as scrolling spark lines

--------------------------------------------------------------------------------
HOW TO RUN (quick, from source)
--------------------------------------------------------------------------------
    1. Install Python 3.11+  (https://www.python.org/downloads/)
    2. Install dependencies:
           pip install -r requirements.txt
       (On non-Windows machines `wmi`/`pywin32` will be skipped automatically;
        temperature simply falls back to whatever psutil can provide.)
    3. (Optional) Install the JetBrains Mono font for the intended look:
           https://www.jetbrains.com/lp/mono/
    4. Launch:
           python main.py                 (shows a console window)
           pythonw main.py                (no console — runs like an app)
           run_lumina.vbs                 (double-click; launches silently)

--------------------------------------------------------------------------------
RUN AS A REAL WINDOWS 11 APP (recommended)
--------------------------------------------------------------------------------
    Build a standalone, windowed Lumina.exe (no console, embedded icon):

           build_exe.bat            ->  produces  dist\Lumina.exe

    Then double-click dist\Lumina.exe, pin it to the taskbar/Start, and/or:

           install_startup.bat      ->  launch automatically at login
           uninstall_startup.bat    ->  undo the above

    The process declares a Win11 AppUserModelID and per-monitor DPI awareness,
    so it renders crisply on scaled displays and groups correctly as its own
    app in the tray/taskbar.

--------------------------------------------------------------------------------
USING IT
--------------------------------------------------------------------------------
    The app starts minimized to the system tray. Left-click the tray icon to
    show/hide the widget. Right-click the widget for a "Hide" / "Exit" menu.
    Drag the widget by clicking anywhere on its body; its position is
    remembered between runs in:  ~/.lumina_widget.json

--------------------------------------------------------------------------------
HOW TO ADD A NEW WIDGET MODULE
--------------------------------------------------------------------------------
Every module subclasses `WidgetModule`. To add one:

    class MyModule(WidgetModule):
        title = "MY THING"                 # shown in the collapsible header

        def build_body(self, body):        # build your tk widgets inside `body`
            self.value = tk.Label(body, text="-", **self.value_style())
            self.value.pack()

        def poll(self):                    # called once per second; update UI
            self.value.config(text=str(some_live_value()))

Then register it in `App._build_modules()` by appending an instance to the list.
The collapsible header, dark theme, dragging and 1-second polling are all
handled for you by the framework below.
--------------------------------------------------------------------------------
"""

from __future__ import annotations

import json
import math
import os
import sys
import threading
import time
from collections import deque
from datetime import datetime

import tkinter as tk
import tkinter.font as tkfont

import psutil

# --- Optional dependencies (degrade gracefully when missing) ------------------
try:
    import pystray
    from PIL import Image, ImageDraw
    _HAS_TRAY = True
except Exception:  # pragma: no cover - tray is optional
    _HAS_TRAY = False

# WMI / LibreHardwareMonitor are Windows-only; importing is wrapped so the app
# still runs on Linux/macOS for development.
try:
    import wmi  # type: ignore
    _HAS_WMI = True
except Exception:
    _HAS_WMI = False


# =============================================================================
# Theme / constants
# =============================================================================
BG          = "#0a0a0a"   # near-black background
ACCENT      = "#ffd400"   # yellow accent
FG          = "#e6e6e6"   # primary text
MUTED       = "#6b6b6b"   # dim text / grid strokes
TRACK       = "#222222"   # inactive arc / bar track
OPACITY     = 0.85        # ~85% window opacity
WIDTH       = 220
POLL_MS     = 1000        # poll every 1 second
CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".lumina_widget.json")

FONT_FAMILY = "JetBrains Mono"   # falls back automatically if not installed
APP_ID      = "Lumina.DesktopWidget.1"   # Win11 AppUserModelID (taskbar/tray)


# =============================================================================
# Windows 11 integration (DPI crispness + distinct app identity)
# =============================================================================
def win11_integration() -> None:
    """Make the process behave like a first-class Win11 app.

    - Per-monitor DPI awareness so the widget renders crisply on scaled
      displays instead of being bitmap-stretched and blurry.
    - An explicit AppUserModelID so Windows treats us as one app for the
      tray / notifications / taskbar grouping.
    Safely no-ops on non-Windows platforms.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        # PROCESS_PER_MONITOR_DPI_AWARE = 2
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass


def resource_path(name: str) -> str:
    """Resolve a bundled resource path (works under PyInstaller too)."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


# =============================================================================
# Config persistence (remembers window position)
# =============================================================================
def load_config() -> dict:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def save_config(cfg: dict) -> None:
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2)
    except Exception:
        pass  # never let a config write crash the UI


# =============================================================================
# Temperature provider — tries several Windows / cross-platform sources
# =============================================================================
class TemperatureProvider:
    """Best-effort CPU temperature in degrees Celsius.

    Order of preference:
        1. LibreHardwareMonitor / OpenHardwareMonitor COM bridge (most accurate
           on Windows, requires the helper app running with WMI enabled).
        2. WMI MSAcpi_ThermalZoneTemperature (works on some Windows machines).
        3. psutil.sensors_temperatures() (Linux / some hardware).
    Returns None when no source is available.
    """

    def __init__(self) -> None:
        self._ohm = None        # OpenHardwareMonitor/LibreHardwareMonitor WMI ns
        self._acpi = None       # root\\wmi namespace
        if _HAS_WMI:
            for ns in (r"root\LibreHardwareMonitor", r"root\OpenHardwareMonitor"):
                try:
                    self._ohm = wmi.WMI(namespace=ns)
                    break
                except Exception:
                    self._ohm = None
            try:
                self._acpi = wmi.WMI(namespace=r"root\wmi")
            except Exception:
                self._acpi = None

    def read(self):  # -> float | None
        # 1) LibreHardwareMonitor / OpenHardwareMonitor
        if self._ohm is not None:
            try:
                temps = [
                    s.Value
                    for s in self._ohm.Sensor()
                    if s.SensorType == "Temperature"
                    and "CPU" in (s.Name or "")
                    and s.Value is not None
                ]
                if temps:
                    return max(temps)
            except Exception:
                pass
        # 2) ACPI thermal zone (deci-Kelvin -> Celsius)
        if self._acpi is not None:
            try:
                zones = self._acpi.MSAcpi_ThermalZoneTemperature()
                if zones:
                    return zones[0].CurrentTemperature / 10.0 - 273.15
            except Exception:
                pass
        # 3) psutil (cross-platform)
        try:
            data = psutil.sensors_temperatures()  # not present on Windows
            for key in ("coretemp", "k10temp", "cpu_thermal", "acpitz"):
                if key in data and data[key]:
                    return data[key][0].current
            for entries in data.values():
                if entries:
                    return entries[0].current
        except Exception:
            pass
        return None


# =============================================================================
# Base module — handles the collapsible header + dark styling
# =============================================================================
class WidgetModule:
    """Base class for a stacked, collapsible widget module.

    Subclasses set `title` and implement `build_body()` and `poll()`.
    """

    title = "MODULE"

    def __init__(self, app: "App", parent: tk.Widget) -> None:
        self.app = app
        self.collapsed = app.config.get("collapsed", {}).get(self.title, False)

        self.frame = tk.Frame(parent, bg=BG)
        self.frame.pack(fill="x", padx=12, pady=(2, 6))

        # --- header: small toggle arrow + title -----------------------------
        header = tk.Frame(self.frame, bg=BG)
        header.pack(fill="x")
        self._arrow = tk.Label(
            header, text=self._arrow_char(), fg=ACCENT, bg=BG,
            font=(FONT_FAMILY, 8), cursor="hand2",
        )
        self._arrow.pack(side="left")
        tk.Label(
            header, text=self.title, fg=MUTED, bg=BG,
            font=(FONT_FAMILY, 8, "bold"),
        ).pack(side="left", padx=(4, 0))
        # toggle on the arrow (clicking the title still drags the window)
        self._arrow.bind("<Button-1>", lambda e: self.toggle())

        # --- body -----------------------------------------------------------
        self.body = tk.Frame(self.frame, bg=BG)
        if not self.collapsed:
            self.body.pack(fill="x", pady=(4, 0))
        self.build_body(self.body)

        # let the user drag the window from any non-interactive part
        app.make_draggable(self.frame)
        app.make_draggable(self.body)

    # -- helpers available to subclasses -------------------------------------
    def value_style(self) -> dict:
        return dict(fg=FG, bg=BG, font=(FONT_FAMILY, 11))

    def label_style(self) -> dict:
        return dict(fg=MUTED, bg=BG, font=(FONT_FAMILY, 8))

    # -- collapse handling ---------------------------------------------------
    def _arrow_char(self) -> str:
        return "▸" if self.collapsed else "▾"  # ▸ / ▾

    def toggle(self) -> None:
        self.collapsed = not self.collapsed
        self._arrow.config(text=self._arrow_char())
        if self.collapsed:
            self.body.pack_forget()
        else:
            self.body.pack(fill="x", pady=(4, 0))
        self.app.persist_collapsed(self.title, self.collapsed)
        self.app.fit_to_content()

    # -- to be implemented by subclasses -------------------------------------
    def build_body(self, body: tk.Frame) -> None:  # pragma: no cover
        raise NotImplementedError

    def poll(self) -> None:  # pragma: no cover
        raise NotImplementedError


# =============================================================================
# Module 1 — Analog clock
# =============================================================================
class ClockModule(WidgetModule):
    title = "CLOCK"
    SIZE = 120

    def build_body(self, body: tk.Frame) -> None:
        self.canvas = tk.Canvas(
            body, width=self.SIZE, height=self.SIZE,
            bg=BG, highlightthickness=0, bd=0,
        )
        self.canvas.pack()
        self.app.make_draggable(self.canvas)
        c = self.SIZE / 2
        r = c - 6
        # thin outer ring
        self.canvas.create_oval(c - r, c - r, c + r, c + r, outline=MUTED, width=1)
        # minimal tick marks (no numbers)
        for i in range(12):
            a = math.radians(i * 30)
            x1 = c + (r - 6) * math.sin(a)
            y1 = c - (r - 6) * math.cos(a)
            x2 = c + r * math.sin(a)
            y2 = c - r * math.cos(a)
            self.canvas.create_line(x1, y1, x2, y2, fill=MUTED, width=1)
        self._hands: list[int] = []

    def poll(self) -> None:
        c = self.SIZE / 2
        r = c - 6
        now = datetime.now()
        for h in self._hands:
            self.canvas.delete(h)
        self._hands.clear()

        def hand(frac: float, length: float, color: str, width: int) -> None:
            a = math.radians(frac * 360)
            x = c + length * math.sin(a)
            y = c - length * math.cos(a)
            self._hands.append(
                self.canvas.create_line(c, c, x, y, fill=color, width=width,
                                        capstyle="round")
            )

        sec = now.second + now.microsecond / 1e6
        minute = now.minute + sec / 60
        hour = (now.hour % 12) + minute / 60
        hand(hour / 12, r * 0.5, FG, 2)        # hour
        hand(minute / 60, r * 0.75, FG, 2)     # minute
        hand(sec / 60, r * 0.85, ACCENT, 1)    # second (yellow)
        self._hands.append(
            self.canvas.create_oval(c - 2, c - 2, c + 2, c + 2,
                                    fill=ACCENT, outline="")
        )


# =============================================================================
# Module 2 — CPU temperature (number + thin progress arc)
# =============================================================================
class CpuTempModule(WidgetModule):
    title = "CPU TEMP"
    SIZE = 90
    T_MIN, T_MAX = 20.0, 100.0   # arc range in °C

    def build_body(self, body: tk.Frame) -> None:
        self.provider = TemperatureProvider()
        wrap = tk.Frame(body, bg=BG)
        wrap.pack()
        self.canvas = tk.Canvas(
            wrap, width=self.SIZE, height=self.SIZE,
            bg=BG, highlightthickness=0, bd=0,
        )
        self.canvas.pack(side="left")
        self.app.make_draggable(self.canvas)

        info = tk.Frame(wrap, bg=BG)
        info.pack(side="left", padx=(10, 0))
        self.value_lbl = tk.Label(info, text="--", fg=ACCENT, bg=BG,
                                  font=(FONT_FAMILY, 18, "bold"))
        self.value_lbl.pack(anchor="w")
        tk.Label(info, text="°C", **self.label_style()).pack(anchor="w")
        self.load_lbl = tk.Label(info, text="load --%", **self.label_style())
        self.load_lbl.pack(anchor="w", pady=(6, 0))
        self.app.make_draggable(info)

        pad = 10
        self._box = (pad, pad, self.SIZE - pad, self.SIZE - pad)
        # static background track arc (270° sweep)
        self.canvas.create_arc(*self._box, start=225, extent=-270,
                               style="arc", outline=TRACK, width=4)
        self._arc = None

    def poll(self) -> None:
        temp = self.provider.read()
        if self._arc is not None:
            self.canvas.delete(self._arc)
            self._arc = None
        if temp is None:
            self.value_lbl.config(text="n/a")
        else:
            self.value_lbl.config(text=f"{temp:.0f}")
            frac = (temp - self.T_MIN) / (self.T_MAX - self.T_MIN)
            frac = max(0.0, min(1.0, frac))
            self._arc = self.canvas.create_arc(
                *self._box, start=225, extent=-270 * frac,
                style="arc", outline=ACCENT, width=4,
            )
        try:
            self.load_lbl.config(
                text=f"load {psutil.cpu_percent():>3.0f}%")
        except Exception:
            pass


# =============================================================================
# Module 3 — Network activity (up/down spark lines)
# =============================================================================
class NetworkModule(WidgetModule):
    title = "NETWORK"
    W, H = 184, 26
    HISTORY = W // 2  # number of samples retained

    def build_body(self, body: tk.Frame) -> None:
        self._last = psutil.net_io_counters()
        self._last_t = time.time()
        self.up_hist: deque[float] = deque([0.0] * self.HISTORY, maxlen=self.HISTORY)
        self.down_hist: deque[float] = deque([0.0] * self.HISTORY, maxlen=self.HISTORY)

        self.down_lbl, self.down_canvas = self._row(body, "DN", ACCENT)
        self.up_lbl, self.up_canvas = self._row(body, "UP", FG)

    def _row(self, parent: tk.Frame, tag: str, color: str):
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", pady=2)
        head = tk.Frame(row, bg=BG)
        head.pack(fill="x")
        tk.Label(head, text=tag, fg=color, bg=BG,
                 font=(FONT_FAMILY, 8, "bold")).pack(side="left")
        val = tk.Label(head, text="0.0 KB/s", fg=FG, bg=BG,
                       font=(FONT_FAMILY, 8))
        val.pack(side="right")
        canvas = tk.Canvas(row, width=self.W, height=self.H, bg=BG,
                           highlightthickness=0, bd=0)
        canvas.pack(fill="x")
        self.app.make_draggable(row)
        self.app.make_draggable(canvas)
        return val, canvas

    @staticmethod
    def _fmt(bytes_per_s: float) -> str:
        if bytes_per_s >= 1_000_000:
            return f"{bytes_per_s / 1_048_576:.1f} MB/s"
        return f"{bytes_per_s / 1024:.1f} KB/s"

    def _draw(self, canvas: tk.Canvas, hist: deque[float], color: str) -> None:
        canvas.delete("spark")
        peak = max(hist) or 1.0
        n = len(hist)
        step = self.W / max(1, n - 1)
        pts = []
        for i, v in enumerate(hist):
            x = i * step
            y = self.H - 1 - (v / peak) * (self.H - 2)
            pts.extend((x, y))
        if len(pts) >= 4:
            canvas.create_line(*pts, fill=color, width=1,
                               smooth=True, tags="spark")

    def poll(self) -> None:
        now = psutil.net_io_counters()
        t = time.time()
        dt = max(1e-6, t - self._last_t)
        up_rate = (now.bytes_sent - self._last.bytes_sent) / dt
        down_rate = (now.bytes_recv - self._last.bytes_recv) / dt
        self._last, self._last_t = now, t

        self.up_hist.append(up_rate)
        self.down_hist.append(down_rate)
        self.up_lbl.config(text=self._fmt(up_rate))
        self.down_lbl.config(text=self._fmt(down_rate))
        self._draw(self.up_canvas, self.up_hist, FG)
        self._draw(self.down_canvas, self.down_hist, ACCENT)


# =============================================================================
# Application shell — window, dragging, tray, polling loop
# =============================================================================
class App:
    def __init__(self) -> None:
        win11_integration()
        self.config = load_config()
        self.root = tk.Tk()
        self.root.title("Lumina Widget")
        self.root.configure(bg=BG)
        # use the bundled icon as the window/alt-tab icon when present
        try:
            ico = resource_path("lumina.ico")
            if os.path.exists(ico):
                self.root.iconbitmap(default=ico)
        except Exception:
            pass
        self.root.overrideredirect(True)          # frameless
        self.root.attributes("-topmost", True)     # always on top
        try:
            self.root.attributes("-alpha", OPACITY)  # ~85% opacity
        except tk.TclError:
            pass

        self._ensure_font()

        # restore saved position
        x = self.config.get("x", 80)
        y = self.config.get("y", 80)
        self.root.geometry(f"{WIDTH}x320+{x}+{y}")

        self._build_chrome()
        self.modules: list[WidgetModule] = []
        self._build_modules()

        # right-click context menu (Hide / Exit)
        self.menu = tk.Menu(self.root, tearoff=0, bg=BG, fg=FG,
                            activebackground=ACCENT, activeforeground=BG,
                            bd=0)
        self.menu.add_command(label="Hide", command=self.hide)
        self.menu.add_separator()
        self.menu.add_command(label="Exit", command=self.exit_app)
        self.root.bind("<Button-3>", self._show_menu)

        self.make_draggable(self.root)
        self.root.bind("<Configure>", self._on_configure)

        self.tray = None
        self._visible = True
        self._start_tray()

        self.root.protocol("WM_DELETE_WINDOW", self.hide)
        self.fit_to_content()
        self.hide()                 # start minimized to tray
        self._poll()                # kick off the 1s loop

    # -- window chrome -------------------------------------------------------
    def _ensure_font(self) -> None:
        """Fall back to a generic monospace if JetBrains Mono is absent."""
        global FONT_FAMILY
        available = set(tkfont.families(self.root))
        if FONT_FAMILY not in available:
            for alt in ("Cascadia Mono", "Consolas", "DejaVu Sans Mono",
                        "Courier New", "TkFixedFont"):
                if alt in available:
                    FONT_FAMILY = alt
                    break

    def _build_chrome(self) -> None:
        self.container = tk.Frame(self.root, bg=BG)
        self.container.pack(fill="both", expand=True)

        title = tk.Frame(self.container, bg=BG)
        title.pack(fill="x", padx=12, pady=(10, 4))
        dot = tk.Label(title, text="●", fg=ACCENT, bg=BG,
                       font=(FONT_FAMILY, 8))
        dot.pack(side="left")
        tk.Label(title, text="LUMINA", fg=FG, bg=BG,
                 font=(FONT_FAMILY, 9, "bold")).pack(side="left", padx=(6, 0))
        tk.Label(title, text="✕", fg=MUTED, bg=BG,
                 font=(FONT_FAMILY, 9), cursor="hand2").pack(side="right")
        # the little × hides to tray
        title.winfo_children()[-1].bind("<Button-1>", lambda e: self.hide())
        self.make_draggable(title)
        self.make_draggable(dot)

    def _build_modules(self) -> None:
        # >>> Register new modules here <<<
        for cls in (ClockModule, CpuTempModule, NetworkModule):
            self.modules.append(cls(self, self.container))

    # -- dragging ------------------------------------------------------------
    def make_draggable(self, widget: tk.Widget) -> None:
        widget.bind("<Button-1>", self._drag_start, add="+")
        widget.bind("<B1-Motion>", self._drag_move, add="+")

    def _drag_start(self, event: tk.Event) -> None:
        self._drag_off = (event.x_root - self.root.winfo_x(),
                          event.y_root - self.root.winfo_y())

    def _drag_move(self, event: tk.Event) -> None:
        if not hasattr(self, "_drag_off"):
            return
        x = event.x_root - self._drag_off[0]
        y = event.y_root - self._drag_off[1]
        self.root.geometry(f"+{x}+{y}")

    def _on_configure(self, event: tk.Event) -> None:
        if event.widget is self.root:
            self.config["x"] = self.root.winfo_x()
            self.config["y"] = self.root.winfo_y()
            save_config(self.config)

    def fit_to_content(self) -> None:
        """Resize window height to fit the (possibly collapsed) modules."""
        self.root.update_idletasks()
        h = self.container.winfo_reqheight()
        self.root.geometry(f"{WIDTH}x{h}")

    # -- context menu --------------------------------------------------------
    def _show_menu(self, event: tk.Event) -> None:
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    def persist_collapsed(self, title: str, collapsed: bool) -> None:
        self.config.setdefault("collapsed", {})[title] = collapsed
        save_config(self.config)

    # -- show / hide / exit --------------------------------------------------
    def show(self) -> None:
        self._visible = True
        self.root.deiconify()
        self.root.attributes("-topmost", True)
        self.fit_to_content()

    def hide(self) -> None:
        self._visible = False
        self.root.withdraw()

    def toggle(self) -> None:
        self.hide() if self._visible else self.show()

    def exit_app(self) -> None:
        try:
            if self.tray is not None:
                self.tray.stop()
        except Exception:
            pass
        self.root.quit()
        self.root.destroy()

    # -- system tray (runs in a daemon thread) -------------------------------
    def _start_tray(self) -> None:
        if not _HAS_TRAY:
            # No pystray: keep the window visible so it is still usable.
            self.root.after(200, self.show)
            return

        image = self._tray_image()
        menu = pystray.Menu(
            pystray.MenuItem("Show / Hide",
                             lambda: self.root.after(0, self.toggle),
                             default=True),
            pystray.MenuItem("Exit",
                             lambda: self.root.after(0, self.exit_app)),
        )
        self.tray = pystray.Icon("lumina", image, "Lumina Widget", menu)
        threading.Thread(target=self.tray.run, daemon=True).start()

    @staticmethod
    def _tray_image():
        # prefer the real app icon when it has been generated/bundled
        try:
            ico = resource_path("lumina.ico")
            if os.path.exists(ico):
                return Image.open(ico)
        except Exception:
            pass
        img = Image.new("RGBA", (64, 64), (10, 10, 10, 255))
        d = ImageDraw.Draw(img)
        d.ellipse((10, 10, 54, 54), outline=(255, 212, 0, 255), width=4)
        d.line((32, 32, 32, 16), fill=(255, 212, 0, 255), width=3)
        d.line((32, 32, 44, 38), fill=(230, 230, 230, 255), width=3)
        return img

    # -- polling loop --------------------------------------------------------
    def _poll(self) -> None:
        if self._visible:
            for m in self.modules:
                try:
                    m.poll()
                except Exception:
                    pass  # one bad module must not stall the others
        self.root.after(POLL_MS, self._poll)

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    try:
        App().run()
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
