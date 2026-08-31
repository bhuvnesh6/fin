"""
rocket_physics.py

Core aerodynamic and structural model for a trapezoidal-fin, single body-tube
rocket, plus a bounded optimizer that searches fin geometry for the lightest
fin set that satisfies a target stability margin and a flutter-speed margin.

Methods used (standard, widely published methods for amateur/model rocketry —
not a substitute for a full aeroelastic / CFD analysis on high-power or
supersonic vehicles):

  * Center of pressure: Barrowman's equations (Barrowman & Barrowman, 1966;
    "The Theoretical Prediction of the Center of Pressure", NAR TR-11).
  * Fin flutter boundary: the semi-empirical NACA-derived equation commonly
    used across amateur rocketry (see e.g. Apogee Components Peak-of-Flight
    Newsletter #348, "Fin Flutter Analysis", and OpenRocket's technical
    documentation, both of which trace back to the same NACA source).
  * Standard atmosphere: ISA troposphere model (valid to 11 km).

All internal calculations are SI (meters, kilograms, pascals, seconds).
The Flask layer is responsible for unit conversion at the boundary.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.optimize import NonlinearConstraint, differential_evolution, minimize

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

GAMMA_AIR = 1.4          # ratio of specific heats for air
R_AIR = 287.05           # J/(kg*K) specific gas constant for dry air
T0_ISA = 288.15          # K, sea level standard temperature
P0_ISA = 101325.0        # Pa, sea level standard pressure
LAPSE_RATE = 0.0065      # K/m, troposphere lapse rate
G0 = 9.80665             # m/s^2

NOSE_CP_FACTORS = {
    # fraction of nose length, distance from the nose tip to nose CP
    "conical": 0.666,
    "ogive": 0.466,        # tangent ogive (typical, standard Barrowman value)
    "parabolic": 0.5,
    "elliptical": 0.333,
}


# --------------------------------------------------------------------------
# Atmosphere
# --------------------------------------------------------------------------

def atmosphere(altitude_m: float) -> tuple[float, float]:
    """Return (speed_of_sound_m_s, pressure_ratio_P_over_P0) at a given
    altitude using the ISA troposphere model. Clamped to 11 km (~36,000 ft),
    which covers essentially all model/high-power rocket flights."""
    h = max(0.0, min(altitude_m, 11000.0))
    temp = T0_ISA - LAPSE_RATE * h
    pressure_ratio = (temp / T0_ISA) ** 5.2561
    speed_of_sound = math.sqrt(GAMMA_AIR * R_AIR * temp)
    return speed_of_sound, pressure_ratio


# --------------------------------------------------------------------------
# Data containers
# --------------------------------------------------------------------------

@dataclass
class MassComponent:
    name: str
    mass_kg: float
    cg_from_nose_m: float


@dataclass
class BodyParams:
    diameter_m: float
    nose_length_m: float
    nose_type: str = "ogive"


@dataclass
class FinMaterial:
    name: str
    density_kg_m3: float
    shear_modulus_pa: float


@dataclass
class FlightParams:
    max_velocity_m_s: float
    altitude_m: float = 0.0
    flutter_safety_factor: float = 1.15


@dataclass
class FinGeometry:
    root_chord_m: float
    tip_chord_m: float
    span_m: float          # exposed semi-span (body surface to tip)
    sweep_m: float          # axial distance, root LE to tip LE
    thickness_m: float
    count: int = 3


@dataclass
class DesignInputs:
    body: BodyParams
    components: list[MassComponent]
    fin_position_from_nose_m: float   # axial location of fin root LE
    fin_count: int
    material: FinMaterial
    flight: FlightParams
    target_margin_calibers: float
    margin_tolerance_calibers: float = 0.3
    bounds: dict | None = None     # optional override of search bounds


# --------------------------------------------------------------------------
# Fin geometry helpers
# --------------------------------------------------------------------------

def fin_area(Cr: float, Ct: float, s: float) -> float:
    """Planform area of a single trapezoidal fin."""
    return 0.5 * (Cr + Ct) * s


def fin_centroid_axial_offset(Cr: float, Ct: float, Xr: float, s: float) -> float:
    """Axial distance from the fin root leading edge to the area centroid
    of a single fin, found by numerical integration over the span so the
    result stays correct for any (Cr, Ct, Xr, s) combination."""
    n = 200
    y = np.linspace(0.0, s, n)
    chord = Cr - (Cr - Ct) * (y / s if s > 0 else 0)
    x_le = Xr * (y / s if s > 0 else 0)
    x_local_centroid = x_le + chord / 2.0
    # area-weighted centroid: integrate (x * chord) dy / integrate(chord) dy
    num = np.trapezoid(x_local_centroid * chord, y)
    den = np.trapezoid(chord, y)
    return float(num / den) if den > 0 else 0.0


def fin_mass_kg(fin: FinGeometry, material: FinMaterial) -> float:
    a = fin_area(fin.root_chord_m, fin.tip_chord_m, fin.span_m)
    return fin.count * a * fin.thickness_m * material.density_kg_m3


# --------------------------------------------------------------------------
# Barrowman stability equations
# --------------------------------------------------------------------------

def nose_cp(body: BodyParams) -> tuple[float, float]:
    """Returns (X_n, CN_alpha_n): CP location from the nose tip, and the
    nose's normal-force coefficient slope (= 2.0 for all standard nose
    shapes under Barrowman's method)."""
    factor = NOSE_CP_FACTORS.get(body.nose_type, 0.466)
    return factor * body.nose_length_m, 2.0


