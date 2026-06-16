"""Generate lumina.ico (the app/tray icon) from Pillow.

Run once before building the .exe:  python make_icon.py
Produces a multi-resolution Windows icon used by build_exe.bat and at runtime.
"""
from PIL import Image, ImageDraw

BG = (10, 10, 10, 255)
ACCENT = (255, 212, 0, 255)
FG = (230, 230, 230, 255)


def render(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), BG)
    d = ImageDraw.Draw(img)
    s = size / 64.0
    # clock-style mark: ring + two hands, yellow accent
    d.ellipse((10 * s, 10 * s, 54 * s, 54 * s), outline=ACCENT, width=max(1, int(4 * s)))
    d.line((32 * s, 32 * s, 32 * s, 16 * s), fill=ACCENT, width=max(1, int(3 * s)))
    d.line((32 * s, 32 * s, 44 * s, 38 * s), fill=FG, width=max(1, int(3 * s)))
    return img


def main() -> None:
    sizes = [16, 24, 32, 48, 64, 128, 256]
    base = render(256)
    base.save("lumina.ico", sizes=[(s, s) for s in sizes])
    print("Wrote lumina.ico")


if __name__ == "__main__":
    main()
