"""Phase 3: safe formula parser, team-size rules."""

from __future__ import annotations

import pytest

from app.formula.parser import FormulaError, evaluate, names, parse
from app.timemodel.teams import CrewRules, EquipmentInfo, PathInfo, persons_for_weight, required_crew


def ev(src: str, **variables):
    return evaluate(parse(src), variables)


def test_arithmetic_and_precedence():
    assert ev("1 + 2 * 3") == 7
    assert ev("(1 + 2) * 3") == 9
    assert ev("2 ^ 3 ^ 2") == 512  # right associative
    assert ev("-2 ^ 2") == -4
    assert ev("10 / 4") == 2.5
    assert ev("7 % 3") == 1
    assert ev("a * b + c", a=2, b=3, c=1) == 7
    assert ev("1.5e2") == 150


def test_functions_and_conditions():
    assert ev("min(3, 1, 2) + max(4, 5)") == 6
    assert ev("if(w > 30, 2, 1)", w=40) == 2
    assert ev("if(w > 30 and steps > 0, 3, 1)", w=40, steps=0) == 1
    assert ev("not (1 > 2)") == 1
    assert ev("clamp(x, 0, 10)", x=15) == 10
    assert ev("round(2.345, 2)") == pytest.approx(2.35)
    assert ev("log(exp(2))") == pytest.approx(2)
    assert ev("sqrt(16) + abs(-1) + floor(1.7) + ceil(1.2)") == 8


def test_aggregates_over_plants():
    t = parse("t + max(sum_plants(work) / team, max_plants(work / crew))")
    plants = [{"work": 10, "crew": 1}, {"work": 30, "crew": 3}]
    assert evaluate(t, {"t": 5, "team": 2}, plants) == 25
    assert evaluate(parse("count_plants() + avg_plants(work)"), {}, plants) == 22
    outer, inner = names(t)
    assert outer == {"t", "team"} and inner == {"work", "crew"}


@pytest.mark.parametrize(
    "src,code",
    [
        ("1 +", "syntax"),
        ("(1 + 2", "syntax"),
        ("__import__('os')", "syntax"),
        ("open(1)", "unknown_function"),
        ("a.b", "syntax"),
        ("1 ; 2", "syntax"),
        ("max()", "arity"),
        ("x" + " + x" * 700, "too_complex"),
    ],
)
def test_rejects_unsafe_or_invalid(src, code):
    with pytest.raises(FormulaError) as exc:
        evaluate(parse(src), {"x": 1})
    assert exc.value.code == code


def test_error_positions_and_eval_errors():
    with pytest.raises(FormulaError) as exc:
        parse("a + * b")
    assert exc.value.pos == 4
    with pytest.raises(FormulaError) as exc:
        ev("1 / x", x=0)
    assert exc.value.code == "eval"
    with pytest.raises(FormulaError) as exc:
        ev("unknown_var + 1")
    assert exc.value.code == "unknown_name" and exc.value.name == "unknown_var"
    with pytest.raises(FormulaError):
        ev("10 ^ 1000")


RULES = CrewRules(
    solo_kg=25,
    carry_factor=0.8,
    grip_diameter_cm=70,
    grip_height_cm=200,
    stairs_weight_kg=20,
    stairs_extra=1,
    steep_slope_pct=12,
    narrow_extra=0,
    max_size=4,
)
FLAT = PathInfo(10, 0, 0, None, 0, 0, False, False, ["paved"])
STAIRS = PathInfo(20, 6, 36, 100, 1, 0, True, False, ["paved", "tiles"])
SACK = EquipmentInfo("1", "Sackkarre", "hand_truck", 150, 0.8, 80, False, ["paved", "tiles"], None, None)
CLIMBER = EquipmentInfo(
    "2", "Treppensteiger", "stair_climber", 170, 0.9, 110, True, ["paved", "tiles"], None, None
)


def test_weight_rule_with_carry_factor():
    assert persons_for_weight(25, [25], 0.8) == 1
    assert persons_for_weight(26, [25], 0.8) == 2  # 0.8 * 2 * 25 = 40
    assert persons_for_weight(41, [25], 0.8) == 3
    # individual members: strongest first
    assert persons_for_weight(60, [40, 35, 20], 0.8) == 2  # 0.8*(40+35) = 60 is just enough
    assert persons_for_weight(61, [40, 35, 20], 0.8) == 3
    assert persons_for_weight(40, [40, 35, 20], 0.8) == 1


def test_required_crew_rules():
    assert required_crew(20, 40, 150, FLAT, RULES, [], False).crew == 1
    r = required_crew(20, 80, 150, FLAT, RULES, [], False)
    assert r.crew == 2 and "grip_diameter" in r.reasons
    r = required_crew(60, 50, 150, STAIRS, RULES, [], False)
    assert r.crew == 3 + 1 and "stairs" in r.reasons
    # a sack truck on a flat path lets one person move 60 kg
    r = required_crew(60, 50, 150, FLAT, RULES, [SACK], False)
    assert r.crew == 1 and r.equipment is SACK and "equipment" in r.reasons
    # not on stairs; the stair climber also removes the stairs surcharge
    r = required_crew(60, 50, 150, STAIRS, RULES, [SACK], False)
    assert r.equipment is None
    r = required_crew(100, 50, 150, STAIRS, RULES, [SACK, CLIMBER], False)
    assert r.equipment is CLIMBER and "stairs" not in r.reasons and r.crew == 1
    # max size and override
    r = required_crew(300, 90, 250, STAIRS, RULES, [], False)
    assert r.crew == 4 and r.exceeds_max and r.needed > 4
    assert required_crew(300, 90, 250, STAIRS, RULES, [], False, override=6).crew == 6
