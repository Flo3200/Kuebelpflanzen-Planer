"""Demo resources: staff, vehicles with shelves, equipment, storage areas, availability."""

from __future__ import annotations

import random
from datetime import date, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.core.security import hash_password, pin_lookup
from app.demo.generator import demo_actor, step
from app.models.core import Tenant, User
from app.models.masterdata import (
    Availability,
    Equipment,
    StaffMember,
    StorageArea,
    Team,
    Vehicle,
    VehicleShelf,
)
from app.settings.service import set_value

FIRST = [
    "Ali",
    "Mara",
    "Jonas",
    "Lea",
    "Tobias",
    "Sven",
    "Nina",
    "Kerem",
    "Paul",
    "Elif",
    "Lukas",
    "Marta",
    "Ben",
    "Hannah",
    "Jan",
    "Svenja",
    "Dario",
    "Ole",
    "Ida",
    "Milan",
]
LAST = [
    "Kaya",
    "Berger",
    "Schuster",
    "Wolf",
    "Krämer",
    "Neumann",
    "Yilmaz",
    "Hartmann",
    "Brandt",
    "Lorenz",
    "Vogel",
    "Peters",
    "Keller",
    "Graf",
    "Seidel",
    "Roth",
    "Winter",
    "Haas",
    "Frank",
    "Simon",
]