def fin_set_cn_alpha(fin: FinGeometry, body_diameter_m: float) -> tuple[float, float]:
    """Returns (CN_alpha_fins, Kfb interference factor) for the whole fin
    set, per Barrowman."""
    Cr, Ct, s, Xr, N = (fin.root_chord_m, fin.tip_chord_m, fin.span_m,
                         fin.sweep_m, fin.count)
    Rt = body_diameter_m / 2.0
    Kfb = 1.0 + Rt / (s + Rt)
    denom = 1.0 + math.sqrt(1.0 + (2.0 * Xr / (Cr + Ct)) ** 2) if (Cr + Ct) > 0 else 1.0
    cn_alpha = Kfb * (4.0 * N * (s / body_diameter_m) ** 2) / denom
    return cn_alpha, Kfb


def fin_cp_offset_from_root_le(Cr: float, Ct: float, Xr: float) -> float:
    """Barrowman's closed-form axial distance from the fin root leading
    edge to the fin set's center of pressure."""
    if (Cr + Ct) == 0:
        return 0.0
    term1 = (Xr * (Cr + 2.0 * Ct)) / (3.0 * (Cr + Ct))
    term2 = (1.0 / 6.0) * (Cr + Ct - (Cr * Ct) / (Cr + Ct))
    return term1 + term2


def compute_cp(design: DesignInputs, fin: FinGeometry) -> dict:
    d = design.body.diameter_m
    x_n, cn_n = nose_cp(design.body)
    cn_fins, kfb = fin_set_cn_alpha(fin, d)
    x_fin_local = fin_cp_offset_from_root_le(fin.root_chord_m, fin.tip_chord_m, fin.sweep_m)
    x_fins_abs = design.fin_position_from_nose_m + x_fin_local

    cn_total = cn_n + cn_fins
    x_cp = (cn_n * x_n + cn_fins * x_fins_abs) / cn_total if cn_total > 0 else x_n

    return {
        "cp_from_nose_m": x_cp,
        "cn_alpha_total": cn_total,
        "cn_alpha_nose": cn_n,
        "cn_alpha_fins": cn_fins,
        "kfb_interference": kfb,
        "nose_cp_m": x_n,
        "fin_cp_m": x_fins_abs,
    }


def compute_cg(design: DesignInputs, fin: FinGeometry, material: FinMaterial) -> dict:
    m_fins = fin_mass_kg(fin, material)
    fin_local_centroid = fin_centroid_axial_offset(fin.root_chord_m, fin.tip_chord_m,
                                                     fin.sweep_m, fin.span_m)
    fin_cg_abs = design.fin_position_from_nose_m + fin_local_centroid

    total_moment = sum(c.mass_kg * c.cg_from_nose_m for c in design.components)
    total_mass = sum(c.mass_kg for c in design.components)

    total_moment += m_fins * fin_cg_abs
    total_mass += m_fins

    cg = total_moment / total_mass if total_mass > 0 else 0.0
    return {
        "cg_from_nose_m": cg,
        "total_mass_kg": total_mass,
        "fin_mass_kg": m_fins,
        "fin_cg_m": fin_cg_abs,
    }


