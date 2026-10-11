"""Offline checks for the API's token and CORS gate: run with `python -m pytest tests` from the repo root."""
import importlib
import sys
import types

import pytest

pytest.importorskip("flask")
pytest.importorskip("flask_cors")

TOKEN = "test-token"
ALLOWED = "http://localhost:5173"


@pytest.fixture
def api(monkeypatch):
    """automation.api imported with a fake planner and registry; nothing real is planned or executed."""
    calls = types.SimpleNamespace(planned=[], executed=[])

    class FakePlanner:
        def plan(self, prompt):
            calls.planned.append(prompt)
            return {"actions": [{"agent": "fake", "action": "noop", "params": {}}], "message": "ok"}

    class FakeAgent:
        def execute(self, action, params):
            calls.executed.append(action)
            return {"status": "success", "details": "", "duration_ms": 0}

    monkeypatch.setitem(sys.modules, "automation.core.llm_orchestrator",
                        types.SimpleNamespace(LLMOrchestrator=FakePlanner))
    monkeypatch.setitem(sys.modules, "automation.core.registry",
                        types.SimpleNamespace(registry=types.SimpleNamespace(get_agent=lambda name: FakeAgent())))
    monkeypatch.setenv("AURA_API_TOKEN", TOKEN)
    monkeypatch.setenv("AURA_ALLOWED_ORIGINS", ALLOWED)
    monkeypatch.delitem(sys.modules, "automation.api", raising=False)
    module = importlib.import_module("automation.api")
    yield types.SimpleNamespace(client=module.app.test_client(), calls=calls)
    sys.modules.pop("automation.api", None)


@pytest.mark.parametrize("headers", [{}, {"X-AURA-Token": "wrong"}, {"X-AURA-Token": "wróng"}])
def test_request_without_valid_token_is_rejected_and_executes_nothing(api, headers):
    response = api.client.post("/api/execute", json={"prompt": "delete everything"}, headers=headers)
    assert response.status_code == 401
    assert api.calls.planned == [] and api.calls.executed == []


def test_request_with_token_reaches_planner(api):
    response = api.client.post("/api/execute", json={"prompt": "open notepad"}, headers={"X-AURA-Token": TOKEN})
    assert response.status_code == 200
    assert api.calls.planned == ["open notepad"] and api.calls.executed == ["noop"]


def test_preflight_from_unlisted_origin_gets_no_cors_header(api):
    def preflight(origin):
        return api.client.options("/api/execute", headers={
            "Origin": origin, "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-aura-token"})

    assert "Access-Control-Allow-Origin" not in preflight("http://evil.example").headers
    assert preflight(ALLOWED).headers.get("Access-Control-Allow-Origin") == ALLOWED
