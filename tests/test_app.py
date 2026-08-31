"""
Integration tests for the Flask API — exercised through Flask's test
client (no real network socket, no need to run the dev server).
"""

import pytest

from app import app as flask_app


@pytest.fixture
def client():
    flask_app.config.update(TESTING=True)
    with flask_app.test_client() as c:
        yield c


class TestHealth:
    def test_health_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.get_json() == {"status": "ok"}


class TestIndexPage:
    def test_index_loads(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert b"FIN" in resp.data


class TestMaterialsEndpoint:
    def test_materials_returns_presets(self, client):
        resp = client.get("/api/materials")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "plywood_birch" in data
        assert "density_kg_m3" in data["plywood_birch"]
        assert "shear_modulus_pa" in data["plywood_birch"]


class TestOptimizeEndpoint:
    def test_valid_request_returns_200(self, client, sample_api_payload):
        resp = client.post("/api/optimize", json=sample_api_payload)
        assert resp.status_code == 200
        data = resp.get_json()
        assert "fin_geometry_mm" in data
        assert "stability" in data
        assert "flutter" in data
        assert data["fin_geometry_mm"]["count"] == 3

    def test_response_respects_stability_target(self, client, sample_api_payload):
        resp = client.post("/api/optimize", json=sample_api_payload)
        data = resp.get_json()
        margin = data["stability"]["margin_calibers"]
        target = sample_api_payload["target"]["stability_margin_calibers"]
        tol = sample_api_payload["target"]["margin_tolerance"]
        assert target - tol - 1e-2 <= margin <= target + tol + 1e-2

    def test_flutter_check_satisfied(self, client, sample_api_payload):
        resp = client.post("/api/optimize", json=sample_api_payload)
        data = resp.get_json()
        assert data["flutter"]["margin_ok"] is True
        assert data["flutter"]["flutter_velocity_mps"] >= data["flutter"]["required_velocity_mps"]

    def test_invalid_body_returns_422(self, client, sample_api_payload):
        sample_api_payload["body"]["diameter_mm"] = -50
        resp = client.post("/api/optimize", json=sample_api_payload)
        assert resp.status_code == 422
        data = resp.get_json()
        assert data["error"] == "Validation failed"
        assert any("diameter_mm" in d["field"] for d in data["detail"])

    def test_missing_field_returns_422(self, client, sample_api_payload):
        del sample_api_payload["target"]
        resp = client.post("/api/optimize", json=sample_api_payload)
        assert resp.status_code == 422

    def test_malformed_json_returns_400(self, client):
        resp = client.post(
            "/api/optimize", data="not json at all {{{", content_type="application/json"
        )
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "Bad request"

    def test_non_object_json_returns_400(self, client):
        resp = client.post("/api/optimize", json=[1, 2, 3])
        assert resp.status_code == 400


class TestEvaluateEndpoint:
    def test_valid_geometry_returns_200(self, client, sample_api_payload):
        sample_api_payload["fins"]["geometry_mm"] = {
            "root_chord_mm": 150, "tip_chord_mm": 60, "span_mm": 120,
            "sweep_mm": 90, "thickness_mm": 3.5,
        }
        resp = client.post("/api/evaluate", json=sample_api_payload)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["fin_geometry_mm"]["root_chord_mm"] == pytest.approx(150)

    def test_missing_geometry_returns_422(self, client, sample_api_payload):
        # no geometry_mm block -> EvaluateRequest's validator should reject
        resp = client.post("/api/evaluate", json=sample_api_payload)
        assert resp.status_code == 422

    def test_tip_exceeding_root_returns_422(self, client, sample_api_payload):
        sample_api_payload["fins"]["geometry_mm"] = {
            "root_chord_mm": 50, "tip_chord_mm": 100, "span_mm": 120,
            "sweep_mm": 90, "thickness_mm": 3.5,
        }
        resp = client.post("/api/evaluate", json=sample_api_payload)
        assert resp.status_code == 422

    def test_no_optimization_metadata_in_evaluate_response(self, client, sample_api_payload):
        sample_api_payload["fins"]["geometry_mm"] = {
            "root_chord_mm": 150, "tip_chord_mm": 60, "span_mm": 120,
            "sweep_mm": 90, "thickness_mm": 3.5,
        }
        resp = client.post("/api/evaluate", json=sample_api_payload)
        data = resp.get_json()
        assert "optimizer" not in data
