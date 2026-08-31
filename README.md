# FIN — Rocket Fin Stability & Flutter Design Tool

A Flask app that takes your body tube diameter, mass distribution, and flight
conditions, and searches for the lightest trapezoidal fin set that hits a
target stability margin while staying clear of aeroelastic flutter. Results
render as a live 3D model, a 2D stability diagram, and a numeric readout.

[![CI](https://img.shields.io/badge/CI-GitHub%20Actions-blue)](.github/workflows/ci.yml)

## What it does

1. You describe the vehicle: body diameter, nose shape/length, every mass
   component (motor, avionics, payload, recovery gear...) with its location,
   where the fin roots sit, fin count, fin material, expected max velocity,
   and altitude at that velocity.
2. You set a target stability margin (in calibers) and a tolerance window.
3. The backend runs a bounded global search (`scipy.optimize.differential_evolution`)
   followed by a constrained local polish (`SLSQP`) over root chord, tip
   chord, span, sweep, and thickness, minimizing fin mass subject to:
   - stability margin landing inside your target window, and
   - flutter velocity clearing your max velocity by your safety factor.
4. Results — geometry, CP/CG, stability margin, flutter velocity — render as
   a live 3D model (nose + body tube + fin set, built from your exact
   geometry) plus a 2D stability diagram and a readout panel. Sliders let
   you hand-tune the optimized geometry afterward and see everything —
   numbers, 2D diagram, and the 3D model — update instantly (calls
   `/api/evaluate`, no re-optimization).

## The 3D model

Built with Three.js (loaded from a CDN via an import map, no bundler
needed). The nose cone is a `LatheGeometry` revolved from the same profile
math (ogive/conical/parabolic/elliptical) as the physics model; the body
tube is a cylinder; each fin is an extruded trapezoid placed radially
around the body. It updates live as you tune geometry, and shows a
reasonable placeholder rocket even before you've run the optimizer.

- **Drag** to orbit (360° rotate around the rocket)
- **Right-click drag** (or two-finger drag on trackpad/touch) to pan in X/Y
- **Scroll / pinch** to zoom in Z
- Toolbar: ISO / FRONT / TOP camera presets, wireframe toggle, auto-rotate

## Architecture

```
              Browser
                 │
                 ▼
          Flask REST API  (app.py)
                 │
        ┌────────┴────────┐
        ▼                 ▼
 Input Validation    Unit Conversion
   (schemas.py,        (mm/g/m·s
    pydantic)         → SI, at the
        │              API boundary)
        └────────┬────────┘
                 ▼
          rocket_physics.py
        (pure Python + SciPy,
         no Flask dependency)
                 │
       ┌─────────┼─────────┐
       ▼         ▼         ▼
   Barrowman   Flutter   Optimizer
   (CP/CG,     (NACA     (differential_
    stability   TN 4197   evolution +
    margin)     boundary) SLSQP)
       │         │         │
       └─────────┼─────────┘
                 ▼
             Evaluation
          (fin geometry, CP,
           CG, margin, flutter
           velocity, fin mass)
                 │
                 ▼
          JSON Response
                 │
                 ▼
          Three.js UI
       (3D model, 2D diagram,
        readouts, tune sliders)
```

The validation layer and the physics layer are deliberately decoupled:
`schemas.py` never touches units or physics, `rocket_physics.py` never
touches HTTP or raw dicts. `app.py` is the only place that knows about
both — it validates, converts units, calls the physics layer, and converts
the result back for the frontend.

## Installation

Requires Python 3.11+.

```bash
git clone <this-repo>
cd fin
pip install -r requirements.txt
python app.py
```

Then open **http://127.0.0.1:5100**.

## Development

Install dev dependencies on top of the runtime ones:

```bash
pip install -r requirements.txt -r requirements-dev.txt
```

### Run tests

```bash
pytest
```

74 tests across four files: `test_rocket_physics.py` (unit tests against
hand-derived/ISA reference values), `test_optimizer.py` (constraint
satisfaction: bounds, stability margin, flutter safety), `test_validation.py`
(schema rejection of invalid input), `test_app.py` (Flask endpoint
integration tests via the test client).

### Run lint

```bash
ruff check .
```

### Run coverage

```bash
pytest --cov=rocket_physics --cov=app --cov=schemas --cov-report=term-missing
```

Currently at ~95% line coverage across `app.py`, `rocket_physics.py`, and
`schemas.py`.

## Docker

```bash
docker build -t fin .
docker run -p 8000:8000 fin
```

Then open **http://127.0.0.1:8000**. The container runs `gunicorn` (not the
Flask dev server) as a non-root user, and exposes `GET /health` for
container orchestrators / load balancers.

## CI

`.github/workflows/ci.yml` runs on every push and pull request to `main`:

```
checkout → Python setup (3.11 & 3.12) → install deps → ruff → pytest --cov → build & smoke-test Docker image
```

## Contributing

1. Fork, branch, make your change.
2. Add or update tests — `rocket_physics.py` changes need physics-level
   tests (known/hand-derived values, not just "it runs"); API changes need
   `test_app.py` coverage; new input fields need `schemas.py` + `test_validation.py`.
3. `ruff check .` and `pytest` should both be clean before you open a PR.
4. Note your change in `CHANGELOG.md` under `[Unreleased]`.

Good first areas to contribute in: boat-tail / transition CP contribution,
multiple fin sets, additional nose shapes, a real motor thrust-curve
integration, transonic drag corrections. See **Extending it** below for
where each of those hooks in.

## Changelog

See [`CHANGELOG.md`](CHANGELOG.md).

## Validation & Limitations

**Methodology:**
- **Center of pressure**: Barrowman's equations (the standard method behind
  OpenRocket, RockSim, and most amateur design tools). Assumes a single fin
  set on a constant-diameter body tube (no boat tail contribution).
