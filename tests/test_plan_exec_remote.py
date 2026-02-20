import os
import json
import pytest
import requests

# Adresse de ton agent sur VM-PG
AGENT_URL = os.environ.get("AGENT_URL", "http://10.214.0.10:5050")
AGENT_TOKEN = os.environ.get("AGENT_TOKEN", "123")


def test_plan_exec_remote():
    """
    Test réel : envoie une requête à l'agent déployé sur VM-PG.
    """

    url = f"{AGENT_URL}/plan_exec"

    payload = {
        "question": "check my backups",
        "mode": "readonly"
    }

    headers = {
        "Authorization": f"Bearer {AGENT_TOKEN}",
        "Content-Type": "application/json"
    }

    response = requests.post(url, headers=headers, data=json.dumps(payload))

    # Le test doit réussir si l'agent répond correctement
    assert response.status_code == 200, f"Bad status: {response.status_code} - {response.text}"

    data = response.json()

    # Vérifications minimales
    assert "plan" in data
    assert "state" in data
    assert "question" in data
    assert data["question"] == "check my backups"

    # Vérifie que le plan contient des steps
    assert len(data["plan"].get("steps", [])) > 0

    # Vérifie que l'exécution renvoie un historique
    assert "history" in data["state"]