@step
def staff_and_fleet(
    db: Session, tenant: Tenant, rng: random.Random, options, report: dict[str, Any], spec
) -> None:
    actor = demo_actor(tenant.id)
    staff: list[StaffMember] = []
    for i in range(options.staff_per_tenant):
        name = (
            f"{FIRST[(i * 7 + len(tenant.slug)) % len(FIRST)]} {LAST[(i * 3 + len(tenant.slug)) % len(LAST)]}"
        )
        licences = ["B"]
        if rng.random() < 0.55:
            licences.append("BE")
        if rng.random() < 0.35:
            licences += ["C1", "C1E"] if "BE" in licences else ["C1"]
        s = StaffMember(
            tenant_id=tenant.id,
            name=name,
            short_name=name.split()[0][:3].upper(),
            licences=licences,
            qualifications=(["Treppensteiger"] if rng.random() < 0.3 else []),
            active=True,
            color=f"#{rng.randint(0x30, 0xA0):02x}{rng.randint(0x60, 0xB0):02x}{rng.randint(0x30, 0x90):02x}",
        )
        db.add(s)
        staff.append(s)
    db.flush()
    # individual factors and wages (object level of the settings hierarchy)
    for s in staff:
        if rng.random() < 0.3:
            set_value(
                db,
                actor,
                scope="staff",
                key="staff.solo_carry_kg",
                value=rng.choice([20, 30, 35]),
                tenant_id=tenant.id,
                object_id=s.id,
            )
        if rng.random() < 0.5:
            set_value(
                db,
                actor,
                scope="staff",
                key="staff.hourly_wage",
                value=round(rng.uniform(14.5, 21), 2),
                tenant_id=tenant.id,
                object_id=s.id,
            )
    # driver accounts with PIN for the first three people
    for i, s in enumerate(staff[:3]):
        pin = f"{1000 + i * 1111}"
        db.add(
            User(
                tenant_id=tenant.id,
                name=s.name,
                role="driver",
                staff_member_id=s.id,
                pin_hash=hash_password(pin),
                pin_lookup=pin_lookup(tenant.slug, pin),
                extra_permissions=[],
                revoked_permissions=[],
            )
        )
    report["driver_pins"] = {s.name: f"{1000 + i * 1111}" for i, s in enumerate(staff[:3])}

    sprinter = Vehicle(
        tenant_id=tenant.id,
        name="Sprinter Hochdach",
        plate=f"S-{tenant.slug[:2].upper()} 101",
        kind="van",
        required_licence="B",
        seats=3,
        cargo_length_cm=430,
        cargo_width_cm=178,
        cargo_height_cm=194,
        payload_kg=1150,
        door_width_cm=156,
        door_height_cm=184,
        loading_edge_cm=62,
        wheel_arch_x_cm=245,
        wheel_arch_length_cm=95,
        wheel_arch_width_cm=20,
        wheel_arch_height_cm=32,
        front_axle_x_cm=-80,
        rear_axle_x_cm=290,
        max_front_axle_extra_kg=500,
        max_rear_axle_extra_kg=1000,
        can_tow=True,
        max_trailer_kg=2500,
    )
    crafter = Vehicle(
        tenant_id=tenant.id,
        name="Transporter klein",
        plate=f"S-{tenant.slug[:2].upper()} 102",
        kind="van",
        required_licence="B",
        seats=3,
        cargo_length_cm=340,
        cargo_width_cm=170,
        cargo_height_cm=172,
        payload_kg=950,
        door_width_cm=150,
        door_height_cm=165,
        loading_edge_cm=58,
        wheel_arch_x_cm=200,
        wheel_arch_length_cm=90,
        wheel_arch_width_cm=20,
        wheel_arch_height_cm=30,
        front_axle_x_cm=-75,
        rear_axle_x_cm=240,
        max_front_axle_extra_kg=450,
        max_rear_axle_extra_kg=850,
        can_tow=True,
        max_trailer_kg=2000,
    )
    lkw = Vehicle(
        tenant_id=tenant.id,
        name="7,5-Tonner mit Ladebordwand",
        plate=f"S-{tenant.slug[:2].upper()} 750",
        kind="truck",
        required_licence="C1",
        seats=3,
        cargo_length_cm=620,
        cargo_width_cm=244,
        cargo_height_cm=240,
        payload_kg=2600,
        door_width_cm=240,
        door_height_cm=230,
        loading_edge_cm=110,
        has_lift=True,
        front_axle_x_cm=-150,
        rear_axle_x_cm=380,
        max_front_axle_extra_kg=1200,
        max_rear_axle_extra_kg=2000,
    )
    trailer = Vehicle(
        tenant_id=tenant.id,
        name="Kofferanhänger",
        plate=f"S-{tenant.slug[:2].upper()} 900",
        kind="trailer",
        required_licence="BE",
        seats=0,
        cargo_length_cm=300,
        cargo_width_cm=150,
        cargo_height_cm=180,
        payload_kg=1600,
        door_width_cm=148,
        door_height_cm=175,
        loading_edge_cm=55,
        rear_axle_x_cm=165,
        max_rear_axle_extra_kg=1600,
        max_tongue_load_kg=100,
        min_tongue_load_kg=25,
        hitch_x_cm=-120,
    )
    vehicles = [sprinter, crafter, lkw, trailer]
    for v in vehicles:
        db.add(v)
    db.flush()
    db.add(
        VehicleShelf(
            tenant_id=tenant.id,
            vehicle_id=sprinter.id,
            name="Regal links vorn",
            x_cm=0,
            y_cm=0,
            length_cm=160,
            depth_cm=40,
            height_cm=95,
            clearance_cm=90,
            max_load_kg=70,
        )
    )
    set_value(
        db,
        actor,
        scope="vehicle",
        key="drive.vehicle_speed_factor",
        value=0.9,
        tenant_id=tenant.id,
        object_id=lkw.id,
    )
    set_value(
        db,
        actor,
        scope="vehicle",
        key="costs.vehicle_per_km",
        value=0.55,
        tenant_id=tenant.id,
        object_id=lkw.id,
    )
    set_value(
        db,
        actor,
        scope="vehicle",
        key="costs.fuel_l_per_100km",
        value=17,
        tenant_id=tenant.id,
        object_id=lkw.id,
    )
    set_value(
        db,
        actor,
        scope="vehicle",
        key="costs.vehicle_per_km",
        value=0.12,
        tenant_id=tenant.id,
        object_id=trailer.id,
    )
    set_value(
        db,
        actor,
        scope="vehicle",
        key="costs.fuel_l_per_100km",
        value=0,
        tenant_id=tenant.id,
        object_id=trailer.id,
    )

    for v, items in (
        (
            sprinter,
            [
                ("Sackkarre", "hand_truck", 150, 0.8, 70, False),
                ("Spanngurte", "straps", None, 1.0, None, False),
            ],
        ),
        (crafter, [("Pflanzenroller", "plant_roller", 200, 0.7, 120, False)]),
        (
            lkw,
            [
                ("Treppensteiger", "stair_climber", 170, 0.9, 110, True),
                ("Hubwagen", "pallet_jack", 1000, 0.6, 300, False),
            ],
        ),
    ):
        for name, kind, cap, factor, solo, stairs in items:
            db.add(
                Equipment(
                    tenant_id=tenant.id,
                    name=name,
                    kind=kind,
                    count=1,
                    capacity_kg=cap,
                    carry_time_factor=factor,
                    solo_limit_kg=solo,
                    usable_on_stairs=stairs,
                    surfaces=["paved", "tiles", "wood"] if kind != "stair_climber" else ["paved", "tiles"],
                    vehicle_id=v.id,
                )
            )
    db.add(
        Equipment(
            tenant_id=tenant.id, name="Decken und Folie", kind="blanket", count=20, carry_time_factor=1.0
        )
    )

    team = Team(
        tenant_id=tenant.id,
        name="Team Treppe",
        member_ids=[str(staff[0].id), str(staff[1].id), str(staff[2].id)],
        vehicle_id=lkw.id,
    )
    db.add(team)
    db.add(
        StorageArea(
            tenant_id=tenant.id,
            name="Kalthaus",
            kind="greenhouse_cold",
            area_m2=420,
            height_cm=380,
            min_temp_c=3,
        )
    )
    db.add(
        StorageArea(
            tenant_id=tenant.id,
            name="Warmhaus",
            kind="greenhouse_warm",
            area_m2=160,
            height_cm=320,
            min_temp_c=10,
            for_frost_sensitive=True,
        )
    )
    db.add(
        StorageArea(
            tenant_id=tenant.id,
            name="Halle",
            kind="hall",
            area_m2=250,
            height_cm=450,
            min_temp_c=1,
            for_frost_sensitive=False,
        )
    )
    # availability: some vacation and a vehicle in maintenance
    season_start = date(date.today().year, 10, 1)
    for s in staff:
        if rng.random() < 0.35:
            start = season_start + timedelta(days=rng.randint(5, 40))
            db.add(
                Availability(
                    tenant_id=tenant.id,
                    resource_type="staff",
                    resource_id=s.id,
                    kind="vacation",
                    date_from=start,
                    date_to=start + timedelta(days=rng.randint(2, 9)),
                    weekdays=[],
                )
            )
    part_timer = staff[-1]
    db.add(
        Availability(
            tenant_id=tenant.id,
            resource_type="staff",
            resource_id=part_timer.id,
            kind="available",
            weekdays=[0, 1, 2],
            note="Teilzeit Mo–Mi",
        )
    )
    m_start = season_start + timedelta(days=rng.randint(10, 30))
    db.add(
        Availability(
            tenant_id=tenant.id,
            resource_type="vehicle",
            resource_id=crafter.id,
            kind="maintenance",
            date_from=m_start,
            date_to=m_start + timedelta(days=2),
            weekdays=[],
            note="Inspektion",
        )
    )
    db.flush()
    report["staff"] = len(staff)
    report["vehicles"] = len(vehicles)