def stability_margin_calibers(cp_m: float, cg_m: float, diameter_m: float) -> float:
    return (cp_m - cg_m) / diameter_m


# --------------------------------------------------------------------------
# Flutter analysis
# --------------------------------------------------------------------------

PA_PER_PSI = 6894.757293168
FT_PER_M = 3.280839895


def flutter_velocity(fin: FinGeometry, material: FinMaterial, altitude_m: float) -> dict:
    """Semi-empirical fin flutter boundary velocity (NACA TN 4197 flutter
    boundary equation, as commonly used in amateur rocketry references).

    IMPORTANT: this equation's constant (1.337) is only valid when the
    shear modulus is in psi and the speed of sound is in ft/s - it is not
    a dimensionally-general SI formula, even though every other quantity
    in it is dimensionless. This function converts to those units
    internally and converts the result back to m/s so the rest of the
    tool can stay in SI throughout.
    """
    Cr, Ct, s, t = fin.root_chord_m, fin.tip_chord_m, fin.span_m, fin.thickness_m
    a_ms, P = atmosphere(altitude_m)

    area = fin_area(Cr, Ct, s)
    AR = (s ** 2) / area if area > 0 else 0.0
    taper = Ct / Cr if Cr > 0 else 0.0
    t_over_c = t / Cr if Cr > 0 else 0.0

    if t_over_c <= 0 or AR <= 0:
        return {"flutter_velocity_m_s": 0.0, "aspect_ratio": AR,
                "taper_ratio": taper, "thickness_ratio": t_over_c,
                "speed_of_sound_m_s": a_ms, "pressure_ratio": P}

    G_psi = material.shear_modulus_pa / PA_PER_PSI
    a_fps = a_ms * FT_PER_M

    denom = 1.337 * (AR ** 3) * P * (taper + 1.0)
    numer = 2.0 * (AR + 2.0) * (t_over_c ** 3)
    stiffness_term = G_psi / (denom / numer)
    vf_fps = a_fps * math.sqrt(stiffness_term) if stiffness_term > 0 else 0.0
    vf_ms = vf_fps / FT_PER_M

    return {
        "flutter_velocity_m_s": vf_ms,
        "aspect_ratio": AR,
        "taper_ratio": taper,
        "thickness_ratio": t_over_c,
        "speed_of_sound_m_s": a_ms,
        "pressure_ratio": P,
    }


# --------------------------------------------------------------------------
# Full design evaluation
# --------------------------------------------------------------------------

def evaluate_design(design: DesignInputs, fin: FinGeometry) -> dict:
    cp = compute_cp(design, fin)
    cg = compute_cg(design, fin, design.material)
    margin = stability_margin_calibers(cp["cp_from_nose_m"], cg["cg_from_nose_m"],
                                        design.body.diameter_m)
    flutter = flutter_velocity(fin, design.material, design.flight.altitude_m)
    required_vf = design.flight.max_velocity_m_s * design.flight.flutter_safety_factor

    return {
        "fin_geometry": {
            "root_chord_m": fin.root_chord_m,
            "tip_chord_m": fin.tip_chord_m,
            "span_m": fin.span_m,
            "sweep_m": fin.sweep_m,
            "thickness_m": fin.thickness_m,
            "count": fin.count,
            "area_single_fin_m2": fin_area(fin.root_chord_m, fin.tip_chord_m, fin.span_m),
        },
        "cp": cp,
        "cg": cg,
        "stability_margin_calibers": margin,
        "flutter": flutter,
        "flutter_required_velocity_m_s": required_vf,
        "flutter_margin_ok": flutter["flutter_velocity_m_s"] >= required_vf,
        "fin_set_mass_kg": cg["fin_mass_kg"],
    }


# --------------------------------------------------------------------------
# Optimizer
# --------------------------------------------------------------------------

