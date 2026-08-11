"""Spec → kinetics-input translation, fed/fasted curve superposition, and the
serum calibration for the substance level graph.

Pure: no I/O, no clock. The `/levels` handler fetches the intakes and labs;
this module turns a catalog spec into the parallel absorption inputs, sums the
modeled curve, and fits the serum scale from the labs. Extracted from the
handler so the subtlest assembly (dual-peak split, fed/fasted superposition,
the lookback horizon, the calibration fit) has a direct test seam instead of
being reachable only through the app.
"""

import statistics
from bisect import bisect_left
from collections.abc import Sequence
from typing import Literal

from heartbeat.logger.kinetics import Input, curve_inputs, level_at_inputs
from heartbeat.logger.specs import LevelPoint, Measurement, MeasurementPoint, SubstanceSpec

__all__ = [
    "Intake",
    "IntakeGroup",
    "calibrate_serum",
    "inputs_for_spec",
    "intake_groups",
    "lookback_start",
    "modeled_curve",
    "modeled_level",
    "trend_between",
]

# events older than this many of the slowest characteristic time (elimination or
# an input's absorption ramp + release lag) contribute < 0.1% of their dose
_LOOKBACK_HALF_LIVES = 14

# amplitude calibration. A lab only informs the scale if the model predicts a
# non-trivial level at the draw (i.e. logged doses actually surround it); below
# this relative-mg floor the draw has no dose history and is skipped rather than
# blowing the fit up with a C / ~0 division. Untimed old labs land here and drop
# out on their own.
_CALIB_MIN_LEVEL = 0.1
# lab-unit -> pg/mL factors, only what we log; an unknown unit returns None so
# the lab is skipped, never silently misplaced on the curve.
# The molar factor is analyte-specific (pg/mL = pmol/L x molar mass / 1000), so
# add a row per analyte you log rather than reusing this one.
_UNIT_TO_PGML = {"pg/ml": 1.0, "pmol/l": 0.2724}

# one logged intake as the curve needs it: (taken_at, dose_mg, fasted). fasted is
# False => taken with food (the slower fed uptake); True or None => default uptake
Intake = tuple[float, float, bool | None]
# an absorption group: its (taken_at, dose_mg) events sharing one input set
IntakeGroup = tuple[list[tuple[float, float]], Sequence[Input]]


def inputs_for_spec(spec: SubstanceSpec) -> tuple[float, list[Input], list[Input] | None]:
    """(half_life_s, absorption inputs, fed inputs or None) for a curve-capable spec.

    Raises ValueError when the spec can't be curved (no elimination half-life) or a
    dual_peak row is missing an absorption parameter. The model validator normally
    guarantees the dual_peak params; this guard keeps a hand-edited DB row honest.
    """
    if spec.half_life_hours is None:
        raise ValueError("has no half_life_hours configured; no curve available")
    half_life_s = spec.half_life_hours * 3600
    if spec.model_family == "dual_peak":
        # two parallel first-order inputs of an extended-release dose: immediate
        # release now, the rest after er_lag
        if (
            spec.dose_split is None
            or spec.absorption_half_life_hours is None
            or spec.er_absorption_half_life_hours is None
            or spec.er_lag_hours is None
        ):
            raise ValueError("dual_peak params incomplete")
        inputs: list[Input] = [
            (spec.dose_split, spec.absorption_half_life_hours * 3600, 0.0),
            (
                1 - spec.dose_split,
                spec.er_absorption_half_life_hours * 3600,
                spec.er_lag_hours * 3600,
            ),
        ]
    else:
        abs_s = spec.absorption_half_life_hours * 3600 if spec.absorption_half_life_hours else None
        inputs = [(1.0, abs_s, 0.0)]
    # food slows uptake: fed intakes draw with a slower single absorption. Only for
    # families that define a fed uptake; dual_peak food effects aren't characterised,
    # so the flag is ignored there.
    fed_abs_s = (
        spec.fed_absorption_half_life_hours * 3600
        if spec.fed_absorption_half_life_hours and spec.model_family != "dual_peak"
        else None
    )
    fed_inputs: list[Input] | None = [(1.0, fed_abs_s, 0.0)] if fed_abs_s else None
    return half_life_s, inputs, fed_inputs


def lookback_start(
    curve_start: float,
    half_life_s: float,
    inputs: Sequence[Input],
    fed_inputs: Sequence[Input] | None,
) -> float:
    """Earliest intake time that can still affect the curve at curve_start: the
    slowest of elimination and each input's absorption ramp + release lag, times a
    fixed number of those spans."""
    all_inputs = [*inputs, *(fed_inputs or [])]
    slowest = max([half_life_s, *((a or 0.0) + lag for _, a, lag in all_inputs)])
    return curve_start - _LOOKBACK_HALF_LIVES * slowest


# how close a meal has to sit to an intake for the intake to count as fed. Food
# slows gastric emptying, so what matters is eating shortly BEFORE the dose or
# alongside it; a meal two hours earlier has largely cleared. Asymmetric on
# purpose, and deliberately not a per-substance catalog param (YAGNI).
FED_WINDOW_BEFORE_S = 90 * 60
FED_WINDOW_AFTER_S = 30 * 60


