"""Invoice PDF with the mandatory content of a German invoice (§ 14 Abs. 4 UStG):
full name and address of issuer and recipient, tax number or VAT ID of the issuer, issue date,
consecutive invoice number, quantity and kind of the service, period of service, net amount by
tax rate, tax rate and tax amount (or the note on § 19 UStG for small businesses), gross amount."""

from __future__ import annotations

from datetime import date
from typing import Any

from reportlab.lib.units import mm
from reportlab.platypus import Paragraph

from app.pdf.base import Letterhead, address_block, build_pdf, lines_table, money, number, spacer


def letterhead_for(party: dict[str, Any]) -> Letterhead:
    city = f"{party.get('postal_code') or ''} {party.get('city') or ''}".strip()
    addr = ", ".join(x for x in (party.get("street"), city) if x)
    return Letterhead(
        name=party.get("name") or "",
        lines=[x for x in (addr, party.get("phone"), party.get("email")) if x],
        footer_columns=[
            [party.get("name") or "", party.get("street") or "", city],
            [f"Tel. {party['phone']}" if party.get("phone") else "", party.get("email") or ""],
            [
                f"USt-IdNr. {party['vat_id']}" if party.get("vat_id") else "",
                f"Steuernr. {party['tax_number']}" if party.get("tax_number") else "",
            ],
            [
                f"IBAN {party['iban']}" if party.get("iban") else "",
                f"BIC {party['bic']}" if party.get("bic") else "",
            ],
        ],
    )


def _d(value: date | str | None) -> str:
    if value is None:
        return "–"
    if isinstance(value, str):
        value = date.fromisoformat(value)
    return value.strftime("%d.%m.%Y")


def render_invoice(inv: dict[str, Any]) -> bytes:
    """inv: number, title, issue_date, due_date, period_start, period_end, issuer, recipient, lines
    [{text, quantity, unit, unit_price, amount}], net, vat_pct, vat, gross, small_business, intro,
    reference (e.g. order number), cancels (number of the cancelled invoice)."""
    issuer, recipient = inv["issuer"], inv["recipient"]

    def story(st):
        out: list[Any] = []
        sender = ", ".join(
            x
            for x in (
                issuer.get("name"),
                issuer.get("street"),
                f"{issuer.get('postal_code') or ''} {issuer.get('city') or ''}".strip(),
            )
            if x
        )
        out.append(Paragraph(sender, st["small"]))
        out.append(
            address_block(
                st,
                [
                    recipient.get("name") or "",
                    recipient.get("extra") or "",
                    recipient.get("street") or "",
                    f"{recipient.get('postal_code') or ''} {recipient.get('city') or ''}".strip(),
                ],
            )
        )
        out.append(spacer(10))
        out.append(Paragraph(f"{inv.get('title') or 'Rechnung'} {inv['number']}", st["title"]))
        meta = [["Rechnungsdatum", _d(inv["issue_date"])]]
        if inv.get("period_start") and inv.get("period_end"):
            meta.append(["Leistungszeitraum", f"{_d(inv['period_start'])} – {_d(inv['period_end'])}"])
        elif inv.get("service_date"):
            meta.append(["Leistungsdatum", _d(inv["service_date"])])
        if inv.get("reference"):
            meta.append(["Bezug", inv["reference"]])
        if inv.get("cancels"):
            meta.append(["Storno zu", inv["cancels"]])
        if recipient.get("vat_id"):
            meta.append(["USt-IdNr. Empfänger", recipient["vat_id"]])
        if recipient.get("customer_no"):
            meta.append(["Kundennummer", recipient["customer_no"]])
        out.append(lines_table(meta, [45 * mm, 80 * mm], header=False))
        out.append(spacer(4))
        if inv.get("intro"):
            out.append(Paragraph(inv["intro"], st["body"]))
            out.append(spacer(3))
        rows: list[list[Any]] = [["Pos.", "Leistung", "Menge", "Einzelpreis", "Betrag (netto)"]]
        for i, line in enumerate(inv["lines"], start=1):
            qty = line.get("quantity")
            rows.append(
                [
                    str(i),
                    Paragraph(line["text"], st["body"]),
                    f"{number(qty, 2 if qty and qty % 1 else 0)} {line.get('unit') or ''}".strip()
                    if qty is not None
                    else "",
                    money(line["unit_price"]) if line.get("unit_price") is not None else "",
                    money(line["amount"]),
                ]
            )
        rows.append(["", "Summe netto", "", "", money(inv["net"])])
        if inv.get("small_business"):
            rows.append(["", "Umsatzsteuer", "", "", money(0)])
        else:
            rows.append(["", f"Umsatzsteuer {number(inv['vat_pct'], 0)} %", "", "", money(inv["vat"])])
        rows.append(["", "Rechnungsbetrag", "", "", money(inv["gross"])])
        out.append(lines_table(rows, [12 * mm, 85 * mm, 22 * mm, 25 * mm, 26 * mm], total_rows=3))
        out.append(spacer(5))
        if inv.get("small_business"):
            out.append(
                Paragraph(
                    "Gemäß § 19 UStG wird keine Umsatzsteuer berechnet (Kleinunternehmerregelung).",
                    st["body"],
                )
            )
        if inv["gross"] > 0:
            due = f"bis zum {_d(inv['due_date'])}" if inv.get("due_date") else "sofort"
            pay = f"Bitte überweisen Sie den Rechnungsbetrag {due}"
            if issuer.get("iban"):
                pay += f" auf das Konto IBAN {issuer['iban']}"
            pay += f" unter Angabe der Rechnungsnummer {inv['number']}."
            out.append(Paragraph(pay, st["body"]))
        elif inv["gross"] < 0:
            out.append(Paragraph("Der Betrag wird Ihnen gutgeschrieben.", st["body"]))
        if inv.get("note"):
            out.append(spacer(3))
            out.append(Paragraph(inv["note"], st["small"]))
        tax_line = " · ".join(
            x
            for x in (
                f"Steuernummer {issuer['tax_number']}" if issuer.get("tax_number") else "",
                f"USt-IdNr. {issuer['vat_id']}" if issuer.get("vat_id") else "",
            )
            if x
        )
        if tax_line:
            out.append(spacer(3))
            out.append(Paragraph(tax_line, st["small"]))
        return out

    return build_pdf(letterhead_for(issuer), story, f"{inv.get('title') or 'Rechnung'} {inv['number']}")
