import json
import pytest
from unittest.mock import patch

from agent.server import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    return app.test_client()


def test_plan_exec_success(client):
    # Fake plan renvoyé par le planner
    fake_plan = {
        "goal": "Check backups",
        "mode": "readonly",
        "max_steps": 1,
        "steps": [
            {
                "id": "check_info",
                "tool": "pgbackrest",
                "args": ["info"],
                "intent": "List backups",
                "on_error": "abort"
            }
        ]
    }

    # Fake state renvoyé par l’orchestrator
    fake_state = {
        "history": [
            {
                "step": fake_plan["steps"][0],
                "command": "/usr/bin/pgbackrest info",
                "result": {"exit_code": 0, "stdout": "OK", "stderr": ""}
            }
        ],
        "errors": []
    }

    # On mock le planner et l’orchestrator
    with patch("agent.server.plan_actions", return_value=fake_plan):
        with patch("agent.server.run_plan", return_value=fake_state):

            response = client.post(
                "/plan_exec",
                headers={"Authorization": "Bearer 123"},
                data=json.dumps({"question": "check my backups"}),
                content_type="application/json"
            )

            assert response.status_code == 200

            data = response.get_json()
            assert "plan" in data
            assert "state" in data

            assert data["plan"]["goal"] == "Check backups"
            assert data["state"]["errors"] == []
            assert data["state"]["history"][0]["result"]["exit_code"] == 0


def test_plan_exec_unauthorized(client):
    response = client.post(
        "/plan_exec",
        data=json.dumps({"question": "check my backups"}),
        content_type="application/json"
    )
    assert response.status_code == 401


def test_plan_exec_missing_question(client):
    response = client.post(
        "/plan_exec",
        headers={"Authorization": "Bearer 123"},
        data=json.dumps({}),
        content_type="application/json"
    )
    assert response.status_code == 400
    assert response.get_json()["error"] == "Missing 'question'"

