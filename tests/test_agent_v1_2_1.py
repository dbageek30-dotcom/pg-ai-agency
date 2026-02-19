import pytest
import requests
import os
import time

# Configuration du test
BASE_URL = "http://localhost:5050"
HEADERS = {"Authorization": "Bearer 123", "Content-Type": "application/json"}

@pytest.fixture(scope="module", autouse=True)
def check_server_is_running():
    """Vérifie que le serveur local est lancé avant les tests."""
    try:
        response = requests.get(f"{BASE_URL}/health", timeout=2)
        if response.status_code != 200:
            pytest.fail("Le serveur agent n'est pas lancé sur 5050")
    except requests.exceptions.ConnectionError:
        pytest.fail("Connexion refusée sur localhost:5050. Lance 'python3 agent/server.py' d'abord.")

def test_registry_discovery():
    """Vérifie que l'agent expose bien ses outils et versions."""
    response = requests.get(f"{BASE_URL}/registry", headers=HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert "binaries" in data
    # On vérifie la présence des binaires critiques que tu as détectés
    bins = data["binaries"]
    assert "psql" in bins
    assert "psql-18" in bins or "psql-16" in bins
    print(f"\n✅ Registry OK : {len(bins)} binaires trouvés.")

def test_execution_with_versioned_alias():
    """Vérifie que l'agent peut exécuter une version spécifique (ex: psql-18)."""
    # On cherche une version disponible dans le registry pour le test
    reg = requests.get(f"{BASE_URL}/registry", headers=HEADERS).json()
    target_tool = "psql-18" if "psql-18" in reg["binaries"] else "psql"
    
    payload = {"command": f"{target_tool} --version"}
    response = requests.post(f"{BASE_URL}/exec", headers=HEADERS, json=payload)
    
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["exit_code"] == 0
    assert "PostgreSQL" in res_data["stdout"]
    print(f"✅ Exec OK : {target_tool} a répondu.")

def test_audit_logging():
    """Vérifie que la dernière commande est bien inscrite en base SQLite."""
    # On laisse un micro-délai pour l'écriture SQLite
    time.sleep(0.1)
    
    response = requests.get(f"{BASE_URL}/audit?limit=1", headers=HEADERS)
    assert response.status_code == 200
    logs = response.json()
    assert len(logs) > 0
    # On vérifie que le dernier log correspond à notre test précédent
    assert "--version" in logs[0]["command"]
    print(f"✅ Audit OK : Commande trouvée en base (ID: {logs[0]['id']})")

def test_security_rejection():
    """Vérifie que l'allowlist fonctionne toujours."""
    payload = {"command": "rm -rf /tmp/test"}
    response = requests.post(f"{BASE_URL}/exec", headers=HEADERS, json=payload)
    assert response.status_code == 403
    assert "not allowed" in response.json()["error"]
    print("✅ Sécurité OK : 'rm' a été bloqué.")