def infer_fed(
    intakes: Sequence[Intake],
    meal_times: Sequence[float],
    *,
    before_s: float = FED_WINDOW_BEFORE_S,
    after_s: float = FED_WINDOW_AFTER_S,
) -> list[Intake]:
    """Fill an *unset* fasted flag from food-photo times.

    In practice nobody remembers to tick `--fed`, so the flag is almost always
    None and every intake would draw the fasted curve. A food photo near an intake is the
    evidence that was missing, and it arrives late: photos are batch-uploaded
    days after the meal, so this is applied at read time rather than stamped at
    write time. Uploading a batch retroactively re-shapes past curves, which is
    the point.

    An explicitly set flag always wins (inference only fills None), so ticking
    it stays possible and stays authoritative.

    `meal_times` must already exclude entries whose time is a batch-upload
    stamp; see `FoodStore.meal_times`. Passing those in would mark every intake
    around the upload instant as fed.
    """
    if not meal_times:
        return list(intakes)
    ordered = sorted(meal_times)
    out: list[Intake] = []
    for taken_at, dose_mg, fasted in intakes:
        if fasted is not None:  # hand-set, never overridden
            out.append((taken_at, dose_mg, fasted))
            continue
        # a meal in [t - before, t + after] makes this intake fed
        i = bisect_left(ordered, taken_at - before_s)
        near = i < len(ordered) and ordered[i] <= taken_at + after_s
        out.append((taken_at, dose_mg, False if near else None))
    return out


def intake_groups(
    intakes: Sequence[Intake], inputs: Sequence[Input], fed_inputs: Sequence[Input] | None
) -> list[IntakeGroup]:
    """Split intakes into absorption groups: fed intakes (fasted is False) draw on
    the slower fed inputs, the rest on the default. One group when no fed uptake is
    configured. Summing the groups' curves is the superposition (linear kinetics)."""
    if fed_inputs is not None:
        return [
            ([(t, d) for t, d, fasted in intakes if fasted is False], fed_inputs),
            ([(t, d) for t, d, fasted in intakes if fasted is not False], inputs),
        ]
    return [([(t, d) for t, d, _ in intakes], inputs)]


def modeled_level(groups: Sequence[IntakeGroup], t: float, half_life_s: float) -> float:
    """Total modeled mg at time t, summed across the absorption groups."""
    return sum(level_at_inputs(ev, t, half_life_s, ins) for ev, ins in groups)


def _to_serum_unit(value: float, from_unit: str, to_unit: str) -> float | None:
    """Convert a lab value into the curve's serum unit, or None if we can't."""
    src, dst = from_unit.strip().lower(), to_unit.strip().lower()
    if src == dst:
        return value
    if dst == "pg/ml" and src in _UNIT_TO_PGML:
        return value * _UNIT_TO_PGML[src]
    return None


def calibrate_serum(
    labs: Sequence[Measurement],
    groups: Sequence[IntakeGroup],
    half_life_s: float,
    *,
    serum_unit: str,
    prior_scale: float,
    window: tuple[float, float],
) -> tuple[float, int, list[MeasurementPoint]]:
    """amplitude calibration: (serum scale, labs fitted, in-window overlay).

    The scale s = C / L(t) is the median over draws where the model predicts a
    non-trivial level (dose history actually surrounds the draw); with no usable
    draw the literature `prior_scale` stands. Labs in an unknown unit are skipped
    outright; every convertible lab inside `window` overlays the curve whether or
    not it informed the fit.
    """
    lo, hi = window
    fitted: list[float] = []
    points: list[MeasurementPoint] = []
    for lab in labs:
        val = _to_serum_unit(lab.value, lab.unit, serum_unit)
        if val is None:  # unit we can't place on this curve
            continue
        modeled = modeled_level(groups, float(lab.taken_at), half_life_s)
        if modeled >= _CALIB_MIN_LEVEL:
            fitted.append(val / modeled)
        if lo <= lab.taken_at <= hi:
            points.append(MeasurementPoint(t=lab.taken_at, value=round(val, 1), note=lab.note))
    if fitted:
        return round(statistics.median(fitted), 4), len(fitted), points
    return prior_scale, 0, points


def modeled_curve(
    groups: Sequence[IntakeGroup],
    start: float,
    end: float,
    step_s: float,
    half_life_s: float,
) -> list[LevelPoint]:
    """Sample the summed curve over [start, end] every step_s; mg rounded to 2 dp.
    The groups share a start/end/step, so their sample timestamps line up."""
    group_curves = [curve_inputs(ev, start, end, step_s, half_life_s, ins) for ev, ins in groups]
    return [
        LevelPoint(t=int(group_curves[0][i][0]), mg=round(sum(gc[i][1] for gc in group_curves), 2))
        for i in range(len(group_curves[0]))
    ]


def trend_between(
    start: float, end: float, tolerance: float
) -> Literal["rising", "falling", "flat"]:
    """Direction of travel between two modeled levels (bar arrow).

    Relative to `start`, so the tolerance means the same thing for a 200 mg
    caffeine load and a 5 mg tablet. A rise from nothing is always rising:
    with `start` at zero there is no proportion to take, and a dose that has
    not begun absorbing yet is exactly the case the arrow exists for.
    """
    before, after = start, end
    if before <= 0:
        return "rising" if after > 0 else "flat"
    change = (after - before) / before
    if change > tolerance:
        return "rising"
    if change < -tolerance:
        return "falling"
    return "flat"
