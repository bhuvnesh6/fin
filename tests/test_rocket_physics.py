"""
Tests for rocket_physics.py's low-level functions.

Every assertion here is checked against a value computed independently of
the function under test — either a standard-atmosphere reference value, a
hand-worked closed-form result, or a textbook formula transcribed directly
in the test (so a transcription bug in the implementation shows up as a
mismatch against the test's own independent arithmetic).
"""

import math

import pytest

from rocket_physics import (
    BodyParams,
    FinGeometry,
    FinMaterial,
    atmosphere,
    fin_area,
    fin_centroid_axial_offset,
    fin_cp_offset_from_root_le,
    fin_mass_kg,
    fin_set_cn_alpha,
    nose_cp,
    stability_margin_calibers,
)

# --------------------------------------------------------------------------
# atmosphere()
# --------------------------------------------------------------------------

class TestAtmosphere:
    def test_sea_level(self):
        a, p = atmosphere(0.0)
        # ISA sea level: speed of sound 340.29 m/s, pressure ratio 1.0
        assert a == pytest.approx(340.29, abs=0.05)
        assert p == pytest.approx(1.0, abs=1e-6)

    def test_tropopause_reference_values(self):
        # 11 km is the standard ISA tropopause: published reference values
        # are T=216.65 K, pressure ratio 0.2234, speed of sound 295.07 m/s.
        a, p = atmosphere(11000.0)
        assert p == pytest.approx(0.2234, abs=0.001)
        assert a == pytest.approx(295.07, abs=0.1)

    def test_pressure_decreases_with_altitude(self):
        _, p_low = atmosphere(0.0)
        _, p_mid = atmosphere(5000.0)
        _, p_high = atmosphere(10000.0)
        assert p_low > p_mid > p_high

    def test_clamped_above_11km(self):
        # troposphere model isn't valid above 11 km; altitude should clamp.
        result_11k = atmosphere(11000.0)
        result_20k = atmosphere(20000.0)
        assert result_11k == result_20k

    def test_clamped_below_zero(self):
        result_0 = atmosphere(0.0)
        result_negative = atmosphere(-500.0)
        assert result_0 == result_negative


# --------------------------------------------------------------------------
# fin_area()
# --------------------------------------------------------------------------

class TestFinArea:
    def test_trapezoid_area(self):
        # standard trapezoid area formula: 0.5 * (a + b) * h
        assert fin_area(Cr=0.2, Ct=0.1, s=0.15) == pytest.approx(0.0225)

    def test_rectangular_fin(self):
        # Cr == Ct reduces to a plain rectangle
        assert fin_area(Cr=0.1, Ct=0.1, s=0.2) == pytest.approx(0.02)

    def test_triangular_fin(self):
        # Ct == 0 reduces to a triangle: 0.5 * base * height
        assert fin_area(Cr=0.12, Ct=0.0, s=0.08) == pytest.approx(0.0048)

    def test_zero_span_is_zero_area(self):
        assert fin_area(Cr=0.2, Ct=0.1, s=0.0) == 0.0


# --------------------------------------------------------------------------
# fin_centroid_axial_offset()
# --------------------------------------------------------------------------

class TestFinCentroid:
    def test_swept_rectangular_fin_centroid(self):
        # For a rectangle (Cr == Ct), the local axial centroid at each span
        # station is x_le(y) + Cr/2, and x_le(y) ranges linearly from 0 to
        # Xr, averaging to Xr/2. So centroid = Xr/2 + Cr/2, independent of
        # span, for a rectangle.
        centroid = fin_centroid_axial_offset(Cr=0.1, Ct=0.1, Xr=0.05, s=0.2)
        assert centroid == pytest.approx(0.05 / 2 + 0.1 / 2, abs=1e-6)  # 0.075

    def test_unswept_rectangular_fin(self):
        centroid = fin_centroid_axial_offset(Cr=0.1, Ct=0.1, Xr=0.0, s=0.2)
        assert centroid == pytest.approx(0.05, abs=1e-6)  # half of root chord

    def test_triangular_fin_centroid(self):
        # A pure triangle (Ct=0, Xr=0, apex at tip) has its area centroid
        # at 1/3 of the root chord from the leading edge (standard result
        # for a triangle's centroid measured from its base-parallel apex).
        centroid = fin_centroid_axial_offset(Cr=0.3, Ct=0.0, Xr=0.0, s=0.2)
        assert centroid == pytest.approx(0.1, abs=1e-3)  # 0.3 / 3


# --------------------------------------------------------------------------
# fin_mass_kg()
# --------------------------------------------------------------------------

class TestFinMass:
    def test_known_mass(self):
        fin = FinGeometry(root_chord_m=0.1, tip_chord_m=0.05, span_m=0.08,
                           sweep_m=0.05, thickness_m=0.003, count=3)
        material = FinMaterial(name="test", density_kg_m3=680.0, shear_modulus_pa=1e9)
        # area = 0.5*(0.1+0.05)*0.08 = 0.006 m^2
        # mass  = 3 * 0.006 * 0.003 * 680 = 0.03672 kg
        assert fin_mass_kg(fin, material) == pytest.approx(0.03672, abs=1e-6)

    def test_mass_scales_linearly_with_count(self):
        material = FinMaterial(name="test", density_kg_m3=680.0, shear_modulus_pa=1e9)
        fin3 = FinGeometry(0.1, 0.05, 0.08, 0.05, 0.003, count=3)
        fin6 = FinGeometry(0.1, 0.05, 0.08, 0.05, 0.003, count=6)
        assert fin_mass_kg(fin6, material) == pytest.approx(2 * fin_mass_kg(fin3, material))


