"""Local image checks without AI: sharpness, exposure and detection of an A4 reference sheet.

The A4 sheet (21.0 × 29.7 cm) gives the scale in cm per pixel. Detection: bright, low-saturation
connected region that fills its bounding box and has an aspect ratio near √2.
"""

from __future__ import annotations

import io
from typing import Any

import numpy as np
from PIL import Image
from scipy import ndimage

A4_RATIO = 29.7 / 21.0


def analyse(data: bytes) -> dict[str, Any]:
    with Image.open(io.BytesIO(data)) as img:
        img = img.convert("RGB")
        scale = 640 / max(img.size)
        small = (
            img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))))
            if scale < 1
            else img
        )
        rgb = np.asarray(small, dtype=np.float32) / 255.0
        full_w, full_h = img.size
    gray = rgb.mean(axis=2)
    lap = ndimage.laplace(gray)
    sharpness = float(lap.var() * 1000)
    brightness = float(gray.mean())
    dark_clip = float((gray < 0.03).mean())
    bright_clip = float((gray > 0.97).mean())
    result: dict[str, Any] = {
        "sharpness": round(sharpness, 3),
        "brightness": round(brightness, 3),
        "dark_clip": round(dark_clip, 4),
        "bright_clip": round(bright_clip, 4),
        "sharp": sharpness > 0.6,
        "exposure_ok": 0.15 < brightness < 0.85 and dark_clip < 0.25 and bright_clip < 0.25,
    }
    result["a4"] = detect_a4(rgb, full_w / rgb.shape[1])
    return result


def detect_a4(rgb: np.ndarray, px_scale: float) -> dict[str, Any]:
    """Find the best A4 candidate. px_scale converts small-image pixels to original pixels."""
    mx = rgb.max(axis=2)
    mn = rgb.min(axis=2)
    saturation = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0)
    white = (mx > 0.72) & (saturation < 0.18)
    white = ndimage.binary_opening(white, iterations=1)
    labels, n = ndimage.label(white)
    if n == 0:
        return {"detected": False, "confidence": 0.0}
    best: dict[str, Any] = {"detected": False, "confidence": 0.0}
    total = rgb.shape[0] * rgb.shape[1]
    for idx, sl in enumerate(ndimage.find_objects(labels), start=1):
        if sl is None:
            continue
        h = sl[0].stop - sl[0].start
        w = sl[1].stop - sl[1].start
        area = int((labels[sl] == idx).sum())
        if area < total * 0.004 or area > total * 0.6:
            continue
        fill = area / max(1, w * h)
        long_side, short_side = max(w, h), min(w, h)
        ratio = long_side / max(1, short_side)
        ratio_score = max(0.0, 1 - abs(ratio - A4_RATIO) / 0.35)
        fill_score = max(0.0, (fill - 0.6) / 0.4)
        conf = ratio_score * 0.6 + fill_score * 0.4
        if conf > best["confidence"]:
            long_px = long_side * px_scale
            best = {
                "detected": conf >= 0.55,
                "confidence": round(conf, 3),
                "bbox": [
                    int(sl[1].start * px_scale),
                    int(sl[0].start * px_scale),
                    int(w * px_scale),
                    int(h * px_scale),
                ],
                "cm_per_px": round(29.7 / long_px, 5) if long_px else None,
                "fully_visible": sl[0].start > 0
                and sl[1].start > 0
                and sl[0].stop < rgb.shape[0]
                and sl[1].stop < rgb.shape[1],
            }
    return best
