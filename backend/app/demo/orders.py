"""Demo customers, pickup orders, plants and access paths with realistic distributions."""

from __future__ import annotations

import math
import random
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.numbering import next_number
from app.demo.generator import step
from app.models.core import Tenant
from app.models.masterdata import Species
from app.models.orders import AccessPath, Address, Customer, Draft, PathSegment, PickupOrder, Plant
from app.settings.service import SettingsResolver
from app.timemodel.plantfill import complete_plant

CITIES = [
    ("Stuttgart-Degerloch", "70597", 48.7476, 9.1700),
    ("Stuttgart-Vaihingen", "70563", 48.7290, 9.1080),
    ("Stuttgart-Mitte", "70173", 48.7758, 9.1829),
    ("Stuttgart-West", "70197", 48.7700, 9.1550),
    ("Stuttgart-Bad Cannstatt", "70372", 48.8050, 9.2140),
    ("Stuttgart-Möhringen", "70567", 48.7240, 9.1500),
    ("Esslingen am Neckar", "73728", 48.7400, 9.3100),
    ("Ostfildern", "73760", 48.7230, 9.2620),
    ("Fellbach", "70734", 48.8090, 9.2760),
    ("Leinfelden-Echterdingen", "70771", 48.6930, 9.1430),
    ("Filderstadt", "70794", 48.6650, 9.2190),
    ("Ludwigsburg", "71634", 48.8970, 9.1920),
    ("Leonberg", "71229", 48.8000, 9.0140),
    ("Böblingen", "71032", 48.6850, 9.0110),
    ("Waiblingen", "71332", 48.8300, 9.3170),
    ("Kornwestheim", "70806", 48.8610, 9.1850),
    ("Gerlingen", "70839", 48.7990, 9.0640),
    ("Denkendorf", "73770", 48.6960, 9.3170),
    ("Plochingen", "73207", 48.7120, 9.4180),
    ("Nürtingen", "72622", 48.6260, 9.3400),
]
STREETS = [
    "Rosenweg",
    "Lindenstraße",
    "Am Weinberg",
    "Gartenstraße",
    "Schillerstraße",
    "Birkenweg",
    "Kirchgasse",
    "Hölderlinweg",
    "Panoramastraße",
    "Uhlandstraße",
    "Im Wiesengrund",
    "Kelterstraße",
    "Mörikeweg",
    "Sonnenhalde",
    "Eichendorffstraße",
    "Talstraße",
    "Hauptstraße",
    "Feldbergstraße",
    "Kastanienallee",
    "Am Hang",
]
FIRST = [
    "Petra",
    "Klaus",
    "Sabine",
    "Thomas",
    "Monika",
    "Andreas",
    "Ute",
    "Michael",
    "Gabi",
    "Stefan",
    "Birgit",
    "Frank",
    "Heike",
    "Jürgen",
    "Anja",
    "Markus",
    "Claudia",
    "Ralf",
    "Susanne",
    "Bernd",
    "Katrin",
    "Dirk",
    "Ayşe",
    "Murat",
    "Giulia",
    "Marco",
    "Olga",
    "Ivan",
    "Fatima",
    "Yusuf",
]
LAST = [
    "Sommer",
    "Fischer",
    "Weber",
    "Wagner",
    "Becker",
    "Schulz",
    "Hoffmann",
    "Koch",
    "Richter",
    "Klein",
    "Wolf",
    "Schröder",
    "Neumann",
    "Schwarz",
    "Zimmermann",
    "Braun",
    "Krüger",
    "Hofmann",
    "Hartmann",
    "Lange",
    "Schmitt",
    "Werner",
    "Krause",
    "Meier",
    "Lehmann",
    "Schmid",
    "Öztürk",
    "Rossi",
    "Petrov",
    "Haddad",
]
SPECIES_WEIGHTS = {
    "Olivenbaum": 18,
    "Oleander": 15,
    "Zitronenbaum": 7,
    "Orangenbaum": 4,
    "Kumquat": 4,
    "Lorbeer": 8,
    "Hanfpalme": 6,
    "Schmucklilie": 6,
    "Bougainvillea": 4,
    "Engelstrompete": 5,
    "Feigenbaum": 4,
    "Hibiskus": 4,
    "Enzianstrauch": 3,
    "Granatapfel": 2,
    "Agave": 2,
    "Palmlilie": 2,
    "Kanarische Dattelpalme": 2,
    "Wandelröschen": 2,
    "Fuchsie": 2,
    "Bleiwurz": 1,
    "Japanische Faserbanane": 1,
    "Kamelie": 2,
    "Myrte": 1,
    "Zylinderputzer": 1,
    "Strelitzie": 1,
}
MATERIALS = [
    ("plastic", 35),
    ("terracotta", 30),
    ("glazed", 10),
    ("fiberglass", 10),
    ("wood", 5),
    ("stone", 5),
    ("concrete", 5),
]

