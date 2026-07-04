"""Tests for HTTP sidecar auth identity propagation into receipts."""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from src.api import create_app
from src.config import AppConfig
from src.guardrails import current_caller, current_run_id


def test_hmac_handshake_passes_service_identity_to_receipts():
    seen = {}

    def fake_handshake(**kwargs):
        seen.update(kwargs)
        seen["caller"] = current_caller()
        seen["run_id"] = current_run_id()
        return json.dumps({
            "activated_servers": [],
            "active_tool_count": 0,
            "budget_remaining": 100,
        })

    app = create_app(
        config=AppConfig(auth_enabled=True, hmac_api_key="expected-secret"),
        catalogue=[],
        handshake_fn=fake_handshake,
    )
    response = TestClient(app).post(
        "/handshake",
        headers={"X-API-Key": "expected-secret"},
        json={"tech_stack": ["python"], "task_description": "trace this"},
    )

    assert response.status_code == 200
    assert seen["caller"] == "service:hmac"
    assert seen["run_id"].startswith("run_")


def test_hmac_handshake_rejects_bad_key_before_receipt_context():
    def fake_handshake(**kwargs):  # pragma: no cover - should never run
        raise AssertionError("handshake should not be called")

    app = create_app(
        config=AppConfig(auth_enabled=True, hmac_api_key="expected-secret"),
        catalogue=[],
        handshake_fn=fake_handshake,
    )
    response = TestClient(app).post(
        "/handshake",
        headers={"X-API-Key": "wrong-secret"},
        json={"tech_stack": ["python"]},
    )

    assert response.status_code == 401
