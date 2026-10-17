"""PDF building blocks (reportlab): page frame with letterhead and footer, styles, tables.

The renderer sits behind small functions so another engine (WeasyPrint, Typst) can replace it.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

FOREST = colors.HexColor("#1f3d2b")
SAGE = colors.HexColor("#d3dfd0")
SAND = colors.HexColor("#f4eee3")
MUTED = colors.HexColor("#5d6b61")
TERRA = colors.HexColor("#c2693e")


def styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "title",
            parent=base["Title"],
            fontName="Times-Roman",
            fontSize=22,
            leading=26,
            textColor=FOREST,
            alignment=0,
            spaceAfter=4 * mm,
        ),
        "h2": ParagraphStyle(
            "h2",
            parent=base["Heading2"],
            fontName="Times-Roman",
            fontSize=13,
            textColor=FOREST,
            spaceBefore=5 * mm,
            spaceAfter=2 * mm,
        ),
        "body": ParagraphStyle(
            "body", parent=base["BodyText"], fontName="Helvetica", fontSize=9.5, leading=13
        ),
        "small": ParagraphStyle(
            "small", parent=base["BodyText"], fontName="Helvetica", fontSize=8, leading=10, textColor=MUTED
        ),
        "right": ParagraphStyle(
            "right",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=9.5,
            leading=13,
            alignment=TA_RIGHT,
        ),
        "address": ParagraphStyle(
            "address", parent=base["BodyText"], fontName="Helvetica", fontSize=10, leading=13
        ),
    }


@dataclass
class Letterhead:
    name: str
    lines: list[str] = field(default_factory=list)
    footer_columns: list[list[str]] = field(default_factory=list)


def money(value: float | None) -> str:
    if value is None:
        return "–"
    s = f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{s} €"


def number(value: float | None, digits: int = 0) -> str:
    if value is None:
        return "–"
    s = f"{value:,.{digits}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return s


def build_pdf(
    letterhead: Letterhead, story_fn: Callable[[dict[str, ParagraphStyle]], list[Any]], title: str
) -> bytes:
    buf = io.BytesIO()
    st = styles()

    def frame(canvas, doc) -> None:
        canvas.saveState()
        w, h = A4
        canvas.setFillColor(FOREST)
        canvas.rect(0, h - 8 * mm, w, 8 * mm, stroke=0, fill=1)
        canvas.setFillColor(FOREST)
        canvas.setFont("Times-Roman", 16)
        canvas.drawString(20 * mm, h - 22 * mm, letterhead.name)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(MUTED)
        for i, line in enumerate(letterhead.lines[:4]):
            canvas.drawRightString(w - 20 * mm, h - 17 * mm - i * 3.6 * mm, line)
        # leaf mark
        canvas.setStrokeColor(TERRA)
        canvas.setLineWidth(1)
        p = canvas.beginPath()
        p.moveTo(14 * mm, h - 24 * mm)
        p.curveTo(15 * mm, h - 19 * mm, 17 * mm, h - 16 * mm, 19 * mm, h - 15 * mm)
        canvas.drawPath(p)
        # footer
        canvas.setStrokeColor(SAGE)
        canvas.line(20 * mm, 22 * mm, w - 20 * mm, 22 * mm)
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(MUTED)
        col_w = (w - 40 * mm) / max(1, len(letterhead.footer_columns))
        for c, col in enumerate(letterhead.footer_columns):
            for i, line in enumerate(col[:4]):
                canvas.drawString(20 * mm + c * col_w, 18 * mm - i * 3.2 * mm, line)
        canvas.drawRightString(w - 20 * mm, 8 * mm, f"Seite {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=34 * mm,
        bottomMargin=30 * mm,
        title=title,
        author=letterhead.name,
    )
    doc.build(story_fn(st), onFirstPage=frame, onLaterPages=frame)
    return buf.getvalue()


def lines_table(
    rows: list[list[Any]], widths: list[float], header: bool = True, total_rows: int = 0
) -> Table:
    t = Table(rows, colWidths=widths, repeatRows=1 if header else 0)
    style = [
        ("FONT", (0, 0), (-1, -1), "Helvetica", 9),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (-1, 0), (-1, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    if header:
        style += [
            ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8.5),
            ("TEXTCOLOR", (0, 0), (-1, 0), MUTED),
            ("LINEBELOW", (0, 0), (-1, 0), 0.6, FOREST),
        ]
    if total_rows:
        style += [
            ("LINEABOVE", (0, -total_rows), (-1, -total_rows), 0.6, FOREST),
            ("FONT", (0, -1), (-1, -1), "Helvetica-Bold", 10),
            ("BACKGROUND", (0, -1), (-1, -1), SAND),
        ]
    t.setStyle(TableStyle(style))
    return t


def address_block(st, lines: list[str]) -> Paragraph:
    return Paragraph("<br/>".join(x for x in lines if x), st["address"])


def spacer(h_mm: float) -> Spacer:
    return Spacer(1, h_mm * mm)
