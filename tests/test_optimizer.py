"""
Tests for optimize_fins() — checking the *behavior* of the optimizer
(constraint satisfaction), not just that it runs without raising.
"""

import pytest

from rocket_physics import (
    FinGeometry,
    default_bounds,
    evaluate_design,
    optimize_fins,
)


class TestOptimizerConstraints:
    def test_returns_valid_geometry(self, sample_design):
        result = optimize_fins(sample_design)
        fg = result["fin_geometry"]
        assert fg["root_chord_m"] > 0
        assert fg["span_m"] > 0
        assert fg["thickness_m"] > 0
        assert 0 <= fg["tip_chord_m"] <= fg["root_chord_m"]
        assert fg["count"] == sample_design.fin_count

    def test_stability_margin_within_requested_tolerance(self, sample_design):
        result = optimize_fins(sample_design)
        margin = result["stability_margin_calibers"]
        lo = sample_design.target_margin_calibers - sample_design.margin_tolerance_calibers
        hi = sample_design.target_margin_calibers + sample_design.margin_tolerance_calibers
        # small numerical slack for the local-optimizer's tolerance
        assert lo - 1e-2 <= margin <= hi + 1e-2

    def test_flutter_velocity_satisfies_safety_requirement(self, sample_design):
        result = optimize_fins(sample_design)
        vf = result["flutter"]["flutter_velocity_m_s"]
        required = result["flutter_required_velocity_m_s"]
        assert vf >= required - 1e-6

    def test_fin_dimensions_remain_within_bounds(self, sample_design):
        result = optimize_fins(sample_design)
        fg = result["fin_geometry"]
        bounds = default_bounds(sample_design)
        eps = 1e-6
        assert bounds["root_chord_m"][0] - eps <= fg["root_chord_m"] <= bounds["root_chord_m"][1] + eps
        assert bounds["span_m"][0] - eps <= fg["span_m"] <= bounds["span_m"][1] + eps
        assert bounds["thickness_m"][0] - eps <= fg["thickness_m"] <= bounds["thickness_m"][1] + eps

    def test_custom_bounds_are_respected(self, sample_design):
        tight_bounds = {
            "root_chord_m": (0.08, 0.10),
            "tip_chord_m": (0.0, 0.05),
            "span_m": (0.05, 0.07),
            "sweep_m": (0.0, 0.05),
            "thickness_m": (0.002, 0.004),
        }
        sample_design.bounds = tight_bounds
        result = optimize_fins(sample_design)
        fg = result["fin_geometry"]
        eps = 1e-6
        assert tight_bounds["root_chord_m"][0] - eps <= fg["root_chord_m"] <= tight_bounds["root_chord_m"][1] + eps
        assert tight_bounds["span_m"][0] - eps <= fg["span_m"] <= tight_bounds["span_m"][1] + eps

    def test_optimizer_result_is_internally_consistent(self, sample_design):
        """Re-evaluating the returned geometry independently should match
        the optimizer's own reported stability margin and flutter numbers —
        i.e. evaluate_design() and optimize_fins() must agree."""
        result = optimize_fins(sample_design)
        fg = result["fin_geometry"]
        fin = FinGeometry(
            root_chord_m=fg["root_chord_m"], tip_chord_m=fg["tip_chord_m"],
            span_m=fg["span_m"], sweep_m=fg["sweep_m"],
            thickness_m=fg["thickness_m"], count=fg["count"],
        )
        recheck = evaluate_design(sample_design, fin)
        assert recheck["stability_margin_calibers"] == pytest.approx(
            result["stability_margin_calibers"], abs=1e-9
        )
        assert recheck["flutter"]["flutter_velocity_m_s"] == pytest.approx(
            result["flutter"]["flutter_velocity_m_s"], abs=1e-9
        )

    def test_tighter_margin_tolerance_still_converges(self, sample_design):
        sample_design.margin_tolerance_calibers = 0.1
        result = optimize_fins(sample_design)
        lo = sample_design.target_margin_calibers - 0.1
        hi = sample_design.target_margin_calibers + 0.1
        assert lo - 1e-2 <= result["stability_margin_calibers"] <= hi + 1e-2

    def test_weaker_material_produces_thicker_or_heavier_fins(self, sample_design):
        """A material with much lower shear modulus should need a thicker
        (or otherwise beefier) fin to clear the same flutter requirement —
        this is a sanity check that the flutter constraint is actually
        doing something, not a no-op."""
        from rocket_physics import FinMaterial

        strong = optimize_fins(sample_design)

        sample_design.material = FinMaterial(
            name="balsa", density_kg_m3=170.0, shear_modulus_pa=4.0e8
        )
        weak = optimize_fins(sample_design)

        # Both must still satisfy their own flutter requirement...
        assert strong["flutter_margin_ok"]
        assert weak["flutter_margin_ok"]
        # ...and the weaker material should need more thickness relative
        # to its chord (or simply a thicker fin) to get there.
        assert (weak["fin_geometry"]["thickness_m"] >= strong["fin_geometry"]["thickness_m"] - 1e-6)


class TestOptimizerReporting:
    def test_optimizer_metadata_present(self, sample_design):
        result = optimize_fins(sample_design)
        assert "optimizer" in result
        assert "bounds_used" in result["optimizer"]
        assert "target_margin_window_calibers" in result["optimizer"]
        lo, hi = result["optimizer"]["target_margin_window_calibers"]
        assert lo < hi

    def test_fin_set_mass_is_positive(self, sample_design):
        result = optimize_fins(sample_design)
        assert result["fin_set_mass_kg"] > 0
