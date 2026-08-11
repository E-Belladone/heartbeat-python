import pytest

from heartbeat.logger.kinetics import level_at_inputs
from heartbeat.logger.levels import (
    FED_WINDOW_AFTER_S,
    FED_WINDOW_BEFORE_S,
    calibrate_serum,
    infer_fed,
    inputs_for_spec,
    intake_groups,
    lookback_start,
    modeled_curve,
    modeled_level,
    trend_between,
)
from heartbeat.logger.specs import Measurement, SubstanceSpec

HL_H = 5.0  # elimination half-life, hours
ABS_H = 1.0  # absorption half-life, hours


def _spec(**kw: object) -> SubstanceSpec:
    return SubstanceSpec(**kw)  # type: ignore[arg-type]


# --- inputs_for_spec ---


def test_inputs_instant_when_no_absorption() -> None:
    hl, inputs, fed = inputs_for_spec(_spec(model_family="instant", half_life_hours=HL_H))
    assert hl == HL_H * 3600
    assert inputs == [(1.0, None, 0.0)]  # None absorption => instant bolus
    assert fed is None


def test_inputs_single_absorption_ramp() -> None:
    _, inputs, fed = inputs_for_spec(
        _spec(model_family="bateman", half_life_hours=HL_H, absorption_half_life_hours=ABS_H)
    )
    assert inputs == [(1.0, ABS_H * 3600, 0.0)]
    assert fed is None


def test_inputs_dual_peak_splits_into_two_delayed_inputs() -> None:
    _, inputs, fed = inputs_for_spec(
        _spec(
            model_family="dual_peak",
            half_life_hours=HL_H,
            absorption_half_life_hours=ABS_H,
            er_absorption_half_life_hours=2.0,
            er_lag_hours=3.0,
            dose_split=0.4,
        )
    )
    assert inputs == [
        (0.4, ABS_H * 3600, 0.0),  # immediate release
        (0.6, 2.0 * 3600, 3.0 * 3600),  # 1 - split, after er_lag
    ]
    assert fed is None


def test_inputs_fed_adds_a_slower_group() -> None:
    _, _, fed = inputs_for_spec(
        _spec(
            model_family="bateman",
            half_life_hours=HL_H,
            absorption_half_life_hours=ABS_H,
            fed_absorption_half_life_hours=4.0,
        )
    )
    assert fed == [(1.0, 4.0 * 3600, 0.0)]


def test_inputs_dual_peak_ignores_the_fed_flag() -> None:
    # food effects on an extended-release product aren't characterised
    _, _, fed = inputs_for_spec(
        _spec(
            model_family="dual_peak",
            half_life_hours=HL_H,
            absorption_half_life_hours=ABS_H,
            er_absorption_half_life_hours=2.0,
            er_lag_hours=3.0,
            dose_split=0.4,
            fed_absorption_half_life_hours=4.0,
        )
    )
    assert fed is None


def test_inputs_reject_a_substance_with_no_half_life() -> None:
    with pytest.raises(ValueError, match="no curve available"):
        inputs_for_spec(_spec(model_family="none"))


def test_inputs_reject_a_hand_broken_dual_peak_row() -> None:
    # the model validator normally guarantees the params; model_construct bypasses
    # it to mimic a hand-edited DB row, exercising the defensive guard
    broken = SubstanceSpec.model_construct(
        model_family="dual_peak", half_life_hours=HL_H, absorption_half_life_hours=ABS_H
    )
    with pytest.raises(ValueError, match="dual_peak params incomplete"):
        inputs_for_spec(broken)


# --- lookback_start ---


def test_lookback_reaches_back_by_the_slowest_span() -> None:
    hl = HL_H * 3600
    # elimination dominates: absorption ramp (1h) is shorter than the 5h half-life
    assert lookback_start(0.0, hl, [(1.0, ABS_H * 3600, 0.0)], None) == -14 * hl


def test_lookback_uses_absorption_plus_lag_when_it_is_slowest() -> None:
    hl = HL_H * 3600
    # a long er input: 4h absorption + 6h lag = 10h > the 5h elimination
    slow = 4 * 3600 + 6 * 3600
    inputs = [(0.5, 3600.0, 0.0), (0.5, 4 * 3600.0, 6 * 3600.0)]
    assert lookback_start(0.0, hl, inputs, None) == -14 * slow


# --- intake_groups ---


def test_groups_single_when_no_fed_uptake() -> None:
    intakes = [(0.0, 100.0, None), (10.0, 50.0, True)]
    groups = intake_groups(intakes, [(1.0, None, 0.0)], None)
    assert len(groups) == 1
    assert groups[0][0] == [(0.0, 100.0), (10.0, 50.0)]