DRAFT_MESSAGES = [
    "Guten Tag, wir hätten gern wieder unsere drei Zitronenbäumchen (ca. 1,20 m hoch, Töpfe 40 cm) und einen großen "
    "Olivenbaum, etwa 2,20 m hoch, Kübel 80 cm, zur Überwinterung abgeholt. Die Pflanzen stehen im Garten hinterm Haus, "
    "ca. 25 m bis zur Straße über einen Kiesweg. Am besten Anfang Oktober.\n\nViele Grüße\nKlaus Becker\n"
    "Uhlandstraße 7, 70771 Leinfelden-Echterdingen\nTel. 0711 7654321",
    "Hallo, ich bin Giulia Rossi aus Fellbach. Auf meinem Balkon im 2. Stock stehen zwei Oleander und eine Bougainvillea. "
    "Aufzug gibt es keinen. Mail: giulia.rossi@example.com. Abholung bitte bis zum 25.10.",
    "Sprachnachricht (abgetippt): Ja hallo, hier ist Familie Krüger, wir haben eine Hanfpalme, die ist schon so 2,5 m "
    "hoch, und vier Schmucklilien. Steht alles auf der Terrasse, ebenerdig, kein Problem. Rufen Sie mich an: 0170 1234567.",
]


def _weighted(rng: random.Random, items: list[tuple[Any, float]]) -> Any:
    total = sum(w for _, w in items)
    r = rng.uniform(0, total)
    acc = 0.0
    for item, w in items:
        acc += w
        if r <= acc:
            return item
    return items[-1][0]


def _around(rng: random.Random, lat: float, lon: float, km: float) -> tuple[float, float]:
    r = km * math.sqrt(rng.random())
    a = rng.uniform(0, 2 * math.pi)
    return lat + (r * math.cos(a)) / 111.0, lon + (r * math.sin(a)) / (111.0 * math.cos(math.radians(lat)))


