# Lumina Widget

A lightweight, dark, frameless **Windows 11 desktop widget** built with Python +
tkinter. It floats always-on-top, lives in the system tray, and stacks small
collapsible modules with a yellow (`#ffd400`) accent on a near-black, ~85%-opacity
background.

![accent](https://img.shields.io/badge/accent-%23ffd400-ffd400) ![python](https://img.shields.io/badge/python-3.11%2B-blue)

## Modules
1. **Analog clock** — minimal, thin stroke, yellow second hand, no numbers
2. **CPU temperature** — live °C readout + thin progress arc (WMI / LibreHardwareMonitor, falling back to psutil)
3. **Memory usage** — thin bar + percentage and used/total GB
4. **Network activity** — live down/upload rates as scrolling spark lines
5. **Disk I/O** — live read/write rates as scrolling spark lines
6. **GPU** — temp arc + load/memory via `nvidia-smi` (LibreHardwareMonitor fallback); shown only if a GPU is detected
7. **Battery** — percentage + charging state (shown only on laptops)

Each module has a small toggle to collapse/expand it (Disk/GPU/Battery start
collapsed to stay compact). Right-click the widget or click the **⚙** button to
open **Settings** — adjust opacity, refresh interval, and accent color, all
saved to the config. The whole widget is
draggable from anywhere on its body, remembers its position, and polls once per
second.

## Run from source
```bat
pip install -r requirements.txt
pythonw main.py          REM no console window
```
or just double-click **`run_lumina.vbs`** to launch it silently.

The app starts minimized to the **system tray** — left-click the tray icon to
show/hide, or right-click the widget for **Hide / Exit**.

## Run as a real Windows 11 app
Build a standalone, windowed executable (no console, embedded icon):
```bat
build_exe.bat            REM -> dist\Lumina.exe
```
Then double-click `dist\Lumina.exe`, pin it to the taskbar, and optionally have
it start at login:
```bat
install_startup.bat      REM auto-start at login
uninstall_startup.bat    REM undo
```
The process sets a Win11 `AppUserModelID` and per-monitor DPI awareness so it
renders crisply on scaled displays and behaves as its own app.

## Tech stack
- Python 3.11+, tkinter (UI), pystray + Pillow (tray icon)
- psutil (CPU load / network), wmi + pywin32 (CPU temperature on Windows)
- PyInstaller (optional, for the `.exe`)

> CPU temperature is most accurate when [LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor)
> (or OpenHardwareMonitor) is running with its WMI/COM interface enabled. Without
> it the widget falls back to ACPI/psutil and may show `n/a` on some hardware.

## Adding a new module
Subclass `WidgetModule` in `main.py`, implement `build_body()` and `poll()`, then
register it in `App._build_modules()`. The collapsible header, theming, dragging
and the 1-second poll loop are handled for you. See the comment block at the top
of `main.py` for a full example.
