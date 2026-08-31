"""Shared fixtures for the Fin test suite."""

import sys
from pathlib import Path

import pytest

# Make the project root importable regardless of where pytest is invoked from.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rocket_physics import (
    BodyParams,
    DesignInputs,
    FinMaterial,
    FlightParams,
    MassComponent,
)


@pytest.fixture
def sample_body() -> BodyParams:
    return BodyParams(diameter_m=0.098, nose_length_m=0.35, nose_type="ogive")


@pytest.fixture
def sample_material() -> FinMaterial:
    return FinMaterial(name="plywood_birch", density_kg_m3=680.0, shear_modulus_pa=2.8e9)


@pytest.fixture
def sample_flight() -> FlightParams:
    return FlightParams(max_velocity_m_s=250.0, altitude_m=500.0, flutter_safety_factor=1.15)


@pytest.fixture
def sample_components() -> list[MassComponent]:
    return [
        MassComponent("nose+avionics", 0.240, 0.180),
        MassComponent("body/payload", 0.420, 0.700),
        MassComponent("motor", 0.350, 1.320),
    ]


@pytest.fixture
def sample_design(sample_body, sample_components, sample_material, sample_flight) -> DesignInputs:
    return DesignInputs(
        body=sample_body,
        components=sample_components,
        fin_position_from_nose_m=1.35,
        fin_count=3,
        material=sample_material,
        flight=sample_flight,
        target_margin_calibers=1.5,
        margin_tolerance_calibers=0.3,
    )


@pytest.fixture
def sample_api_payload() -> dict:
    """A valid request body for /api/optimize and (with geometry_mm added)
    /api/evaluate."""
    return {
        "body": {"diameter_mm": 98, "nose_length_mm": 350, "nose_type": "ogive"},
        "mass": {"components": [
            {"name": "nose+avionics", "mass_g": 240, "cg_from_nose_mm": 180},
            {"name": "body/payload", "mass_g": 420, "cg_from_nose_mm": 700},
            {"name": "motor", "mass_g": 350, "cg_from_nose_mm": 1320},
        ]},
        "fins": {"count": 3, "position_from_nose_mm": 1350, "material": "plywood_birch"},
        "flight": {"max_velocity_mps": 250, "altitude_m": 500, "safety_factor": 1.15},
        "target": {"stability_margin_calibers": 1.5, "margin_tolerance": 0.3},
    }