def _path_segments(rng: random.Random) -> tuple[str, list[dict[str, Any]], float | None]:
    kind = _weighted(
        rng,
        [
            ("curb", 35),
            ("garden", 25),
            ("upstairs", 15),
            ("elevator", 10),
            ("through_house", 10),
            ("roof", 5),
        ],
    )
    if kind == "curb":
        return (
            "Einfahrt",
            [{"kind": "flat", "length_m": round(rng.uniform(3, 15), 1), "surface": "paved"}],
            None,
        )
    if kind == "garden":
        segs = [
            {
                "kind": "flat",
                "length_m": round(rng.uniform(12, 40), 1),
                "surface": rng.choice(["gravel", "lawn", "paved"]),
            }
        ]
        if rng.random() < 0.5:
            n = rng.randint(3, 8)
            segs.append(
                {
                    "kind": "stairs",
                    "length_m": round(n * 0.32, 1),
                    "steps": n,
                    "height_diff_m": round(n * 0.16, 2),
                    "min_width_cm": rng.choice([100, 120, 150]),
                }
            )
        segs.append({"kind": "flat", "length_m": round(rng.uniform(3, 10), 1), "surface": "paved"})
        return "Garten", segs, None
    if kind == "upstairs":
        floor = rng.randint(1, 3)
        n = floor * 18
        return (
            f"{floor}. OG ohne Aufzug",
            [
                {"kind": "door", "length_m": 4, "doors": 1, "min_width_cm": rng.choice([80, 85, 90])},
                {
                    "kind": "stairs",
                    "length_m": round(n * 0.3, 1),
                    "steps": n,
                    "height_diff_m": round(floor * 2.9, 1),
                    "min_width_cm": rng.choice([90, 100, 110]),
                },
                {"kind": "flat", "length_m": round(rng.uniform(5, 15), 1), "surface": "paved", "doors": 1},
            ],
            None,
        )
    if kind == "elevator":
        return (
            "Aufzug",
            [
                {
                    "kind": "flat",
                    "length_m": round(rng.uniform(5, 12), 1),
                    "surface": "tiles",
                    "doors": 2,
                    "min_width_cm": 90,
                },
                {
                    "kind": "elevator",
                    "length_m": 2,
                    "elevator": True,
                    "height_diff_m": round(rng.randint(2, 6) * 2.9, 1),
                    "min_width_cm": rng.choice([80, 90, 110]),
                },
                {"kind": "flat", "length_m": round(rng.uniform(8, 20), 1), "surface": "paved"},
            ],
            None,
        )
    if kind == "through_house":
        return (
            "Durchs Haus",
            [
                {"kind": "flat", "length_m": round(rng.uniform(5, 12), 1), "surface": "wood"},
                {"kind": "narrow", "length_m": 6, "doors": 2, "min_width_cm": rng.choice([72, 78, 85])},
                {"kind": "stairs", "length_m": 1.5, "steps": rng.randint(2, 5), "height_diff_m": 0.6},
                {"kind": "flat", "length_m": round(rng.uniform(4, 10), 1), "surface": "paved"},
            ],
            None,
        )
    n = rng.randint(55, 80)
    return (
        "Dachterrasse",
        [
            {"kind": "flat", "length_m": round(rng.uniform(5, 12), 1), "surface": "tiles", "doors": 1},
            {
                "kind": "stairs",
                "length_m": round(n * 0.3, 1),
                "steps": n,
                "height_diff_m": round(n * 0.17, 1),
                "min_width_cm": 95,
            },
            {"kind": "flat", "length_m": round(rng.uniform(5, 12), 1), "surface": "paved"},
        ],
        round(rng.uniform(20, 45)),
    )


