"""Test helpers: synthetic photos (with an A4 sheet and GPS EXIF data), module switches."""

from __future__ import annotations

import io

from PIL import Image, ImageDraw, ImageFilter


def make_photo(a4: bool = True, blur: bool = False, size=(900, 1200), gps: bool = False) -> bytes:
    img = Image.new("RGB", size, (88, 120, 70))
    draw = ImageDraw.Draw(img)
    # pot and crown
    draw.rectangle([300, 800, 600, 1150], fill=(160, 90, 60))
    draw.ellipse([200, 150, 700, 820], fill=(40, 100, 45))
    for x in range(0, size[0], 37):
        draw.line([(x, 0), (x + 40, size[1])], fill=(70, 110, 60), width=2)
    if a4:
        # A4 sheet 210x297 -> 140 x 198 px, upright, fully visible
        draw.rectangle([380, 560, 520, 758], fill=(250, 250, 248))
    if blur:
        img = img.filter(ImageFilter.GaussianBlur(14))
    out = io.BytesIO()
    if gps:
        exif = Image.Exif()
        exif[0x010F] = "TestKamera"  # Make
        gps_ifd = {1: "N", 2: (48.0, 46.0, 30.0), 3: "E", 4: (9.0, 10.0, 0.0)}
        exif[0x8825] = gps_ifd
        img.save(out, format="JPEG", exif=exif)
    else:
        img.save(out, format="JPEG", quality=90)
    return out.getvalue()


def set_modules(api, **modules: bool) -> None:
    """Switches optional modules of the logged-in tenant (all are off for a new tenant)."""
    for name, on in modules.items():
        api.put("/api/settings", json={"scope": "tenant", "key": f"modules.{name}", "value": on})