def test_groups_split_fed_from_the_rest() -> None:
    fed_inputs = [(1.0, 4 * 3600.0, 0.0)]
    inputs = [(1.0, 3600.0, 0.0)]
    intakes = [
        (0.0, 100.0, False),  # fed -> slow group
        (10.0, 50.0, True),  # fasted -> default group
        (20.0, 25.0, None),  # unknown -> default group
    ]
    fed_group, rest_group = intake_groups(intakes, inputs, fed_inputs)
    assert fed_group == ([(0.0, 100.0)], fed_inputs)
    assert rest_group == ([(10.0, 50.0), (20.0, 25.0)], inputs)


# --- modeled_level / modeled_curve ---


def test_modeled_level_sums_the_groups() -> None:
    hl = HL_H * 3600
    inputs = [(1.0, None, 0.0)]
    fed_inputs = [(1.0, 4 * 3600.0, 0.0)]
    intakes = [(0.0, 100.0, False), (0.0, 40.0, True)]
    groups = intake_groups(intakes, inputs, fed_inputs)
    t = 2 * 3600.0
    expected = level_at_inputs([(0.0, 100.0)], t, hl, fed_inputs) + level_at_inputs(
        [(0.0, 40.0)], t, hl, inputs
    )
    assert modeled_level(groups, t, hl) == pytest.approx(expected)


def test_modeled_level_zero_with_no_intakes() -> None:
    groups = intake_groups([], [(1.0, None, 0.0)], None)
    assert modeled_level(groups, 1000.0, HL_H * 3600) == 0.0


def test_modeled_curve_samples_aligned_and_rounded() -> None:
    hl = HL_H * 3600
    groups = intake_groups([(0.0, 100.0, None)], [(1.0, None, 0.0)], None)
    step = 3600.0
    curve = modeled_curve(groups, 0.0, 4 * 3600.0, step, hl)
    assert [p.t for p in curve] == [0, 3600, 7200, 10800, 14400]  # both ends, step apart
    assert curve[0].mg == 100.0  # full dose at intake
    assert curve[1].mg == pytest.approx(100.0 * 0.5 ** (1 / HL_H), abs=0.01)  # one hour of decay
    assert all(round(p.mg, 2) == p.mg for p in curve)  # rounded to 2 dp


# --- calibrate_serum ---


def _lab(taken_at: int, value: float, unit: str = "pg/ml", note: str | None = None) -> Measurement:
    return Measurement(
        id=1, taken_at=taken_at, analyte="analyte-a", value=value, unit=unit, note=note
    )


def _groups_one_dose(dose_mg: float = 100.0) -> list:
    # instant bolus at t=0, so the modeled level at any t is analytic
    return intake_groups([(0.0, dose_mg, None)], [(1.0, None, 0.0)], None)


def test_calibrate_fits_median_scale_over_usable_labs() -> None:
    hl = HL_H * 3600
    groups = _groups_one_dose()
    t1, t2 = 3600, 7200
    l1, l2 = modeled_level(groups, t1, hl), modeled_level(groups, t2, hl)
    labs = [_lab(t1, l1 * 2.0), _lab(t2, l2 * 4.0)]  # per-lab scales 2 and 4
    scale, n, points = calibrate_serum(
        labs, groups, hl, serum_unit="pg/ml", prior_scale=87.0, window=(0.0, 10_000.0)
    )
    assert scale == pytest.approx(3.0)  # median of [2, 4]
    assert n == 2
    assert [p.t for p in points] == [t1, t2]


def test_calibrate_prior_stands_without_usable_labs() -> None:
    hl = HL_H * 3600
    # draw long before the dose: modeled level ~0, below the fit floor
    labs = [_lab(-30 * 86400, 250.0)]
    scale, n, points = calibrate_serum(
        labs, _groups_one_dose(), hl, serum_unit="pg/ml", prior_scale=87.0, window=(0.0, 1.0)
    )
    assert (scale, n) == (87.0, 0)
    assert points == []  # outside the window too


def test_calibrate_skips_unknown_units_entirely() -> None:
    hl = HL_H * 3600
    labs = [_lab(3600, 250.0, unit="nmol/l")]  # not in the conversion table
    scale, n, points = calibrate_serum(
        labs, _groups_one_dose(), hl, serum_unit="pg/ml", prior_scale=87.0, window=(0.0, 10_000.0)
    )
    assert (scale, n, points) == (87.0, 0, [])


def test_calibrate_converts_pmol_per_l() -> None:
    hl = HL_H * 3600
    groups = _groups_one_dose()
    t = 3600
    modeled = modeled_level(groups, t, hl)
    labs = [_lab(t, 1000.0, unit="pmol/L")]  # mixed case on purpose
    scale, n, points = calibrate_serum(
        labs, groups, hl, serum_unit="pg/mL", prior_scale=87.0, window=(0.0, 10_000.0)
    )
    assert n == 1
    assert scale == pytest.approx(round(1000.0 * 0.2724 / modeled, 4))
    assert points[0].value == pytest.approx(round(1000.0 * 0.2724, 1))


