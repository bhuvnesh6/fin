"""
Flask backend for the rocket fin design/optimization tool.

Run with:
    pip install -r requirements.txt
    python app.py

Then open http://127.0.0.1:5000

Error handling convention used throughout this module:
    400  malformed request (not valid JSON / not a JSON object)
    422  well-formed JSON that fails schema validation (pydantic)
    500  valid input that failed during the physics/optimization calculation
         (the actual exception is logged server-side; the client only gets
         a generic message, since internals shouldn't leak in the response)
"""

from __future__ import annotations

import logging

from flask import Flask, jsonify, render_template, request
from pydantic import ValidationError
from werkzeug.exceptions import BadRequest

from rocket_physics import (
    BodyParams,
    DesignInputs,
    FinGeometry,
    FinMaterial,
    FlightParams,
    MassComponent,
    evaluate_design,
    optimize_fins,
)
from schemas import DesignRequest, EvaluateRequest

app = Flask(__name__)
app.logger.setLevel(logging.INFO)

MATERIAL_PRESETS = {
    "balsa": {"density_kg_m3": 170.0, "shear_modulus_pa": 4.0e8},
    "basswood": {"density_kg_m3": 420.0, "shear_modulus_pa": 1.0e9},
    "plywood_birch": {"density_kg_m3": 680.0, "shear_modulus_pa": 2.8e9},
    "fiberglass_g10": {"density_kg_m3": 1850.0, "shear_modulus_pa": 4.1e9},
    "carbon_fiber": {"density_kg_m3": 1600.0, "shear_modulus_pa": 5.0e9},
    "acrylic": {"density_kg_m3": 1180.0, "shear_modulus_pa": 1.4e9},
}


def _mm(v: float) -> float:
    return v / 1000.0


def _g(v: float) -> float:
    return v / 1000.0


class CalculationError(Exception):
    """Raised when validated input still fails during the physics/
    optimization stage (e.g. a numerically infeasible configuration)."""


def _parse_design(req: DesignRequest) -> DesignInputs:
    """Build the internal (SI-unit) DesignInputs from an already-validated
    pydantic request. No defensive checks needed here - schemas.py is the
    single validation boundary."""
    body = BodyParams(
        diameter_m=_mm(req.body.diameter_mm),
        nose_length_m=_mm(req.body.nose_length_mm),
        nose_type=req.body.nose_type,
    )

    components = [
        MassComponent(
            name=c.name,
            mass_kg=_g(c.mass_g),
            cg_from_nose_m=_mm(c.cg_from_nose_mm),
        )
        for c in req.mass.components
    ]

    mat_in = req.fins.material
    if isinstance(mat_in, str):
        preset = MATERIAL_PRESETS[mat_in]
        material = FinMaterial(name=mat_in, **preset)
    else:
        material = FinMaterial(
            name=mat_in.name,
            density_kg_m3=mat_in.density_kg_m3,
            shear_modulus_pa=mat_in.shear_modulus_pa,
        )

    flight = FlightParams(
        max_velocity_m_s=req.flight.max_velocity_mps,
        altitude_m=req.flight.altitude_m,
        flutter_safety_factor=req.flight.safety_factor,
    )

    bounds = None
    if req.bounds_mm is not None:
        b = req.bounds_mm
        bounds = {
            "root_chord_m": tuple(_mm(v) for v in b.root_chord_mm),
            "tip_chord_m": tuple(_mm(v) for v in b.tip_chord_mm),
            "span_m": tuple(_mm(v) for v in b.span_mm),
            "sweep_m": tuple(_mm(v) for v in b.sweep_mm),
            "thickness_m": tuple(_mm(v) for v in b.thickness_mm),
        }

    return DesignInputs(
        body=body,
        components=components,
        fin_position_from_nose_m=_mm(req.fins.position_from_nose_mm),
        fin_count=req.fins.count,
        material=material,
        flight=flight,
        target_margin_calibers=req.target.stability_margin_calibers,
        margin_tolerance_calibers=req.target.margin_tolerance,
        bounds=bounds,
    )