def default_bounds(design: DesignInputs) -> dict:
    d = design.body.diameter_m
    return {
        "root_chord_m": (0.5 * d, 3.5 * d),
        "tip_chord_m": (0.0, 3.0 * d),
        "span_m": (0.3 * d, 2.5 * d),
        "sweep_m": (0.0, 3.5 * d),
        "thickness_m": (0.001, 0.012),  # 1-12 mm
    }


def _unpack(x, order):
    return {name: val for name, val in zip(order, x, strict=True)}


def optimize_fins(design: DesignInputs) -> dict:
    """Search for the lightest fin set (fixed count, position, material)
    that meets both the target stability margin window and the flutter
    safety margin. Runs a global search (differential evolution) followed
    by a local constrained polish (SLSQP)."""

    bounds_dict = design.bounds or default_bounds(design)
    order = ["root_chord_m", "tip_chord_m", "span_m", "sweep_m", "thickness_m"]
    bounds = [bounds_dict[k] for k in order]

    margin_lo = design.target_margin_calibers - design.margin_tolerance_calibers
    margin_hi = design.target_margin_calibers + design.margin_tolerance_calibers

    def make_fin(x):
        p = _unpack(x, order)
        Cr, Ct, s, Xr, t = (p["root_chord_m"], p["tip_chord_m"], p["span_m"],
                             p["sweep_m"], p["thickness_m"])
        Ct = min(Ct, Cr)          # tip chord cannot exceed root chord
        Xr = min(Xr, Cr)          # keep a physically sane swept planform
        return FinGeometry(Cr, Ct, s, Xr, t, design.fin_count)

    def objective(x):
        fin = make_fin(x)
        result = evaluate_design(design, fin)
        mass = result["fin_set_mass_kg"]

        margin = result["stability_margin_calibers"]
        penalty = 0.0
        if margin < margin_lo:
            penalty += 5000.0 * (margin_lo - margin) ** 2
        if margin > margin_hi:
            penalty += 500.0 * (margin - margin_hi) ** 2  # softer: overstable wastes mass, not unsafe

        vf = result["flutter"]["flutter_velocity_m_s"]
        req = result["flutter_required_velocity_m_s"]
        if vf < req:
            penalty += 5000.0 * ((req - vf) / max(req, 1.0)) ** 2

        return mass * 1000.0 + penalty  # scale mass to grams so penalties dominate sensibly

    result_de = differential_evolution(
        objective, bounds, seed=42, maxiter=300, popsize=25,
        tol=1e-10, mutation=(0.4, 1.2), recombination=0.7, polish=False,
    )

    # Local polish with explicit constraints for a cleaner final answer.
    def margin_constraint(x):
        fin = make_fin(x)
        r = evaluate_design(design, fin)
        return r["stability_margin_calibers"]

    def flutter_constraint(x):
        fin = make_fin(x)
        r = evaluate_design(design, fin)
        return r["flutter"]["flutter_velocity_m_s"] - r["flutter_required_velocity_m_s"]

    def mass_objective(x):
        return objective(x) / 1000.0  # for the local pass, closer to grams scale

    constraints = [
        NonlinearConstraint(margin_constraint, margin_lo, margin_hi),
        NonlinearConstraint(flutter_constraint, 0.0, np.inf),
    ]

    x0 = result_de.x
    try:
        result_local = minimize(
            mass_objective, x0, method="SLSQP", bounds=bounds,
            constraints=constraints, options={"maxiter": 200, "ftol": 1e-9},
        )
        x_final = result_local.x if result_local.success else x0
    except Exception:  # noqa: BLE001 - SLSQP/constraint evaluation can fail in
        # several different ways (LinAlgError, ValueError from a degenerate
        # geometry, etc); any failure here just means "keep the global
        # search's answer" rather than the caller getting a 500.
        x_final = x0

    best_fin = make_fin(x_final)
    evaluation = evaluate_design(design, best_fin)
    evaluation["optimizer"] = {
        "global_search_mass_g": result_de.fun,
        "converged": bool(result_de.success),
        "bounds_used": bounds_dict,
        "target_margin_window_calibers": [margin_lo, margin_hi],
    }
    return evaluation