# --------------------------------------------------------------------------
# nose_cp()
# --------------------------------------------------------------------------

class TestNoseCp:
    @pytest.mark.parametrize("nose_type,expected_factor", [
        ("conical", 0.666),
        ("ogive", 0.466),
        ("parabolic", 0.5),
        ("elliptical", 0.333),
    ])
    def test_known_barrowman_factors(self, nose_type, expected_factor):
        body = BodyParams(diameter_m=0.1, nose_length_m=0.4, nose_type=nose_type)
        x_n, cn_n = nose_cp(body)
        assert x_n == pytest.approx(expected_factor * 0.4)
        assert cn_n == 2.0  # Barrowman: CN_alpha = 2.0 for any standard nose shape

    def test_unknown_nose_type_falls_back_to_ogive(self):
        body = BodyParams(diameter_m=0.1, nose_length_m=0.4, nose_type="unobtainium")
        x_n, _ = nose_cp(body)
        assert x_n == pytest.approx(0.466 * 0.4)


# --------------------------------------------------------------------------
# fin_set_cn_alpha()  and  fin_cp_offset_from_root_le()
# --------------------------------------------------------------------------

class TestFinAerodynamics:
    def test_cn_alpha_matches_hand_derivation(self):
        # Barrowman fin-set CN_alpha, worked by hand for round numbers:
        #   Cr=0.15, Ct=0.075, s=0.1, Xr=0.075, N=3, d=0.1
        #   Rt = 0.05
        #   Kfb = 1 + 0.05/(0.1+0.05) = 4/3
        #   denom = 1 + sqrt(1 + (2*0.075/0.225)^2) = 1 + sqrt(1 + (2/3)^2)
        #   CN_alpha = Kfb * 4*3*(0.1/0.1)^2 / denom = (4/3)*12 / denom = 16/denom
        fin = FinGeometry(root_chord_m=0.15, tip_chord_m=0.075, span_m=0.1,
                           sweep_m=0.075, thickness_m=0.003, count=3)
        cn_alpha, kfb = fin_set_cn_alpha(fin, body_diameter_m=0.1)

        denom = 1 + math.sqrt(1 + (2 * 0.075 / 0.225) ** 2)
        expected_cn = (4 / 3) * 12 / denom

        assert kfb == pytest.approx(4 / 3)
        assert cn_alpha == pytest.approx(expected_cn, rel=1e-6)

    def test_more_fins_increases_normal_force_slope(self):
        base = FinGeometry(0.15, 0.075, 0.1, 0.075, 0.003, count=3)
        more = FinGeometry(0.15, 0.075, 0.1, 0.075, 0.003, count=4)
        cn3, _ = fin_set_cn_alpha(base, body_diameter_m=0.1)
        cn4, _ = fin_set_cn_alpha(more, body_diameter_m=0.1)
        assert cn4 > cn3
        assert cn4 == pytest.approx(cn3 * 4 / 3)  # CN_alpha is linear in N

    def test_cp_offset_matches_hand_derivation(self):
        # Cr=0.2, Ct=0.1, Xr=0.1
        #   term1 = (0.1*(0.2+0.2)) / (3*0.3) = 0.04/0.9
        #   term2 = (1/6)*(0.3 - 0.02/0.3)
        expected = (0.1 * 0.4) / 0.9 + (1 / 6) * (0.3 - 0.02 / 0.3)
        offset = fin_cp_offset_from_root_le(Cr=0.2, Ct=0.1, Xr=0.1)
        assert offset == pytest.approx(expected, rel=1e-9)

    def test_unswept_rectangular_fin_cp_at_quarter_chord(self):
        # Cr == Ct, Xr == 0: Barrowman's formula reduces to the classic
        # quarter-chord point here, consistent with thin-airfoil theory
        # (term1 vanishes since Xr=0; term2 = (1/6)*(2*Cr - Cr/2) = Cr/4).
        offset = fin_cp_offset_from_root_le(Cr=0.2, Ct=0.2, Xr=0.0)
        assert offset == pytest.approx(0.05, abs=1e-9)  # 0.2 / 4


# --------------------------------------------------------------------------
# stability_margin_calibers()
# --------------------------------------------------------------------------

class TestStabilityMargin:
    def test_known_margin(self):
        # CP 1.5 diameters behind CG -> margin of 1.5 calibers
        margin = stability_margin_calibers(cp_m=2.0, cg_m=1.0, diameter_m=(1.0 / 1.5))
        assert margin == pytest.approx(1.5)

    def test_cp_ahead_of_cg_is_negative_margin(self):
        # unstable configuration: CP forward of CG
        margin = stability_margin_calibers(cp_m=0.5, cg_m=1.0, diameter_m=0.1)
        assert margin < 0
