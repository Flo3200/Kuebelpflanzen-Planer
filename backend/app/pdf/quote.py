"""Quote PDF for a pickup order (customer offer of a nursery)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from reportlab.lib.units import mm
from reportlab.platypus import Paragraph

from app.models.core import Tenant
from app.models.orders import Address, Customer, PickupOrder
from app.pdf.base import Letterhead, address_block, build_pdf, lines_table, money, number, spacer


def tenant_letterhead(t: Tenant) -> Letterhead:
    addr = ", ".join(x for x in (t.street, f"{t.postal_code or ''} {t.city or ''}".strip()) if x)
    return Letterhead(
        name=t.legal_name or t.name,
        lines=[x for x in (addr, t.phone, t.email) if x],
        footer_columns=[
            [t.legal_name or t.name, t.street or "", f"{t.postal_code or ''} {t.city or ''}".strip()],
            [f"Tel. {t.phone}" if t.phone else "", t.email or ""],
            [
                f"USt-IdNr. {t.vat_id}" if t.vat_id else "",
                f"Steuernr. {t.tax_number}" if t.tax_number else "",
            ],
            [f"IBAN {t.iban}" if t.iban else ""],
        ],
    )


def quote_lines(estimate: dict[str, Any], include_vat: bool) -> list[dict[str, Any]]:
    """Positions in the basis of the price formula (gross if prices include VAT, else net).
    The last line reconciles minimum price and rounding so the lines add up to the price."""
    price = estimate.get("price") or {}
    comp = price.get("components") or {}
    labour = estimate.get("labour_min") or 0
    plants = len(estimate.get("plants") or [])
    lines = [
        {"text": "Grundpreis Abholung (Anfahrt, Verwaltung)", "amount": comp.get("base_price", 0)},
        {
            "text": f"Arbeitszeit vor Ort, geschätzt {number(labour)} Personenminuten "
            f"(Team aus {estimate.get('team_size')} Personen)",
            "amount": labour * comp.get("rate_per_labour_minute", 0),
        },
        {"text": f"{plants} Pflanzen, Pauschale je Pflanze", "amount": plants * comp.get("per_plant_fee", 0)},
    ]
    if price.get("distance_surcharge"):
        lines.append(
            {
                "text": f"Entfernungszuschlag ({number(estimate.get('distance_km'), 1)} km)",
                "amount": price["distance_surcharge"],
            }
        )
    target = (price.get("gross") if include_vat else price.get("net")) or 0
    diff = round(target - sum(x["amount"] for x in lines), 2)
    if abs(diff) >= 0.01:
        minimum = comp.get("minimum_price") or 0
        text = (
            "Aufschlag auf den Mindestpreis"
            if diff > 0 and abs(target - minimum) < 0.01 + (comp.get("rounding") or 0)
            else "Rundung"
        )
        lines.append({"text": text, "amount": diff})
    return [{**x, "amount": round(x["amount"], 2)} for x in lines]


def render_quote(
    tenant: Tenant,
    customer: Customer,
    address: Address,
    order: PickupOrder,
    estimate: dict[str, Any],
    plants: list[dict[str, Any]],
    number_text: str,
    net: float,
    vat_pct: float,
    gross: float,
    lines: list[dict[str, Any]],
    valid_days: int = 30,
    prices_include_vat: bool = True,
) -> bytes:
    today = date.today()

    def story(st):
        out: list[Any] = []
        out.append(
            address_block(
                st,
                [
                    customer.company or "",
                    customer.name,
                    address.street,
                    f"{address.postal_code} {address.city}",
                ],
            )
        )
        out.append(spacer(10))
        out.append(Paragraph(f"Angebot {number_text}", st["title"]))
        meta = lines_table(
            [
                ["Datum", today.strftime("%d.%m.%Y")],
                ["Auftrag", order.number],
                ["Gültig bis", (today + timedelta(days=valid_days)).strftime("%d.%m.%Y")],
                ["Abholung", _window(order)],
            ],
            [35 * mm, 60 * mm],
            header=False,
        )
        out.append(meta)
        out.append(spacer(4))
        out.append(
            Paragraph(
                f"Guten Tag {customer.name},<br/>vielen Dank für Ihre Anfrage. Gern holen wir Ihre Kübelpflanzen ab und "
                "überwintern sie fachgerecht. Für die Abholung bieten wir Ihnen an:",
                st["body"],
            )
        )
        out.append(spacer(4))
        rows: list[list[Any]] = [
            ["Pos.", "Leistung", "Betrag (brutto)" if prices_include_vat else "Betrag (netto)"]
        ]
        for i, line in enumerate(lines, start=1):
            rows.append([str(i), Paragraph(line["text"], st["body"]), money(line["amount"])])
        vat_amount = gross - net
        if prices_include_vat:
            rows.append(["", f"darin enthaltene Umsatzsteuer {number(vat_pct, 0)} %", money(vat_amount)])
            rows.append(["", "Gesamtbetrag", money(gross)])
            total_rows = 2
        else:
            rows.append(["", "Summe netto", money(net)])
            rows.append(["", f"Umsatzsteuer {number(vat_pct, 0)} %", money(vat_amount)])
            rows.append(["", "Gesamtbetrag", money(gross)])
            total_rows = 3
        out.append(lines_table(rows, [12 * mm, 120 * mm, 38 * mm], total_rows=total_rows))
        out.append(spacer(5))
        out.append(
            Paragraph(
                "Grundlage sind Ihre Angaben und Fotos. Die Arbeitszeit ist geschätzt; weichen Pflanzen oder Weg deutlich "
                "von den Angaben ab, passen wir den Preis nach Rücksprache an. Die Überwinterung wird gesondert berechnet.",
                st["small"],
            )
        )
        if plants:
            out.append(Paragraph("Ihre Pflanzen", st["h2"]))
            prow: list[list[Any]] = [["Nr.", "Pflanze", "Höhe", "Topf", "Gewicht (ca.)"]]
            for p in plants:
                prow.append(
                    [
                        f"#{p['number']}",
                        Paragraph(p.get("display") or "", st["body"]),
                        f"{number(p.get('total_height_cm'))} cm",
                        f"{number(p.get('pot_diameter_cm'))} cm",
                        f"{number(p.get('weight_kg'))} kg",
                    ]
                )
            out.append(lines_table(prow, [15 * mm, 75 * mm, 25 * mm, 25 * mm, 30 * mm]))
        out.append(spacer(8))
        out.append(Paragraph("Wir freuen uns auf Ihren Auftrag.<br/>Mit freundlichen Grüßen", st["body"]))
        out.append(Paragraph(tenant.legal_name or tenant.name, st["body"]))
        return out

    return build_pdf(tenant_letterhead(tenant), story, f"Angebot {number_text}")


def _window(order: PickupOrder) -> str:
    if order.fixed_date:
        return order.fixed_date.strftime("%d.%m.%Y")
    if order.earliest_date and order.latest_date:
        return f"{order.earliest_date.strftime('%d.%m.')} – {order.latest_date.strftime('%d.%m.%Y')}"
    if order.earliest_date:
        return f"ab {order.earliest_date.strftime('%d.%m.%Y')}"
    return "nach Absprache"
