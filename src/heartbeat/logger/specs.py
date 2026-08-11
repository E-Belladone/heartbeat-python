"""Substance catalogue and measurement specs: the kinetics model's data shapes.

Split out of `models.py` so this file can be published on its own. `models.py`
is the logger's whole API surface (food, hearth, mood, battery, presence) and
carries plenty that is nobody else's business; these five shapes plus their three
literals are the entire input to `kinetics.py` and `levels.py`, which are general
pharmacokinetics and useful to anyone.

`models.py` re-exports everything here, so importing either module works and no
call site had to change.

Keep this file free of anything personal. It describes a catalogue's *shape*, and
the moment it names what someone actually takes it stops being publishable.
"""

from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

__all__ = [
    "LevelPoint",
    "Measurement",
    "MeasurementPoint",
    "Palette",
    "SubstanceCategory",
    "SubstanceModel",
    "SubstanceSpec",
    "TemplateSpec",
]

Palette = Literal["love", "gold", "rose", "pine", "foam", "iris"]
"""Rose Pine role a substance curve draws in; the frontend maps it to a CSS var."""

SubstanceCategory = Literal["stimulant", "complement", "pharma", "recreational"]
"""Coarse group the dashboard's log filter buckets substances into."""

SubstanceModel = Literal["instant", "bateman", "flip_flop", "dual_peak", "none"]
"""Kinetics family a substance draws. First-order families (instant, bateman,
flip_flop) differ only in the half-life params (kinetics.py infers the shape);
`dual_peak` adds a second delayed absorption input for extended-release
products, so it carries `er_*` + `dose_split`. `none` is log-only (no curve),
for anything that isn't first-order (e.g. alcohol)."""


class SubstanceSpec(BaseModel):
    """Per-substance metadata, one row of substance.catalog."""

    model_family: SubstanceModel = "none"
    """Kinetics family; `params` (the half-lives below) is its per-family blob."""

    half_life_hours: float | None = Field(default=None, gt=0)
    """Elimination half-life for the decay graph.

    Only meaningful for first-order elimination (caffeine, most stimulants).
    Leave unset for substances that don't fit that model (e.g. alcohol is
    roughly zero-order): they can still be logged, just not curved.
    """

    absorption_half_life_hours: float | None = Field(default=None, gt=0)
    """First-order absorption half-life, when intake is not an instant bolus.

    Set it for routes with a real uptake ramp (depot injections, extended-release
    tablets, sublingual/vaginal) and each dose becomes a Bateman rise-then-fall
    instead of an instant jump. Setting it equal to half_life_hours picks the
    flip-flop limit that fits slow depot esters. Unset means instant absorption;
    only used alongside half_life_hours. For dual_peak this is the immediate-
    release input's absorption half-life.
    """

    er_absorption_half_life_hours: float | None = Field(default=None, gt=0)
    """dual_peak only: absorption half-life of the delayed extended-release input.
    Its dose fraction is 1 - dose_split, released after er_lag_hours."""

    er_lag_hours: float | None = Field(default=None, ge=0)
    """dual_peak only: delay before the extended-release input starts absorbing."""

    dose_split: float | None = Field(default=None, gt=0, lt=1)
    """dual_peak only: fraction of the dose on the immediate-release input; the
    rest (1 - dose_split) rides the delayed extended-release input."""

    fed_absorption_half_life_hours: float | None = Field(default=None, gt=0)
    """Slower absorption half-life for an intake taken with food; a fed intake
    swaps its uptake for this so the curve peaks later and lower. Needs the
    (fasted) absorption_half_life_hours as its baseline. Unset = food ignored."""

    label: str | None = None
    """Display name for the tiles and graph; falls back to the substance key."""

    color: Palette | None = None
    """Curve colour, a Rose Pine role; falls back to a default when unset."""

    category: SubstanceCategory | None = None
    """Group for the logger's category filter; None keeps it out of the filters."""

    unit: str = "mg"
    """Display unit for doses. Storage stays milligrams; this only relabels."""

    unit_per_mg: float = Field(default=1.0, gt=0)
    """Display units per mg (µg -> 1000, g -> 0.001): dose_mg * this = shown value."""

    serum_analyte: str | None = None
    """Measurement name this substance's curve maps to, enabling amplitude
    calibration: labs of this analyte scale the relative curve into real serum
    units. None keeps the curve literature-relative."""

    serum_scale: float | None = Field(default=None, gt=0)
    """Literature prior, serum_unit per relative curve unit: the fallback scale
    used until a usable lab exists. A lab overrides it with the fit s = C / L(t)."""

    serum_unit: str | None = None
    """Serum unit the calibrated curve reads in (e.g. "ng/mL")."""

    target_low: float | None = Field(default=None, gt=0)
    """Low end of the optional target band (in serum_unit)."""

    target_high: float | None = Field(default=None, gt=0)
    """High end of the optional target band; low must not exceed high."""

    @model_validator(mode="after")
    def _serum_complete(self) -> Self:
        """Calibration is all-or-nothing (analyte + prior scale + unit), a band
        needs that trio, and the band must be ordered."""
        trio = (self.serum_analyte, self.serum_scale, self.serum_unit)
        if any(v is not None for v in trio) and any(v is None for v in trio):
            raise ValueError("serum_analyte, serum_scale, serum_unit go together or not at all")
        has_band = self.target_low is not None or self.target_high is not None
        if has_band and self.serum_unit is None:
            raise ValueError("a target band needs serum_analyte/serum_scale/serum_unit set")
        if (
            self.target_low is not None
            and self.target_high is not None
            and self.target_low > self.target_high
        ):
            raise ValueError("target_low must not exceed target_high")
        return self

    @model_validator(mode="after")
    def _dual_peak_complete(self) -> Self:
        """dual_peak needs both absorption inputs fully specified, else the curve
        can't build the second peak. The er_* / dose_split fields are meaningless
        on any other family, so reject them there too."""
        dual = (
            self.er_absorption_half_life_hours,
            self.er_lag_hours,
            self.dose_split,
        )
        if self.model_family == "dual_peak":
            if self.half_life_hours is None or self.absorption_half_life_hours is None:
                raise ValueError("dual_peak needs half_life_hours and absorption_half_life_hours")
            if any(p is None for p in dual):
                raise ValueError(
                    "dual_peak needs er_absorption_half_life_hours, er_lag_hours, dose_split"
                )
        elif any(p is not None for p in dual):
            raise ValueError("er_*/dose_split are only valid on the dual_peak family")
        if (
            self.fed_absorption_half_life_hours is not None
            and self.absorption_half_life_hours is None
        ):
            raise ValueError("fed_absorption_half_life_hours needs absorption_half_life_hours set")
        return self


class TemplateSpec(BaseModel):
    """A named intake preset, e.g. espresso -> caffeine 80 mg."""

    substance: str
    dose_mg: float = Field(gt=0)
    label: str | None = None


class Measurement(BaseModel):
    """One stored lab/measurement reading: a labeled analyte value."""

    id: int
    taken_at: int
    """Unix seconds, UTC: when the sample was taken (a lab draw may be days ago)."""
    analyte: str
    value: float
    unit: str
    ref_low: float | None = None
    ref_high: float | None = None
    """The lab's reference interval, if known; either end may be absent."""
    note: str | None = None


class LevelPoint(BaseModel):
    t: int
    mg: float


class MeasurementPoint(BaseModel):
    """One analyte lab laid over a calibrated level curve: when it was drawn and
    its value in the curve's serum unit (converted if the lab used another)."""

    t: int
    value: float
    note: str | None = None
