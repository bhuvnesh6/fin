"""
schemas.py

Pydantic request models for the Fin API. These are the single source of
truth for what a valid request looks like — invalid requests are rejected
here, before they ever reach rocket_physics.py, with a structured 422
response describing exactly what was wrong.

All physical quantities at this boundary are in the same units the
frontend uses (mm, g, m/s, Pa) — app.py converts to SI when building the
internal `rocket_physics.DesignInputs` object.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

NoseType = Literal["ogive", "conical", "parabolic", "elliptical"]

MaterialPresetName = Literal[
    "balsa", "basswood", "plywood_birch", "fiberglass_g10", "carbon_fiber", "acrylic",
]


class BodyIn(BaseModel):
    diameter_mm: float = Field(..., gt=0, le=2000, description="Body tube outer diameter")
    nose_length_mm: float = Field(..., gt=0, le=5000)
    nose_type: NoseType = "ogive"


class MassComponentIn(BaseModel):
    name: str = "component"
    mass_g: float = Field(..., ge=0)
    cg_from_nose_mm: float = Field(..., ge=0)


class MassIn(BaseModel):
    components: list[MassComponentIn] = Field(..., min_length=1)


class MaterialCustomIn(BaseModel):
    name: str = "custom"
    density_kg_m3: float = Field(..., gt=0, le=20000)
    shear_modulus_pa: float = Field(..., gt=0, le=1e12)


class GeometryMMIn(BaseModel):
    """An explicit fin geometry, used by /api/evaluate."""
    root_chord_mm: float = Field(..., gt=0)
    tip_chord_mm: float = Field(..., ge=0)
    span_mm: float = Field(..., gt=0)
    sweep_mm: float = Field(..., ge=0)
    thickness_mm: float = Field(..., gt=0, le=50)

    @model_validator(mode="after")
    def tip_within_root(self):
        if self.tip_chord_mm > self.root_chord_mm:
            raise ValueError("tip_chord_mm cannot exceed root_chord_mm")
        return self


class FinsIn(BaseModel):
    count: int = Field(3, ge=3, le=8)
    position_from_nose_mm: float = Field(..., gt=0)
    material: MaterialPresetName | MaterialCustomIn
    geometry_mm: GeometryMMIn | None = None


class FlightIn(BaseModel):
    max_velocity_mps: float = Field(..., gt=0, le=3000)
    altitude_m: float = Field(0.0, ge=0, le=11000)
    safety_factor: float = Field(1.15, ge=1.0, le=5.0)


class TargetIn(BaseModel):
    stability_margin_calibers: float = Field(..., ge=-2, le=10)
    margin_tolerance: float = Field(0.3, gt=0, le=5)


class BoundsRange(BaseModel):
    min_mm: float = Field(..., ge=0)
    max_mm: float = Field(..., gt=0)

    @model_validator(mode="after")
    def min_below_max(self):
        if self.min_mm >= self.max_mm:
            raise ValueError("min_mm must be less than max_mm")
        return self


class BoundsMMIn(BaseModel):
    root_chord_mm: tuple[float, float]
    tip_chord_mm: tuple[float, float]
    span_mm: tuple[float, float]
    sweep_mm: tuple[float, float]
    thickness_mm: tuple[float, float]

    @field_validator(
        "root_chord_mm", "tip_chord_mm", "span_mm", "sweep_mm", "thickness_mm"
    )
    @classmethod
    def check_range(cls, v: tuple[float, float]) -> tuple[float, float]:
        lo, hi = v
        if lo < 0 or hi <= lo:
            raise ValueError("bounds must be [min, max] with 0 <= min < max")
        return v


class DesignRequest(BaseModel):
    """Full input for /api/optimize."""
    body: BodyIn
    mass: MassIn
    fins: FinsIn
    flight: FlightIn
    target: TargetIn
    bounds_mm: BoundsMMIn | None = None


class EvaluateRequest(DesignRequest):
    """Same as DesignRequest, but requires an explicit fin geometry since
    no optimization is being run."""

    @model_validator(mode="after")
    def require_geometry(self):
        if self.fins.geometry_mm is None:
            raise ValueError("fins.geometry_mm is required for /api/evaluate")
        return self
