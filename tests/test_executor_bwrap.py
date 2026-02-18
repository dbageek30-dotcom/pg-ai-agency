import pytest
import os
import json
from agent.executor import run_command
from agent.runtime.registry import refresh_registry

@pytest.fixture(scope="module", autouse=True)
def setup_registry():
    """Initialise le registry avant les tests."""
    refresh_registry()

def test_whoami_authorized():
    """Vérifie qu'une commande simple autorisée fonctionne sous bwrap."""
    # Note: Assure-toi que 'whoami' est dans ton security/allowed_tools.json
    response = run_command("whoami")
    
    assert response["exit_code"] == 0
    assert "postgres" in response["stdout"] or "pgagent" in response["stdout"]
    assert "bwrap" in response["command_executed"]

def test_unauthorized_tool():
    """Vérifie qu'un outil non présent dans la allowlist est bloqué."""
    # On tente une commande qui ne devrait PAS être dans ton allowed_tools.json
    response = run_command("top")
    
    assert response["exit_code"] == -1
    assert "not allowed" in response["stderr"]

def test_dynamic_binary_resolution():
    """Vérifie que l'executor trouve le chemin complet via le registry."""
    response = run_command("ls /tmp")
    
    assert response["exit_code"] == 0
    # On vérifie que la commande exécutée utilise le chemin absolu (ex: /usr/bin/ls)
    assert "/bin/ls" in response["command_executed"]

def test_sandbox_isolation():
    """Vérifie que la sandbox restreint bien l'accès (en dehors des binds)."""
    # On tente de lire un fichier sensible non monté (si bwrap est bien configuré)
    # Selon tes binds, /root ne devrait pas être accessible
    response = run_command("ls /root")
    
    assert response["exit_code"] != 0
    assert "Permission denied" in response["stderr"] or "No such file" in response["stderr"]