def _to_mm_output(evaluation: dict) -> dict:
    """Convert the SI-unit evaluation dict into a display-friendly,
    mm / g / m-s response for the frontend."""
    fg = evaluation["fin_geometry"]
    out = {
        "fin_geometry_mm": {
            "root_chord_mm": fg["root_chord_m"] * 1000,
            "tip_chord_mm": fg["tip_chord_m"] * 1000,
            "span_mm": fg["span_m"] * 1000,
            "sweep_mm": fg["sweep_m"] * 1000,
            "thickness_mm": fg["thickness_m"] * 1000,
            "count": fg["count"],
            "area_single_fin_cm2": fg["area_single_fin_m2"] * 1e4,
        },
        "stability": {
            "cp_from_nose_mm": evaluation["cp"]["cp_from_nose_m"] * 1000,
            "cg_from_nose_mm": evaluation["cg"]["cg_from_nose_m"] * 1000,
            "margin_calibers": evaluation["stability_margin_calibers"],
            "total_mass_g": evaluation["cg"]["total_mass_kg"] * 1000,
            "fin_set_mass_g": evaluation["fin_set_mass_kg"] * 1000,
        },
        "flutter": {
            "flutter_velocity_mps": evaluation["flutter"]["flutter_velocity_m_s"],
            "required_velocity_mps": evaluation["flutter_required_velocity_m_s"],
            "margin_ok": evaluation["flutter_margin_ok"],
            "aspect_ratio": evaluation["flutter"]["aspect_ratio"],
            "taper_ratio": evaluation["flutter"]["taper_ratio"],
            "thickness_ratio": evaluation["flutter"]["thickness_ratio"],
        },
    }
    if "optimizer" in evaluation:
        out["optimizer"] = evaluation["optimizer"]
    return out


def _get_json_body() -> dict:
    """Parse the request body as JSON, raising a 400 if it isn't valid
    JSON or isn't a JSON object."""
    payload = request.get_json(silent=True)
    if payload is None or not isinstance(payload, dict):
        raise BadRequest("Request body must be a valid JSON object.")
    return payload


# --------------------------------------------------------------------------
# Error handlers - centralised so every route gets the same response shape
# --------------------------------------------------------------------------

@app.errorhandler(BadRequest)
def handle_bad_request(e: BadRequest):
    return jsonify({"error": "Bad request", "detail": e.description}), 400


@app.errorhandler(ValidationError)
def handle_validation_error(e: ValidationError):
    app.logger.info("request validation failed: %s", e)
    return jsonify({
        "error": "Validation failed",
        "detail": [
            {"field": ".".join(str(p) for p in err["loc"]), "message": err["msg"]}
            for err in e.errors()
        ],
    }), 422


@app.errorhandler(CalculationError)
def handle_calculation_error(e: CalculationError):
    app.logger.exception("calculation error")
    return jsonify({"error": "Calculation failed", "detail": str(e)}), 500


@app.errorhandler(500)
def handle_internal_error(e):
    app.logger.exception("unhandled internal error")
    return jsonify({"error": "Internal server error"}), 500


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html", materials=list(MATERIAL_PRESETS.keys()))


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/api/materials")
def materials():
    return jsonify(MATERIAL_PRESETS)


@app.route("/api/optimize", methods=["POST"])
def api_optimize():
    payload = _get_json_body()
    req = DesignRequest.model_validate(payload)  # raises ValidationError -> 422
    design = _parse_design(req)

    try:
        evaluation = optimize_fins(design)
    except Exception as e:
        raise CalculationError(str(e)) from e

    return jsonify(_to_mm_output(evaluation))


@app.route("/api/evaluate", methods=["POST"])
def api_evaluate():
    """Evaluate a single, fully specified fin geometry (no optimization) -
    useful for checking a design you already have, or for the frontend's
    interactive manual-tuning mode."""
    payload = _get_json_body()
    req = EvaluateRequest.model_validate(payload)  # raises ValidationError -> 422
    design = _parse_design(req)

    g = req.fins.geometry_mm  # guaranteed non-None by EvaluateRequest validator
    fin = FinGeometry(
        root_chord_m=_mm(g.root_chord_mm),
        tip_chord_m=_mm(g.tip_chord_mm),
        span_m=_mm(g.span_mm),
        sweep_m=_mm(g.sweep_mm),
        thickness_m=_mm(g.thickness_mm),
        count=design.fin_count,
    )

    try:
        evaluation = evaluate_design(design, fin)
    except Exception as e:
        raise CalculationError(str(e)) from e

    return jsonify(_to_mm_output(evaluation))


if __name__ == "__main__":
    app.run(debug=True, port=5100)
