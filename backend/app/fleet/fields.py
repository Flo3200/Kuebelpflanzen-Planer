"""Vehicle values the AI fills in (package C): name, column (or object setting) and type.

Each value in a draft is {value, confidence}. Costs are object settings of the vehicle
(costs.vehicle_per_km, costs.vehicle_per_hour, costs.fuel_l_per_100km), everything else is a
column of the vehicles table. Shelves become modules assigned to the vehicle.
"""

from __future__ import annotations

# (key, kind) – kind: number | integer | string | boolean
VEHICLE_FIELDS: list[tuple[str, str]] = [
    ("name", "string"),
    ("kind", "string"),
    ("plate", "string"),
    ("required_licence", "string"),
    ("seats", "integer"),
    ("payload_kg", "number"),
    ("cargo_length_cm", "number"),
    ("cargo_width_cm", "number"),
    ("cargo_height_cm", "number"),
    ("door_width_cm", "number"),
    ("door_height_cm", "number"),
    ("door_position", "string"),
    ("loading_edge_cm", "number"),
    ("wheel_arch_x_cm", "number"),
    ("wheel_arch_length_cm", "number"),
    ("wheel_arch_width_cm", "number"),
    ("wheel_arch_height_cm", "number"),
    ("front_axle_x_cm", "number"),
    ("rear_axle_x_cm", "number"),
    ("max_front_axle_extra_kg", "number"),
    ("max_rear_axle_extra_kg", "number"),
    ("can_tow", "boolean"),
    ("max_trailer_kg", "number"),
    ("max_tongue_load_kg", "number"),
]
COST_FIELDS: list[tuple[str, str, str]] = [
    # draft key, setting key, kind
    ("cost_per_km", "costs.vehicle_per_km", "number"),
    ("cost_per_hour", "costs.vehicle_per_hour", "number"),
    ("fuel_l_per_100km", "costs.fuel_l_per_100km", "number"),
]
SHELF_FIELDS: list[tuple[str, str]] = [
    ("name", "string"),
    ("x_cm", "number"),
    ("y_cm", "number"),
    ("length_cm", "number"),
    ("depth_cm", "number"),
    ("height_cm", "number"),
    ("clearance_cm", "number"),
    ("max_load_kg", "number"),
]
# without these the vehicle cannot be planned or packed; missing or unsure ones are asked for
REQUIRED = (
    "cargo_length_cm",
    "cargo_width_cm",
    "cargo_height_cm",
    "payload_kg",
    "door_width_cm",
    "door_height_cm",
)
KINDS = ("van", "truck", "trailer", "car")
LICENCES = ("B", "BE", "C1", "C1E", "C", "CE")
# plausible ranges for the check of AI values (outside: confidence is capped)
RANGES: dict[str, tuple[float, float]] = {
    "cargo_length_cm": (80, 1400),
    "cargo_width_cm": (80, 260),
    "cargo_height_cm": (60, 300),
    "payload_kg": (100, 20000),
    "door_width_cm": (50, 260),
    "door_height_cm": (50, 300),
    "seats": (1, 9),
}
