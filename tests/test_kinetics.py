import math

import pytest

from heartbeat.logger.kinetics import curve, curve_inputs, level_at, level_at_inputs

HL = 5 * 3600  # caffeine-ish half-life in seconds
ABS = 3600.0  # 1h absorption half-life


def test_nothing_before_intake() -> None:
    assert level_at([(1000.0, 160.0)], t=999.0, half_life_s=HL) == 0.0


def test_full_dose_at_intake_time() -> None:
    assert level_at([(1000.0, 160.0)], t=1000.0, half_life_s=HL) == 160.0


def test_halves_after_one_half_life() -> None:
    assert level_at([(0.0, 160.0)], t=HL, half_life_s=HL) == pytest.approx(80.0)
    assert level_at([(0.0, 160.0)], t=2 * HL, half_life_s=HL) == pytest.approx(40.0)


def test_doses_stack() -> None:
    events = [(0.0, 160.0), (float(HL), 80.0)]
    # first dose has halved, second just landed
    assert level_at(events, t=HL, half_life_s=HL) == pytest.approx(160.0)


def test_curve_samples_both_ends() -> None:
    points = curve([(0.0, 100.0)], start=0.0, end=3600.0, step_s=900.0, half_life_s=HL)
    assert [t for t, _ in points] == [0.0, 900.0, 1800.0, 2700.0, 3600.0]
    assert points[0][1] == pytest.approx(100.0)


def test_curve_decays_monotonically_without_new_doses() -> None:
    points = curve([(0.0, 100.0)], start=0.0, end=8 * 3600, step_s=1800.0, half_life_s=HL)
    levels = [mg for _, mg in points]
    assert levels == sorted(levels, reverse=True)
    assert levels[-1] < 40.0


# --- first-order absorption (Bateman rise-then-fall) ---


def test_absorption_starts_at_zero_and_rises() -> None:
    # an uptake ramp means the dose is not fully present at intake
    assert level_at([(0.0, 100.0)], t=0.0, half_life_s=HL, absorption_half_life_s=ABS) == 0.0
    assert level_at([(0.0, 100.0)], t=600.0, half_life_s=HL, absorption_half_life_s=ABS) > 0.0


def test_absorption_peaks_then_falls() -> None:
    events = [(0.0, 100.0)]
    ka, ke = math.log(2) / ABS, math.log(2) / HL
    tmax = math.log(ka / ke) / (ka - ke)  # Bateman peak time
    peak = level_at(events, tmax, half_life_s=HL, absorption_half_life_s=ABS)
    before = level_at(events, tmax - 900, half_life_s=HL, absorption_half_life_s=ABS)
    after = level_at(events, tmax + 900, half_life_s=HL, absorption_half_life_s=ABS)
    assert before < peak and after < peak
    # with bioavailability folded to 1, the peak still sits below the dose
    assert 0 < peak < 100.0


def test_flip_flop_equal_rates_peak_at_inverse_rate() -> None:
    # depot limit: absorption == elimination -> dose*k*t*e^(-k t), peaks at 1/k = dose/e
    events = [(0.0, 100.0)]
    ke = math.log(2) / HL
    peak = level_at(events, 1 / ke, half_life_s=HL, absorption_half_life_s=HL)
    assert peak == pytest.approx(100.0 / math.e, rel=1e-6)
    assert level_at(events, 1 / ke - 1800, half_life_s=HL, absorption_half_life_s=HL) < peak


def test_bateman_stays_finite_across_flip_flop_boundary() -> None:
    # just outside the equal-rate window the general 1/(ka-ke) formula must not
    # explode; it should land close to the equal-rate limit it hands off to
    events = [(0.0, 100.0)]
    tmax = HL / math.log(2)  # = 1/ke
    equal = level_at(events, tmax, half_life_s=HL, absorption_half_life_s=HL)
    near = level_at(events, tmax, half_life_s=HL, absorption_half_life_s=HL * 1.01)
    assert near == pytest.approx(equal, rel=0.02)


def test_absorption_doses_stack() -> None:
    a = level_at([(0.0, 100.0)], t=2 * ABS, half_life_s=HL, absorption_half_life_s=ABS)
    b = level_at([(ABS, 100.0)], t=2 * ABS, half_life_s=HL, absorption_half_life_s=ABS)
    both = level_at(
        [(0.0, 100.0), (ABS, 100.0)], t=2 * ABS, half_life_s=HL, absorption_half_life_s=ABS
    )
    assert both == pytest.approx(a + b)