- **Fin flutter**: the semi-empirical flutter-boundary equation derived from
  NACA TN 4197, widely used across amateur/high-power rocketry (Apogee
  Components' newsletters, RocketPy, and various open web calculators all
  cite the same equation). This equation's constant is only valid with
  shear modulus in psi and speed of sound in ft/s — the code converts units
  internally so you can work entirely in SI/metric at the API boundary.
- **Atmosphere**: ISA troposphere model, valid to 11 km.

**What's tested:** every physics primitive (`atmosphere`, `fin_area`,
`nose_cp`, `fin_set_cn_alpha`, `fin_cp_offset_from_root_le`, `fin_mass_kg`,
`fin_centroid_axial_offset`) against independently-derived or published
reference values; the optimizer's constraint satisfaction (bounds,
stability window, flutter safety) end-to-end; every API endpoint's success
and failure paths; every validation rule in `schemas.py`.

**What's not verified against real flight data.** These are standard
*preliminary design* methods, not a substitute for ground vibration
testing or a full aeroelastic analysis, particularly:
- **Transonic/supersonic flight** — Barrowman's CP method and the flutter
  equation are both most trustworthy well below Mach 1; neither includes a
  wave-drag or compressibility correction.
- **Anisotropic materials** — the flutter equation assumes an isotropic
  fin material (a single shear modulus). Composite layups with different
  stiffness by direction will be mis-estimated.
- **Boat tails, transitions, and multiple fin sets** — not modeled; the
  body's normal-force contribution is assumed zero between the nose and
  fins, which is standard for a constant-diameter tube but not universal.
- **Unswept/unusual fin planforms** — Barrowman's equations were derived
  for conventional swept trapezoidal fins; very unusual planforms (forward
  swept, non-trapezoidal) are outside their validated range.

If you're building something that will actually fly and matters (a
certification project, a high-value airframe, anything supersonic), treat
this tool's output as a starting point and confirm against ground vibration
testing, a full aeroelastic analysis, or flight data — the same caveat that
applies to OpenRocket and RockSim.

## Project layout

```
app.py                 Flask routes, request validation wiring, unit conversion, error handling
rocket_physics.py       Barrowman equations, flutter equation, optimizer (pure SI, no Flask dependency)
schemas.py              Pydantic request models (DesignRequest, EvaluateRequest, FinGeometry, MassComponent, ...)
tests/                  pytest suite (physics, optimizer, API, validation)
templates/index.html    Page layout, tabs, 3D viewer + toolbar markup
static/style.css        Styling
static/app.js           Form handling, API calls, SVG diagram, tab/toolbar wiring, live tuning sliders
static/viewer3d.js      Three.js 3D rocket model (nose/body/fin mesh builder + camera/controls)
Dockerfile              Production image (gunicorn, non-root user, healthcheck)
.github/workflows/ci.yml  Lint + test + coverage + Docker smoke test
```

## API

**GET /health** — liveness check: `{"status": "ok"}`.

**POST /api/optimize** — full input payload in, optimized fin geometry +
full evaluation out. See `schemas.DesignRequest` for the exact schema
(mm/g/m-s units at this boundary; everything is meters/kg/Pa internally).
Returns `422` with per-field error detail on invalid input, `400` on
malformed JSON, `500` on a calculation failure (logged server-side).

**POST /api/evaluate** — same payload, plus `fins.geometry_mm` with an
explicit `{root_chord_mm, tip_chord_mm, span_mm, sweep_mm, thickness_mm}` —
evaluates that exact geometry without searching. See `schemas.EvaluateRequest`.

**GET /api/materials** — built-in material presets (density + shear modulus).

## Extending it

- `rocket_physics.py` has no Flask dependency, so you can import it directly
  in a script or notebook for batch studies (e.g. sweep target margin vs.
  fin mass).
- To support boat-tails or multiple fin sets, extend `compute_cp` — the
  Barrowman body-CN term is currently assumed zero for a constant-diameter
  tube, which is standard but not universal.
- Bounds for the search (`default_bounds` in `rocket_physics.py`) are
  reasonable multiples of body diameter; pass `bounds_mm` in the request
  payload to override them for unusual configurations (very long/short
  fins, minimum-gauge thickness constraints, etc).
- New input fields belong in `schemas.py` first — that's the single
  validation boundary; `_parse_design` in `app.py` trusts that validated
  data completely and does no defensive checking of its own.
