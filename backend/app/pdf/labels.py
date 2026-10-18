"""QR labels for plants (optional module): A4 sheet with 3 × 8 labels (70 × 37 mm).

The code holds "KP1:<plant id>"; the driver app scans it when loading and confirms the place.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from reportlab.graphics import renderPDF
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from app.pdf.base import FOREST, MUTED

COLS, ROWS = 3, 8
LABEL_W, LABEL_H = 70 * mm, 37 * mm
QR_PREFIX = "KP1:"


@dataclass
class Label:
    plant_id: str
    number: int
    name: str
    customer: str
    order_number: str
    extra: str = ""


def qr_text(plant_id: str) -> str:
    return f"{QR_PREFIX}{plant_id}"


def _fit(c: canvas.Canvas, text: str, font: str, size: float, width: float) -> str:
    while text and c.stringWidth(text, font, size) > width:
        text = text[:-2] + "…" if len(text) > 2 else ""
    return text


def labels_pdf(labels: list[Label], title: str = "") -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle(title or "Pflanzenetiketten")
    page_w, page_h = A4
    margin_x = (page_w - COLS * LABEL_W) / 2
    margin_y = (page_h - ROWS * LABEL_H) / 2
    for i, lab in enumerate(labels):
        if i and i % (COLS * ROWS) == 0:
            c.showPage()
        k = i % (COLS * ROWS)
        col, row = k % COLS, k // COLS
        x = margin_x + col * LABEL_W
        y = page_h - margin_y - (row + 1) * LABEL_H
        c.setStrokeColorRGB(0.85, 0.85, 0.85)
        c.setLineWidth(0.3)
        c.rect(x, y, LABEL_W, LABEL_H)
        size = LABEL_H - 8 * mm
        widget = QrCodeWidget(qr_text(lab.plant_id), barLevel="M")
        b = widget.getBounds()
        d = Drawing(size, size, transform=[size / (b[2] - b[0]), 0, 0, size / (b[3] - b[1]), 0, 0])
        d.add(widget)
        renderPDF.draw(d, c, x + 3 * mm, y + 4 * mm)
        tx = x + size + 6 * mm
        tw = LABEL_W - size - 9 * mm
        c.setFillColor(FOREST)
        c.setFont("Helvetica-Bold", 22)
        c.drawString(tx, y + LABEL_H - 12 * mm, f"#{lab.number}")
        c.setFont("Helvetica-Bold", 9)
        c.drawString(tx, y + LABEL_H - 18 * mm, _fit(c, lab.name, "Helvetica-Bold", 9, tw))
        c.setFillColor(MUTED)
        c.setFont("Helvetica", 8)
        c.drawString(tx, y + LABEL_H - 23 * mm, _fit(c, lab.customer, "Helvetica", 8, tw))
        c.drawString(tx, y + LABEL_H - 27 * mm, _fit(c, lab.order_number, "Helvetica", 8, tw))
        if lab.extra:
            c.drawString(tx, y + LABEL_H - 31 * mm, _fit(c, lab.extra, "Helvetica", 7, tw))
    if not labels:
        c.setFont("Helvetica", 12)
        c.drawString(30 * mm, page_h - 40 * mm, "Keine Pflanzen.")
    c.showPage()
    c.save()
    return buf.getvalue()