def test_curve_threads_absorption_and_humps() -> None:
    points = curve(
        [(0.0, 100.0)],
        start=0.0,
        end=4 * 3600,
        step_s=600.0,
        half_life_s=HL,
        absorption_half_life_s=ABS,
    )
    levels = [mg for _, mg in points]
    assert levels[0] == 0.0  # rises from zero at intake
    assert max(levels) > levels[0]  # humps up before it decays
    assert max(levels) not in (levels[0], levels[-1])  # peak is interior


# --- dual-peak / extended-release ---

# back-fit params: shared t½ 2.5 h, IR uptake 0.5 h, ER uptake 1.8 h after 4 h lag
FOC_KE_HL = 2.5 * 3600
FOC_INPUTS = [(0.5, 0.5 * 3600, 0.0), (0.5, 1.8 * 3600, 4.0 * 3600)]


def _local_maxima(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    return [
        points[i]
        for i in range(1, len(points) - 1)
        if points[i][1] > points[i - 1][1] and points[i][1] >= points[i + 1][1]
    ]


def test_single_input_matches_plain_bateman() -> None:
    # one full-dose input with no lag is exactly the single-input Bateman
    one = level_at_inputs([(0.0, 100.0)], t=2 * ABS, half_life_s=HL, inputs=[(1.0, ABS, 0.0)])
    assert one == pytest.approx(
        level_at([(0.0, 100.0)], t=2 * ABS, half_life_s=HL, absorption_half_life_s=ABS)
    )


def test_split_inputs_same_rate_sum_to_whole() -> None:
    # splitting a dose across two identical (no-lag) inputs changes nothing
    split = level_at_inputs(
        [(0.0, 100.0)], t=ABS, half_life_s=HL, inputs=[(0.3, ABS, 0.0), (0.7, ABS, 0.0)]
    )
    whole = level_at([(0.0, 100.0)], t=ABS, half_life_s=HL, absorption_half_life_s=ABS)
    assert split == pytest.approx(whole)


def test_dual_peak_is_bimodal_at_the_label_anchors() -> None:
    # the whole point of the family: two plasma peaks, tmax1 ~1.5 h and tmax2 ~6.5 h
    points = curve_inputs(
        [(0.0, 10.0)],
        start=0.0,
        end=12 * 3600,
        step_s=60.0,
        half_life_s=FOC_KE_HL,
        inputs=FOC_INPUTS,
    )
    peaks = _local_maxima(points)
    assert len(peaks) == 2
    (t1, c1), (t2, c2) = peaks
    assert t1 / 3600 == pytest.approx(1.5, abs=0.5)  # IR peak, anchor tmax1 ~1.5 h
    assert 4.5 <= t2 / 3600 <= 7.0  # ER peak, anchor tmax2 range 4.5-7 h
    assert c2 < c1  # second peak is the lower one (label anchor Cmax2 < Cmax1)


def test_dual_peak_er_input_waits_for_its_lag() -> None:
    # before the ER lag only the IR half is absorbing, so dropping the ER input
    # changes nothing yet; well after the lag it must matter
    early = 2 * 3600.0
    late = 8 * 3600.0
    ir_only = [(0.5, 0.5 * 3600, 0.0)]
    assert level_at_inputs([(0.0, 10.0)], early, FOC_KE_HL, FOC_INPUTS) == pytest.approx(
        level_at_inputs([(0.0, 10.0)], early, FOC_KE_HL, ir_only)
    )
    assert level_at_inputs([(0.0, 10.0)], late, FOC_KE_HL, FOC_INPUTS) > level_at_inputs(
        [(0.0, 10.0)], late, FOC_KE_HL, ir_only
    )


def test_dual_peak_doses_stack() -> None:
    a = level_at_inputs([(0.0, 10.0)], 5 * 3600.0, FOC_KE_HL, FOC_INPUTS)
    b = level_at_inputs([(3 * 3600.0, 10.0)], 5 * 3600.0, FOC_KE_HL, FOC_INPUTS)
    both = level_at_inputs([(0.0, 10.0), (3 * 3600.0, 10.0)], 5 * 3600.0, FOC_KE_HL, FOC_INPUTS)
    assert both == pytest.approx(a + b)
