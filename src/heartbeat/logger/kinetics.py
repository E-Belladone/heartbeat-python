"""Pure pharmacokinetics for the "how much is in my system" graphs.

Deliberately not a medical model. Time is plain unix seconds passed in by the
caller so everything here stays deterministic.

Each intake contributes a curve chosen by the substance's parameters:

* No absorption half-life -> instant absorption: the whole dose is present at
  intake and decays by first-order elimination. Fine for a fast oral hit taken
  as an idealised bolus; the original caffeine/melatonin behaviour.
* An absorption half-life -> a Bateman curve: the dose enters through a
  first-order absorption compartment and leaves by first-order elimination, so
  the level ramps to a peak then falls. Depot injections, extended-release
  tablets, and sublingual/vaginal routes only read truthfully this way. When the
  absorption and elimination rates coincide (the flip-flop limit that fits slow
  depot esters) the two exponentials collapse to dose * k * t * e^(-k t), which
  peaks at t = 1 / k.

Amounts are milligrams of the administered dose; bioavailability and volume of
distribution are folded to 1, so the curves are a personal relative tracker,
not serum concentrations.

An intake can absorb through more than one parallel first-order input: a
dual-peak / extended-release product splits its dose across inputs that each
carry their own absorption rate and release delay, feeding one shared
elimination. A 50/50 immediate + delayed-release capsule is the motivating
case: two plasma peaks some hours apart from one swallow. Because every family here is first-order
and so linear, an input is just a fraction of a lag-shifted Bateman hump and the
whole curve is their superposition; `level_at`/`curve` are the single-input
convenience over the general `level_at_inputs`/`curve_inputs`.
"""

import math
from collections.abc import Iterable, Sequence

__all__ = ["curve", "curve_inputs", "level_at", "level_at_inputs"]

Event = tuple[float, float]
"""(taken_at unix seconds, dose_mg)"""

Input = tuple[float, float | None, float]
"""One absorption input of an intake: (dose_fraction, absorption_half_life_s or
None for instant, lag_s before this input releases)."""

# within this relative gap the Bateman denominator (ka - ke) is numerically
# unstable; fall back to the exact equal-rate limit instead
_FLIP_FLOP_EPS = 1e-3

_ResolvedInput = tuple[float, float | None, float]
"""(dose_fraction, absorption rate ka or None, lag_s): an Input with its
half-life converted to a rate constant once, ahead of sampling."""


def _contribution(dose_mg: float, elapsed_s: float, ke: float, ka: float | None) -> float:
    if elapsed_s < 0:
        return 0.0
    if ka is None:  # instant absorption: whole dose present at intake
        return dose_mg * math.exp(-ke * elapsed_s)
    if abs(ka - ke) <= _FLIP_FLOP_EPS * ke:  # equal-rate (flip-flop depot) limit
        return dose_mg * ke * elapsed_s * math.exp(-ke * elapsed_s)
    return dose_mg * ka / (ka - ke) * (math.exp(-ke * elapsed_s) - math.exp(-ka * elapsed_s))


def _resolve(inputs: Iterable[Input]) -> list[_ResolvedInput]:
    return [
        (fraction, (math.log(2) / abs_s if abs_s else None), lag_s)
        for fraction, abs_s, lag_s in inputs
    ]


def _level(events: list[Event], t: float, ke: float, resolved: Sequence[_ResolvedInput]) -> float:
    return sum(
        fraction * _contribution(dose, t - taken - lag_s, ke, ka)
        for taken, dose in events
        for fraction, ka, lag_s in resolved
    )


def level_at_inputs(
    events: Iterable[Event],
    t: float,
    half_life_s: float,
    inputs: Iterable[Input],
) -> float:
    """Milligrams still in the system at time t, summed over all intakes and each
    intake's parallel absorption inputs."""
    ke = math.log(2) / half_life_s
    return _level(list(events), t, ke, _resolve(inputs))


def curve_inputs(
    events: Iterable[Event],
    start: float,
    end: float,
    step_s: float,
    half_life_s: float,
    inputs: Iterable[Input],
) -> list[tuple[float, float]]:
    """Sample level_at_inputs over [start, end] every step_s (both ends included)."""
    materialized = list(events)
    ke = math.log(2) / half_life_s
    resolved = _resolve(inputs)
    steps = int((end - start) // step_s)
    return [
        (t, _level(materialized, t, ke, resolved))
        for i in range(steps + 1)
        if (t := start + i * step_s) <= end
    ]


def level_at(
    events: Iterable[Event],
    t: float,
    half_life_s: float,
    absorption_half_life_s: float | None = None,
) -> float:
    """Single-input level: the whole dose through one first-order absorption."""
    return level_at_inputs(events, t, half_life_s, [(1.0, absorption_half_life_s, 0.0)])


def curve(
    events: Iterable[Event],
    start: float,
    end: float,
    step_s: float,
    half_life_s: float,
    absorption_half_life_s: float | None = None,
) -> list[tuple[float, float]]:
    """Sample level_at over [start, end] every step_s (both ends included)."""
    return curve_inputs(
        events, start, end, step_s, half_life_s, [(1.0, absorption_half_life_s, 0.0)]
    )