@step
def customers_and_orders(
    db: Session, tenant: Tenant, rng: random.Random, options, report: dict[str, Any], spec
) -> None:
    resolver = SettingsResolver(db, tenant.id)
    species_by_name = {s.name: s for s in db.scalars(select(Species).where(Species.tenant_id.is_(None)))}
    species_items = [(species_by_name[n], w) for n, w in SPECIES_WEIGHTS.items() if n in species_by_name]
    season = date.today().year if date.today().month >= 8 else date.today().year - 1
    region = spec["region"]
    cities = [
        c
        for c in CITIES
        if math.dist((c[2], c[3]), (region["lat"], region["lon"])) * 111 < region["radius_km"] + 8
    ]
    n_plants = 0
    for i in range(options.orders_per_tenant):
        first, last = rng.choice(FIRST), rng.choice(LAST)
        name = f"{first} {last}" if rng.random() < 0.8 else f"Familie {last}"
        customer = Customer(
            tenant_id=tenant.id,
            name=name,
            email=f"{first.lower()}.{last.lower()}{i}@example.com".replace("ş", "s")
            .replace("ö", "oe")
            .replace("ü", "ue")
            .replace("ä", "ae"),
            phone=f"0711 {rng.randint(100000, 9999999)}",
            consent_photos=rng.random() < 0.7,
            source="demo",
        )
        db.add(customer)
        db.flush()
        city, plz, clat, clon = rng.choice(cities)
        lat, lon = _around(rng, clat, clon, 2.2)
        address = Address(
            tenant_id=tenant.id,
            customer_id=customer.id,
            street=f"{rng.choice(STREETS)} {rng.randint(1, 120)}",
            postal_code=plz,
            city=city,
            lat=round(lat, 6),
            lon=round(lon, 6),
            geocode_source="demo",
            parking_notes=rng.choice(
                [None, None, "Halteverbot vor dem Haus, Einfahrt nutzen", "Parken im Hof möglich"]
            ),
        )
        db.add(address)
        db.flush()
        status = _weighted(rng, [("confirmed", 85), ("draft", 10), ("cancelled", 5)])
        earliest = date(season, 10, 1) + timedelta(days=rng.randint(0, 24))
        order = PickupOrder(
            tenant_id=tenant.id,
            customer_id=customer.id,
            address_id=address.id,
            season=season,
            direction="pickup",
            status=status,
            earliest_date=earliest,
            latest_date=earliest + timedelta(days=rng.randint(7, 21)),
            source="demo",
            priority=0,
            number=f"A-{season}-{next_number(db, tenant.id, f'order-{season}'):04d}",
            time_windows=[],
        )
        if rng.random() < 0.2:
            order.time_windows = (
                [{"from": "08:00", "to": "12:00"}]
                if rng.random() < 0.5
                else [{"from": "13:00", "to": "17:00"}]
            )
        db.add(order)
        db.flush()
        path_name, segments, confirmed = _path_segments(rng)
        path = AccessPath(
            tenant_id=tenant.id,
            order_id=order.id,
            name=path_name,
            length_confirmed_m=confirmed,
            confidence={},
        )
        db.add(path)
        db.flush()
        for pos, seg in enumerate(segments):
            db.add(PathSegment(tenant_id=tenant.id, path_id=path.id, position=pos, **seg))
        count = _weighted(rng, [(1, 30), (2, 25), (3, 17), (rng.randint(4, 6), 20), (rng.randint(7, 15), 8)])
        for _ in range(count):
            sp = _weighted(rng, species_items)
            d = max(20.0, min(75.0, rng.lognormvariate(math.log(36), 0.28)))
            shape = "square" if rng.random() < 0.2 else "round"
            height = max(40.0, (sp.typical_height_cm or 140) * rng.lognormvariate(0, 0.3))
            plant = Plant(
                tenant_id=tenant.id,
                order_id=order.id,
                number=next_number(db, tenant.id, "plant"),
                species_id=sp.id,
                species_name=sp.name,
                species_source="ai",
                access_path_id=path.id,
                pot_shape=shape,
                pot_diameter_cm=round(d) if shape == "round" else None,
                pot_length_cm=round(d) if shape == "square" else None,
                pot_width_cm=round(d) if shape == "square" else None,
                pot_height_cm=round(d * rng.uniform(0.8, 1.0)),
                pot_material=_weighted(rng, MATERIALS),
                total_height_cm=round(height),
                crown_width_cm=round(d * rng.uniform(1.1, 2.6)),
                estimated_fields=[],
                field_confidence={},
                required_equipment=[],
                incompatible_with=[],
                label=None,
            )
            db.add(plant)
            db.flush()
            complete_plant(db, plant, resolver, sp)
            if rng.random() < 0.12:
                plant.weight_measured_kg = round(plant.weight_kg * rng.lognormvariate(0.08, 0.15), 1)
            n_plants += 1
    db.flush()
    # a few unprocessed messages in the inbox
    for text in DRAFT_MESSAGES:
        db.add(
            Draft(
                tenant_id=tenant.id,
                source_kind="email",
                source_text=text,
                status="processing",
                created_via="demo",
            )
        )
    db.flush()
    from app.ai.intake import process_draft

    for d in db.scalars(select(Draft).where(Draft.tenant_id == tenant.id, Draft.status == "processing")):
        process_draft(db, tenant.id, d.id)
    report["orders"] = options.orders_per_tenant
    report["plants"] = n_plants
    report["drafts"] = len(DRAFT_MESSAGES)
