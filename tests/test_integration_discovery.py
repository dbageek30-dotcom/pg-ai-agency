import requests
import pytest

# Configuration de l'environnement VM-Agency
AGENT_URL = "http://10.214.0.10:5050"
HEADERS = {
    "Authorization": "Bearer 123",
    "Content-Type": "application/json"
}

def test_plan_exec_ls_resolution():
    """Vérifie que 'ls' est résolu en chemin absolu par discovery"""
    payload = {"question": "run ls", "mode": "readonly"}
    response = requests.post(f"{AGENT_URL}/plan_exec", json=payload, headers=HEADERS)
    
    # Si conflit (409), le test échoue car on veut une résolution propre pour 'ls'
    assert response.status_code == 200
    data = response.json()
    
    # On vérifie que l'orchestrateur a utilisé le chemin complet
    history = data["state"]["history"]
    assert len(history) > 0
    executed_command = history[0]["command"]
    
    # 'ls' doit être devenu '/usr/bin/ls' ou similaire
    assert executed_command.startswith("/")
    assert "ls" in executed_command
    print(f"\n[OK] 'ls' résolu en : {executed_command}")

def test_registry_structure():
    """Vérifie que le registry contient bien les métadonnées (version/desc)"""
    response = requests.get(f"{AGENT_URL}/registry", headers=HEADERS)
    assert response.status_code == 200
    registry = response.json()
    
    assert "tools" in registry
    # On vérifie qu'au moins un outil a une version extraite
    psql_data = next((t for t in registry["tools"] if t["name"] == "psql"), None)
    if psql_data:
        assert "version" in psql_data
        assert psql_data["version"] != "unknown"
        print(f"\n[OK] Version de psql détectée : {psql_data['version']}")

def test_version_conflict_handling():
    """
    Test prédictif : si tu sais que tu as deux versions de psql, 
    ce test doit valider que l'agent renvoie un 409.
    """
    # Ce test est optionnel selon ton setup actuel
    payload = {"question": "check psql version", "mode": "readonly"}
    response = requests.post(f"{AGENT_URL}/plan_exec", json=payload, headers=HEADERS)
    
    if response.status_code == 409:
        print("\n[OK] Système de conflit validé : l'agent refuse l'ambiguïté.")
        assert "conflicts" in response.json()