def test_calibrate_overlays_in_window_even_when_unfittable() -> None:
    hl = HL_H * 3600
    # no dose history around the draw (fit floor) but the draw is in-window
    labs = [_lab(-30 * 86400, 250.0, note="old panel")]
    scale, n, points = calibrate_serum(
        labs,
        _groups_one_dose(),
        hl,
        serum_unit="pg/ml",
        prior_scale=87.0,
        window=(-31 * 86400.0, 10_000.0),
    )
    assert (scale, n) == (87.0, 0)
    assert [(p.t, p.value, p.note) for p in points] == [(-30 * 86400, 250.0, "old panel")]


def test_trend_between_uses_a_relative_tolerance() -> None:
    # the same absolute wobble is noise on a big load and real movement on a
    # small one, which is why the tolerance is proportional
    assert trend_between(200.0, 201.0, 0.01) == "flat"
    assert trend_between(2.0, 2.5, 0.01) == "rising"
    assert trend_between(200.0, 150.0, 0.01) == "falling"


def test_trend_between_calls_a_rise_from_zero_rising() -> None:
    # a dose is exactly zero at the instant it is logged; with no proportion to
    # take, any climb has to count or the arrow would be flat when it matters
    assert trend_between(0.0, 0.4, 0.01) == "rising"
    assert trend_between(0.0, 0.0, 0.01) == "flat"


# --- fed/fasted inferred from food photos -----------------
# Nobody remembers to tick --fed, so without this every intake draws fasted.
# A food photo near an intake is the evidence; it arrives late (batch uploads),
# hence a read-time inference rather than a write-time stamp.

_T = 1_000_000.0


def test_infer_fed_marks_an_intake_with_a_meal_just_before() -> None:
    intakes = [(_T, 80.0, None)]
    assert infer_fed(intakes, [_T - 600]) == [(_T, 80.0, False)]


def test_infer_fed_leaves_an_intake_with_no_meal_nearby_alone() -> None:
    # still None, not True: "no evidence of food", which draws the same default
    # uptake it always did
    assert infer_fed([(_T, 80.0, None)], [_T - 10 * 3600]) == [(_T, 80.0, None)]


def test_infer_fed_ignores_a_meal_outside_the_window_on_either_side() -> None:
    just_too_early = _T - FED_WINDOW_BEFORE_S - 1
    just_too_late = _T + FED_WINDOW_AFTER_S + 1
    assert infer_fed([(_T, 80.0, None)], [just_too_early, just_too_late]) == [(_T, 80.0, None)]


def test_infer_fed_includes_the_window_edges() -> None:
    for edge in (_T - FED_WINDOW_BEFORE_S, _T + FED_WINDOW_AFTER_S):
        assert infer_fed([(_T, 80.0, None)], [edge]) == [(_T, 80.0, False)]


def test_infer_fed_never_overrides_a_hand_set_flag() -> None:
    # ticking --fasted next to a meal photo must stand: the human saw the plate
    assert infer_fed([(_T, 80.0, True)], [_T]) == [(_T, 80.0, True)]
    # and an explicit fed with no photo is equally untouched
    assert infer_fed([(_T, 80.0, False)], []) == [(_T, 80.0, False)]


def test_infer_fed_is_a_noop_with_no_meals() -> None:
    intakes = [(_T, 80.0, None), (_T + 3600, 40.0, True)]
    assert infer_fed(intakes, []) == intakes


def test_infer_fed_handles_unsorted_meal_times() -> None:
    # the store returns them ordered, but the pure function must not rely on it
    assert infer_fed([(_T, 80.0, None)], [_T + 50_000, _T - 300, _T - 90_000]) == [
        (_T, 80.0, False)
    ]


def test_infer_fed_resolves_each_intake_independently() -> None:
    intakes = [(_T, 80.0, None), (_T + 6 * 3600, 80.0, None)]
    assert infer_fed(intakes, [_T - 60]) == [(_T, 80.0, False), (_T + 6 * 3600, 80.0, None)]


def test_inferred_fed_intake_draws_the_slower_curve() -> None:
    # the whole point: inference has to actually change the superposition
    spec = SubstanceSpec(
        model_family="bateman",
        half_life_hours=5.0,
        absorption_half_life_hours=0.1,
        fed_absorption_half_life_hours=0.8,
    )
    half_life_s, inputs, fed_inputs = inputs_for_spec(spec)
    assert fed_inputs is not None
    raw = [(_T, 80.0, None)]
    fasted_groups = intake_groups(raw, inputs, fed_inputs)
    fed_groups = intake_groups(infer_fed(raw, [_T - 600]), inputs, fed_inputs)
    # 20 min in, the fed curve is still climbing while the fasted one has peaked
    t = _T + 20 * 60
    assert modeled_level(fed_groups, t, half_life_s) < modeled_level(fasted_groups, t, half_life_s)
