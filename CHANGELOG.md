# Changelog

All notable changes to this project are documented here. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

Architecture/infrastructure upgrade — no changes to the physics or the
optimizer's behavior in this pass. Engineering feature work (additional
fin geometry constraints, multiple fin-set support, configurable flutter
safety factor, etc.) tracked separately.

### Added
- `schemas.py` — Pydantic request models (`DesignRequest`, `EvaluateRequest`,
  `BodyIn`, `MassComponentIn`, `FinsIn`, `GeometryMMIn`, `FlightIn`,
  `TargetIn`, `BoundsMMIn`) as the single validation boundary for the API.
  Replaces manual `dict` parsing (`payload["body"]["diameter_mm"]` style
  access with scattered `KeyError`/`ValueError` handling).
- `GET /health` endpoint.
- Layered error handling: `400` for malformed JSON, `422` for schema
  validation failures (with per-field detail), `500` for calculation
  failures — with the actual exception now logged server-side via
  `app.logger.exception` instead of only being returned to the client.
- Test suite: `tests/test_rocket_physics.py`, `tests/test_optimizer.py`,
  `tests/test_validation.py`, `tests/test_app.py` — 74 tests total, ~95%
  coverage of `app.py` / `rocket_physics.py` / `schemas.py`.
- `pyproject.toml` — project metadata plus `ruff`/`pytest`/`coverage` config.
- `requirements-dev.txt` for test/lint tooling, separate from runtime deps.
- `Dockerfile` and `.dockerignore` — production image running `gunicorn`
  as a non-root user, with a container `HEALTHCHECK` against `/health`.
- `.github/workflows/ci.yml` — lint, test with coverage, and a Docker
  build + smoke test, on every push/PR to `main`.
- `.gitignore`.

### Changed
- `requirements.txt` now pins exact versions (`Flask==3.1.3`,
  `numpy==2.4.4`, `scipy==1.17.1`, `pydantic==2.13.5`, `Werkzeug==3.1.7`)
  instead of open-ended `>=` ranges, for reproducible installs. Verified
  by installing into a clean virtualenv and running the full test suite
  against it.
- `app.py` rewritten around the new validation layer: routes now call
  `DesignRequest.model_validate(...)` / `EvaluateRequest.model_validate(...)`
  instead of hand-parsing dicts.
- README restructured with Architecture, Installation, Development,
  Docker, CI, Contributing, Changelog, and Validation & Limitations
  sections.

### Fixed
- Minor `ruff`-flagged issues in `rocket_physics.py` (an unused local
  variable, an unqualified `zip()` call without `strict=`).

## [0.1.0] — first working version

- Flask backend + `rocket_physics.py`: Barrowman center-of-pressure
  equations, NACA TN 4197 fin flutter boundary equation, ISA troposphere
  atmosphere model, and a `differential_evolution` + `SLSQP` optimizer
  that searches fin geometry for the lightest fin set meeting a target
  stability margin and flutter safety factor.
- Frontend: form-driven design inputs, live 2D stability (CP/CG) diagram,
  manual-tune sliders calling `/api/evaluate` for instant recompute.
- 3D viewer: Three.js model (nose/body/fin mesh built from live geometry),
  orbit/pan/zoom controls, view presets, wireframe/auto-rotate toggles.
- Discovered and fixed a real unit-consistency bug in the flutter equation
  during testing: the published constant (1.337) is only valid with shear
  modulus in psi and speed of sound in ft/s, not SI units — plugging in
  Pa/m·s directly inflated flutter velocities by roughly 80x.
