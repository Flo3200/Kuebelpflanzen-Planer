"""Settings registry – the single source of truth for every configurable value.

Each setting has: key, type, unit, default, bounds, allowed levels, group and an
"important" flag (simple view). German labels and explanations live in
app/i18n/de.json under settings.<key>.label / settings.<key>.help.

Levels, from least to most specific:
  platform (admin default) -> tenant (nursery) -> object (staff, vehicle, equipment,
  species, plant, customer, tour)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

OBJECT_SCOPES = ("staff", "vehicle", "equipment", "species", "plant", "customer", "tour")
ALL_LEVELS = ("platform", "tenant", *OBJECT_SCOPES)

PT = ("platform", "tenant")
P = ("platform",)

# Strategy names offered by OR-Tools; kept here so the UI can show choices.
FIRST_SOLUTION = (
    "AUTOMATIC",
    "PATH_CHEAPEST_ARC",
    "PARALLEL_CHEAPEST_INSERTION",
    "LOCAL_CHEAPEST_INSERTION",
    "SAVINGS",
    "CHRISTOFIDES",
    "GLOBAL_CHEAPEST_ARC",
)
METAHEURISTICS = ("AUTOMATIC", "GUIDED_LOCAL_SEARCH", "SIMULATED_ANNEALING", "TABU_SEARCH", "GREEDY_DESCENT")
AI_FUNCTIONS = (
    "completeness_check",
    "photo_analysis",
    "message_intake",
    "settings_assistant",
    "support_agent",
    "vehicle_photo",
    "vehicle_chat",
    "load_layout",
)


@dataclass(frozen=True)
class SettingDef:
    key: str
    type: str  # int | float | bool | str | text | enum | json | time
    default: Any
    group: str
    levels: tuple[str, ...] = PT
    unit: str | None = None
    min: float | None = None
    max: float | None = None
    choices: tuple[str, ...] | None = None
    choices_source: str | None = None  # dynamic choices, e.g. "ai_models"
    important: bool = False
    admin_only: bool = False  # tenant-level values may only be written by the platform admin
    secret: bool = False
    tags: tuple[str, ...] = field(default_factory=tuple)
    module: str | None = None  # shown and used only while this module is on (app/core/modules.py)


def _s(*args, **kwargs) -> SettingDef:
    return SettingDef(*args, **kwargs)


SETTINGS: tuple[SettingDef, ...] = (
    # --- modules (off by default: the platform focuses on logistics) -----------
    _s("modules.storage", "bool", False, "modules", important=True),
    _s("modules.customer_billing", "bool", False, "modules", important=True),
    _s("modules.portal", "bool", False, "modules", important=True),
    _s("modules.payments", "bool", False, "modules", important=True),
    # --- general -------------------------------------------------------------
    _s("general.season_start_month", "int", 9, "general", unit="Monat", min=1, max=12),
    _s("general.currency", "enum", "EUR", "general", choices=("EUR", "CHF")),
    _s("general.timezone", "str", "Europe/Berlin", "general"),
    _s(
        "general.storage_warn_pct",
        "float",
        90.0,
        "general",
        unit="%",
        min=10,
        max=100,
        important=True,
        module="storage",
    ),
    _s(
        "general.storage_space_factor", "float", 1.25, "general", unit="×", min=1.0, max=3.0, module="storage"
    ),
    # --- security / platform -------------------------------------------------
    _s("security.admin_require_2fa", "bool", False, "security", levels=P),
    _s("security.owner_require_2fa", "bool", False, "security"),
    _s("platform.mode", "enum", "test", "platform", levels=P, choices=("test", "production"), important=True),
    # --- staff (carrying, driving, working time) ------------------------------
    _s(
        "staff.solo_carry_kg",
        "float",
        25.0,
        "staff",
        levels=(*PT, "staff"),
        unit="kg",
        min=0,
        max=80,
        important=True,
    ),
    _s(
        "staff.team_carry_factor",
        "float",
        0.8,
        "staff",
        levels=(*PT, "staff"),
        unit="×",
        min=0.3,
        max=1.0,
        important=True,
    ),
    _s("staff.carry_speed_factor", "float", 1.0, "staff", levels=(*PT, "staff"), unit="×", min=0.3, max=3.0),
    _s("staff.drive_speed_factor", "float", 1.0, "staff", levels=(*PT, "staff"), unit="×", min=0.5, max=1.5),
    _s("staff.max_work_hours_day", "float", 10.0, "staff", levels=(*PT, "staff"), unit="h", min=1, max=12),
    _s(
        "staff.hourly_wage",
        "float",
        16.0,
        "costs",
        levels=(*PT, "staff"),
        unit="€/h",
        min=0,
        max=200,
        important=True,
    ),
    _s("staff.employer_share_pct", "float", 21.0, "costs", levels=(*PT, "staff"), unit="%", min=0, max=100),
    # --- team-size rules -------------------------------------------------------
    _s(
        "team.grip_diameter_cm",
        "float",
        70.0,
        "team",
        levels=(*PT, "species", "plant"),
        unit="cm",
        min=10,
        max=300,
    ),
    _s(
        "team.grip_height_cm",
        "float",
        200.0,
        "team",
        levels=(*PT, "species", "plant"),
        unit="cm",
        min=30,
        max=600,
    ),
    _s("team.stairs_weight_kg", "float", 20.0, "team", levels=PT, unit="kg", min=0, max=200),
    _s("team.stairs_extra_persons", "int", 1, "team", levels=PT, unit="Pers.", min=0, max=3),
    _s("team.steep_slope_pct", "float", 12.0, "team", levels=PT, unit="%", min=0, max=50),
    _s("team.narrow_extra_persons", "int", 0, "team", levels=PT, unit="Pers.", min=0, max=2),
    _s("team.max_size", "int", 4, "team", levels=PT, unit="Pers.", min=1, max=8, important=True),
    _s("team.plan_over_limit", "bool", True, "team"),
    _s("team.min_size_per_stop", "int", 1, "team", levels=(*PT, "customer"), unit="Pers.", min=1, max=6),
    # --- time model --------------------------------------------------------------
    _s("time.walk_speed_m_min", "float", 25.0, "time", unit="m/min", min=5, max=150),
    _s("time.narrow_clearance_cm", "float", 10.0, "time", unit="cm", min=0, max=100),
    _s("time.narrow_factor", "float", 1.5, "time", unit="×", min=1, max=5),
    _s("time.planning_quantile", "float", 0.8, "time", unit="", min=0.5, max=0.99, important=True),
    _s("time.default_path_length_m", "float", 15.0, "time", unit="m", min=0, max=500),
    _s("time.formula_tier", "int", 1, "time", unit="", min=1, max=9),
    _s("time.error_sigma", "float", 0.25, "time", unit="", min=0.0, max=2.0),
    # --- weight estimation ---------------------------------------------------------
    _s("weight.pot_fill", "float", 0.88, "weight", unit="", min=0.3, max=1.0),
    _s("weight.pot_taper", "float", 0.85, "weight", unit="", min=0.5, max=1.0),
    _s(
        "weight.pot_material_kg_per_l",
        "json",
        {
            "plastic": 0.03,
            "fiberglass": 0.06,
            "wood": 0.15,
            "metal": 0.12,
            "terracotta": 0.25,
            "glazed": 0.3,
            "stone": 0.6,
            "concrete": 0.7,
        },
        "weight",
    ),
    _s("weight.uncertainty_pct", "float", 25.0, "weight", unit="%", min=0, max=200),
    _s("weight.calibration_factor", "float", 1.0, "weight", unit="×", min=0.3, max=3.0, important=True),
    _s("weight.default_pot_diameter_cm", "float", 45.0, "weight", unit="cm", min=10, max=300),
    _s("weight.default_crown_ratio", "float", 1.6, "weight", unit="×", min=0.3, max=6),
    # --- learning ------------------------------------------------------------------
    _s("learning.loss", "enum", "huber", "learning", choices=("linear", "huber")),
    _s("learning.huber_delta_min", "float", 6.0, "learning", unit="min", min=0.5, max=60),
    _s("learning.lambda", "float", 1.0, "learning", unit="", min=0, max=1000),
    _s("learning.cv_folds", "int", 5, "learning", unit="", min=2, max=20),
    _s("learning.min_measurements_per_param", "int", 15, "learning", unit="", min=3, max=200),
    _s("learning.schedule", "enum", "off", "learning", choices=("off", "weekly", "monthly")),
    _s("learning.staff_factor_prior_n", "int", 20, "learning", unit="", min=1, max=500),
    _s("learning.experiment_share", "float", 0.0, "learning", unit="", min=0, max=0.5),
    # --- driving ------------------------------------------------------------------
    _s("drive.provider", "enum", "offline", "drive", levels=P, choices=("offline", "osrm", "ors", "google")),
    _s("drive.detour_factor", "float", 1.35, "drive", unit="×", min=1.0, max=3.0),
    _s("drive.avg_speed_kmh", "float", 45.0, "drive", unit="km/h", min=10, max=120),
    _s(
        "drive.trailer_speed_factor",
        "float",
        0.88,
        "drive",
        levels=(*PT, "vehicle"),
        unit="×",
        min=0.5,
        max=1.0,
    ),
    _s(
        "drive.trailer_max_kmh", "float", 80.0, "drive", levels=(*PT, "vehicle"), unit="km/h", min=40, max=100
    ),
    _s(
        "drive.parking_min",
        "float",
        4.0,
        "drive",
        levels=(*PT, "vehicle", "customer"),
        unit="min",
        min=0,
        max=60,
    ),
    _s(
        "drive.vehicle_speed_factor",
        "float",
        1.0,
        "drive",
        levels=(*PT, "vehicle"),
        unit="×",
        min=0.5,
        max=1.5,
    ),
    # --- costs --------------------------------------------------------------------
    _s("costs.overtime_surcharge_pct", "float", 25.0, "costs", unit="%", min=0, max=200),
    _s("costs.vehicle_per_km", "float", 0.30, "costs", levels=(*PT, "vehicle"), unit="€/km", min=0, max=10),
    _s("costs.vehicle_per_hour", "float", 6.0, "costs", levels=(*PT, "vehicle"), unit="€/h", min=0, max=200),
    _s("costs.fuel_price", "float", 1.75, "costs", unit="€/l", min=0, max=5),
    _s(
        "costs.fuel_l_per_100km",
        "float",
        11.0,
        "costs",
        levels=(*PT, "vehicle"),
        unit="l/100 km",
        min=0,
        max=60,
    ),
    _s("costs.equipment_per_use", "float", 0.0, "costs", levels=(*PT, "equipment"), unit="€", min=0, max=500),
    # logistics costs only by default (package E): overhead and margin are 0 %, still adjustable
    _s("costs.overhead_pct", "float", 0.0, "costs", unit="%", min=0, max=200, important=True),
    _s("costs.workdays_per_month", "int", 21, "costs", unit="Tage", min=1, max=31),
    _s(
        "costs.margin_pct",
        "float",
        0.0,
        "costs",
        unit="%",
        min=0,
        max=300,
        important=True,
        module="customer_billing",
    ),
    _s("costs.vat_pct", "float", 19.0, "costs", unit="%", min=0, max=30, module="customer_billing"),
    _s("costs.small_business", "bool", False, "costs", module="customer_billing"),
    # --- pricing ------------------------------------------------------------------
    _s(
        "pricing.base_price",
        "float",
        25.0,
        "pricing",
        levels=(*PT, "customer"),
        unit="€",
        min=0,
        max=5000,
        important=True,
        module="customer_billing",
    ),
    _s(
        "pricing.rate_per_labour_min",
        "float",
        0.75,
        "pricing",
        levels=(*PT, "customer"),
        unit="€/min",
        min=0,
        max=20,
        important=True,
        module="customer_billing",
    ),
    _s(
        "pricing.per_plant_fee",
        "float",
        6.0,
        "pricing",
        levels=(*PT, "customer"),
        unit="€",
        min=0,
        max=500,
        important=True,
        module="customer_billing",
    ),
    _s(
        "pricing.minimum_price",
        "float",
        49.0,
        "pricing",
        levels=(*PT, "customer"),
        unit="€",
        min=0,
        max=5000,
        important=True,
        module="customer_billing",
    ),
    _s(
        "pricing.distance_mode",
        "enum",
        "distance",
        "pricing",
        choices=("off", "distance", "zones", "detour"),
        module="customer_billing",
    ),
    _s(
        "pricing.distance_rate_km",
        "float",
        0.9,
        "pricing",
        unit="€/km",
        min=0,
        max=20,
        module="customer_billing",
    ),
    _s(
        "pricing.distance_free_km",
        "float",
        5.0,
        "pricing",
        unit="km",
        min=0,
        max=200,
        module="customer_billing",
    ),
    _s(
        "pricing.zones",
        "json",
        [{"max_km": 10, "surcharge": 0}, {"max_km": 25, "surcharge": 15}, {"max_km": 9999, "surcharge": 35}],
        "pricing",
        module="customer_billing",
    ),
    _s("pricing.rounding", "float", 1.0, "pricing", unit="€", min=0, max=50, module="customer_billing"),
    _s("pricing.prices_include_vat", "bool", True, "pricing", module="customer_billing"),
    # used for the drive share of the cost estimate before planning, hence group costs
    _s("pricing.typical_tour_stops", "int", 8, "costs", unit="", min=1, max=50),
    _s("pricing.local_detour_km", "float", 4.0, "costs", unit="km", min=0, max=100),
    # --- planning -------------------------------------------------------------------
    _s("planning.day_start", "time", "07:00", "planning", levels=(*PT, "staff", "vehicle"), important=True),
    _s("planning.day_end", "time", "17:30", "planning", levels=(*PT, "staff", "vehicle"), important=True),
    # package F: unloading time from the formula "unload" (fixed minutes only as fallback/choice)
    _s(
        "planning.unload_mode",
        "enum",
        "formula",
        "planning",
        levels=(*PT, "vehicle"),
        choices=("formula", "fixed"),
        important=True,
    ),
    _s("planning.unload_min", "float", 20.0, "planning", levels=(*PT, "vehicle"), unit="min", min=0, max=240),
    _s("planning.load_min", "float", 25.0, "planning", levels=(*PT, "vehicle"), unit="min", min=0, max=240),
    _s("planning.break_after_6h_min", "float", 30.0, "planning", unit="min", min=0, max=120),
    _s("planning.break_after_9h_min", "float", 45.0, "planning", unit="min", min=0, max=120),
    _s("planning.max_trips_per_day", "int", 3, "planning", levels=(*PT, "vehicle"), unit="", min=1, max=8),
    _s("planning.time_windows", "enum", "soft", "planning", choices=("off", "soft", "hard")),
    _s("planning.time_window_penalty_min", "float", 2.0, "planning", unit="€/min", min=0, max=100),
    _s("planning.skip_penalty", "float", 2000.0, "planning", unit="€", min=0, max=1e6),
    _s("planning.overtime_penalty_min", "float", 1.0, "planning", unit="€/min", min=0, max=100),
    _s("planning.objective", "enum", "cost", "planning", choices=("cost", "profit")),
    _s("planning.weight_vehicle_cost", "float", 1.0, "planning", unit="×", min=0, max=10),
    _s("planning.weight_labour_cost", "float", 1.0, "planning", unit="×", min=0, max=10),
    _s("planning.first_solution", "enum", "PARALLEL_CHEAPEST_INSERTION", "planning", choices=FIRST_SOLUTION),
    _s("planning.metaheuristic", "enum", "GUIDED_LOCAL_SEARCH", "planning", choices=METAHEURISTICS),
    _s("planning.time_limit_s", "float", 30.0, "planning", unit="s", min=1, max=3600, important=True),
    _s("planning.cluster_max_stops", "int", 180, "planning", unit="", min=20, max=2000),
    _s("planning.pack_retry_limit", "int", 4, "planning", unit="", min=0, max=20),
    _s("planning.capacity_shrink", "float", 0.9, "planning", unit="×", min=0.5, max=0.99),
    _s("planning.form_teams", "enum", "auto", "planning", choices=("auto", "fixed")),
    # staged optimisation: fastest route -> team composition variants -> search experiments -> final
    _s("planning.strategy", "enum", "staged", "planning", choices=("staged", "single"), important=True),
    _s("planning.team_size_default", "int", 2, "planning", unit="Pers.", min=1, max=8),
    _s("planning.day_preference_eur", "float", 3.0, "planning", unit="€/Tag", min=0, max=1000),
    _s("planning.unit_fixed_eur", "float", 15.0, "planning", unit="€", min=0, max=10000),
    _s("planning.horizon_days", "int", 10, "planning", unit="Tage", min=1, max=90),
    # --- packing --------------------------------------------------------------------
    _s("packing.time_limit_s", "float", 3.0, "packing", unit="s", min=0.2, max=120),
    # package G: AI proposal as start solution (always checked and improved by the packer)
    _s("packing.mode", "enum", "rules", "packing", choices=("rules", "ai_start", "compare")),
    _s(
        "packing.sort_rule",
        "enum",
        "tour_then_size",
        "packing",
        choices=("tour_then_size", "size", "weight", "tour"),
    ),
    _s(
        "packing.crown_overlap",
        "float",
        0.15,
        "packing",
        levels=(*PT, "species", "plant"),
        unit="",
        min=0,
        max=0.6,
    ),
    _s(
        "packing.tilt_angle_deg",
        "float",
        90.0,
        "packing",
        levels=(*PT, "species", "plant"),
        unit="°",
        min=0,
        max=90,
    ),
    _s("packing.clearance_cm", "float", 2.0, "packing", unit="cm", min=0, max=20),
    _s("packing.heavy_kg", "float", 40.0, "packing", unit="kg", min=1, max=500),
    _s("packing.cog_tolerance", "float", 0.15, "packing", unit="", min=0.02, max=0.5),
    _s("packing.tall_ratio", "float", 3.0, "packing", unit="", min=1, max=10),
    # --- photos and data protection ------------------------------------------------
    _s("photos.plant_set", "json", ["plant_front", "plant_side", "plant_top", "pot"], "photos"),
    _s("photos.path_set", "json", ["path_start", "path_segment", "path_end"], "photos"),
    _s("photos.min_confidence", "float", 0.6, "photos", unit="", min=0, max=1, important=True),
    _s("privacy.consent_text", "text", "", "privacy", important=True),
    _s("privacy.photo_retention_days", "int", 240, "privacy", unit="Tage", min=7, max=3650),
    _s("privacy.customer_retention_days", "int", 1095, "privacy", unit="Tage", min=30, max=3650),
    _s("privacy.invoice_retention_years", "int", 10, "privacy", levels=P, unit="Jahre", min=6, max=15),
    # --- AI ---------------------------------------------------------------------------
    *[_s(f"ai.model.{fn}", "str", "", "ai", choices_source="ai_models") for fn in AI_FUNCTIONS],
    _s("ai.fallback_model", "str", "", "ai", choices_source="ai_models"),
    _s("ai.key_mode", "enum", "platform", "ai", choices=("platform", "byok"), admin_only=True),
    _s("ai.monthly_limit_eur", "float", 50.0, "ai", unit="€", min=0, max=100000, admin_only=True),
    _s("ai.warn_pct", "float", 80.0, "ai", unit="%", min=1, max=100),
    _s("ai.max_retries", "int", 2, "ai", unit="", min=0, max=5),
    _s("ai.usd_to_eur", "float", 0.92, "ai", levels=P, unit="€/$", min=0.1, max=10),
    # --- driver app ----------------------------------------------------------------
    _s("driver.per_plant_events", "bool", False, "driver", important=True),
    _s("driver.require_pickup_photo", "bool", True, "driver"),
    _s("driver.qr_module", "bool", False, "driver"),
    # --- billing of the platform (written by admin per tenant) -----------------------
    _s("billing.subscription_eur", "float", 0.0, "billing", unit="€", min=0, max=100000, admin_only=True),
    _s(
        "billing.subscription_period",
        "enum",
        "monthly",
        "billing",
        choices=("monthly", "yearly"),
        admin_only=True,
    ),
    _s("billing.per_plant_eur", "float", 0.0, "billing", unit="€", min=0, max=100, admin_only=True),
    _s("billing.ai_markup_pct", "float", 0.0, "billing", unit="%", min=0, max=500, admin_only=True),
    _s("billing.ai_enabled", "bool", True, "billing", admin_only=True),
    _s("billing.vat_pct", "float", 19.0, "billing", levels=P, unit="%", min=0, max=30),
    _s("billing.small_business", "bool", False, "billing", levels=P),
    _s(
        "billing.issuer",
        "json",
        {
            "name": "",
            "street": "",
            "postal_code": "",
            "city": "",
            "vat_id": "",
            "tax_number": "",
            "iban": "",
            "email": "",
        },
        "billing",
        levels=P,
    ),
    _s("billing.payment_days", "int", 14, "billing", levels=P, unit="Tage", min=0, max=90),
    # --- spring return ---------------------------------------------------------------
    _s(
        "returns.frost_rule",
        "enum",
        "frost_sensitive",
        "returns",
        choices=("frost_sensitive", "all", "off"),
        important=True,
    ),
    _s("returns.frost_safe_date", "str", "05-15", "returns", important=True),
    _s("returns.time_factor", "float", 1.0, "returns", unit="×", min=0.3, max=3.0),
    _s(
        "returns.price_mode",
        "enum",
        "separate",
        "returns",
        choices=("separate", "included", "factor"),
        module="customer_billing",
    ),
    _s("returns.price_factor", "float", 0.8, "returns", unit="×", min=0, max=3.0, module="customer_billing"),
    _s("returns.default_window_days", "int", 42, "returns", unit="Tage", min=1, max=180),
    # --- customer portal and online payment -------------------------------------------
    # the on/off switch is modules.portal (was portal.enabled until the logistics focus)
    _s("portal.link_days", "int", 120, "portal", unit="Tage", min=1, max=730, module="portal"),
    _s("portal.accept_quote_confirms", "bool", True, "portal", module="portal"),
    _s(
        "payments.provider",
        "enum",
        "off",
        "portal",
        choices=("off", "test", "stripe"),
        important=True,
        module="payments",
    ),
    _s("payments.stripe_account", "str", "", "portal", module="payments"),
    # --- agents --------------------------------------------------------------------
    _s("agents.token_days", "int", 30, "agents", unit="Tage", min=1, max=365),
    _s("agents.rate_per_min", "int", 120, "agents", unit="/min", min=1, max=10000),
)

REGISTRY: dict[str, SettingDef] = {s.key: s for s in SETTINGS}
GROUPS: tuple[str, ...] = tuple(dict.fromkeys(s.group for s in SETTINGS))


def get_def(key: str) -> SettingDef:
    try:
        return REGISTRY[key]
    except KeyError as exc:
        raise KeyError(f"unknown setting {key!r}") from exc


def keys_for_scope(scope: str) -> list[str]:
    return [s.key for s in SETTINGS if scope in s.levels]
