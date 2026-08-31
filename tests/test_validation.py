"""
Tests for schemas.py — the request validation layer. These specifically
target the weakness the original review called out: manual dict parsing
with no real input validation. Every test here either confirms a valid
payload is accepted, or that an invalid one is rejected with a
ValidationError (which app.py turns into a 422 response).
"""

import pytest
from pydantic import ValidationError

from schemas import BoundsMMIn, DesignRequest, EvaluateRequest, GeometryMMIn


class TestDesignRequestValid:
    def test_valid_payload_is_accepted(self, sample_api_payload):
        req = DesignRequest.model_validate(sample_api_payload)
        assert req.body.diameter_mm == 98
        assert len(req.mass.components) == 3
        assert req.fins.material == "plywood_birch"

    def test_custom_material_is_accepted(self, sample_api_payload):
        sample_api_payload["fins"]["material"] = {
            "name": "custom_epoxy_glass", "density_kg_m3": 1900, "shear_modulus_pa": 4.3e9,
        }
        req = DesignRequest.model_validate(sample_api_payload)
        assert req.fins.material.name == "custom_epoxy_glass"

    def test_defaults_apply_when_optional_fields_omitted(self, sample_api_payload):
        del sample_api_payload["flight"]["safety_factor"]
        del sample_api_payload["target"]["margin_tolerance"]
        req = DesignRequest.model_validate(sample_api_payload)
        assert req.flight.safety_factor == 1.15
        assert req.target.margin_tolerance == 0.3


class TestDesignRequestInvalid:
    def test_missing_required_field_rejected(self, sample_api_payload):
        del sample_api_payload["body"]["diameter_mm"]
        with pytest.raises(ValidationError):
            DesignRequest.model_validate(sample_api_payload)

    def test_negative_diameter_rejected(self, sample_api_payload):
        sample_api_payload["body"]["diameter_mm"] = -50
        with pytest.raises(ValidationError):
            DesignRequest.model_validate(sample_api_payload)

    def test_zero_diameter_rejected(self, sample_api_payload):
        sample_api_payload["body"]["diameter_mm"] = 0
        with pytest.raises(ValidationError):
            DesignRequest.model_validate(sample_api_payload)

    def test_absurdly_large_diameter_rejected(self, sample_api_payload):
        sample_api_payload["body"]["diameter_mm"] = 999999
        with pytest.raises(ValidationError):
            DesignRequest.model_validate(sample_api_payload)

    def test_invalid_nose_type_rejected(self, sample_api_payload):
        sample_api_payload["body"]["nose_type"] = "banana"
        with pytest.raises(ValidationError):
            DesignRequest.model_validate(sample_api_payload)

    def test_unknown_material_preset_rejected(self, sample_api_payload):
        sample_api_payload["fins"]["material"] = "unobtainium"
        with pytest.raises(ValidationError):
            DesignRequest.model_validate(sample_api_payload)

    def test_empty_component_list_rejected(self, sample_api_payload):
        sample_api_payload["mass"]["components"] = []
        with pytest.raises(ValidationError):
            DesignRequest.model_validate(sample_api_payload)

    def test_negative_component_mass_rejected(self, sample_api_payload):
        sample_api_payload["mass"]["components"][0]["mass_g"] = -10
        with pytest.raises(ValidationError):
            DesignRequest.model_validate(sample_api_payload)

    def test_fin_count_out_of_range_rejected(self, sample_api_payload):
        sample_api_payload["fins"]["count"] = 2  # minimum is 3
        with pytest.raises(ValidationError):
            DesignRequest.model_validate(sample_api_payload)

        sample_api_payload["fins"]["count"] = 20  # maximum is 8
        with pytest.raises(ValidationError):
            DesignRequest.model_validate(sample_api_payload)

    def test_negative_max_velocity_rejected(self, sample_api_payload):
        sample_api_payload["flight"]["max_velocity_mps"] = -10
        with pytest.raises(ValidationError):
            DesignRequest.model_validate(sample_api_payload)

    def test_safety_factor_below_one_rejected(self, sample_api_payload):
        sample_api_payload["flight"]["safety_factor"] = 0.5
        with pytest.raises(ValidationError):
            DesignRequest.model_validate(sample_api_payload)

    def test_zero_margin_tolerance_rejected(self, sample_api_payload):
        sample_api_payload["target"]["margin_tolerance"] = 0
        with pytest.raises(ValidationError):
            DesignRequest.model_validate(sample_api_payload)

    def test_custom_material_missing_shear_modulus_rejected(self, sample_api_payload):
        sample_api_payload["fins"]["material"] = {"name": "x", "density_kg_m3": 1000}
        with pytest.raises(ValidationError):
            DesignRequest.model_validate(sample_api_payload)


class TestGeometryMMIn:
    def test_valid_geometry_accepted(self):
        g = GeometryMMIn(root_chord_mm=150, tip_chord_mm=60, span_mm=120,
                          sweep_mm=90, thickness_mm=3.5)
        assert g.root_chord_mm == 150

    def test_tip_chord_exceeding_root_chord_rejected(self):
        with pytest.raises(ValidationError):
            GeometryMMIn(root_chord_mm=50, tip_chord_mm=100, span_mm=120,
                         sweep_mm=90, thickness_mm=3.5)

    def test_zero_thickness_rejected(self):
        with pytest.raises(ValidationError):
            GeometryMMIn(root_chord_mm=150, tip_chord_mm=60, span_mm=120,
                         sweep_mm=90, thickness_mm=0)

    def test_absurd_thickness_rejected(self):
        with pytest.raises(ValidationError):
            GeometryMMIn(root_chord_mm=150, tip_chord_mm=60, span_mm=120,
                         sweep_mm=90, thickness_mm=500)


class TestEvaluateRequest:
    def test_requires_geometry_mm(self, sample_api_payload):
        # no geometry_mm supplied -> should be rejected
        with pytest.raises(ValidationError):
            EvaluateRequest.model_validate(sample_api_payload)

    def test_accepts_when_geometry_mm_present(self, sample_api_payload):
        sample_api_payload["fins"]["geometry_mm"] = {
            "root_chord_mm": 150, "tip_chord_mm": 60, "span_mm": 120,
            "sweep_mm": 90, "thickness_mm": 3.5,
        }
        req = EvaluateRequest.model_validate(sample_api_payload)
        assert req.fins.geometry_mm.root_chord_mm == 150


class TestBoundsMMIn:
    def test_valid_bounds_accepted(self):
        b = BoundsMMIn(
            root_chord_mm=(50, 200), tip_chord_mm=(0, 150),
            span_mm=(30, 150), sweep_mm=(0, 200), thickness_mm=(1, 12),
        )
        assert b.root_chord_mm == (50, 200)

    def test_inverted_range_rejected(self):
        with pytest.raises(ValidationError):
            BoundsMMIn(
                root_chord_mm=(200, 50),  # min > max
                tip_chord_mm=(0, 150), span_mm=(30, 150),
                sweep_mm=(0, 200), thickness_mm=(1, 12),
            )

    def test_equal_min_max_rejected(self):
        with pytest.raises(ValidationError):
            BoundsMMIn(
                root_chord_mm=(100, 100),
                tip_chord_mm=(0, 150), span_mm=(30, 150),
                sweep_mm=(0, 200), thickness_mm=(1, 12),
            )
