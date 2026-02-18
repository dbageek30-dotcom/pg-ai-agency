import pytest
import os
import json
from agent.executor import run_command
from agent.runtime.registry import refresh_registry
from agent.runtime.audit import get_last_logs, init_db

@pytest.fixture(scope="session", autouse=True)
def prepare_env():
    """Prépare l'environnement avant les tests."""
    init_db()
    refresh_registry()

def test_chain_authorized_psql():
    """
    Vérifie la chaîne : Commande autorisée -> Registry -> Executor -> Audit
    """
    # On utilise 'psql --version' car il est dans ta allowlist
    command = "psql --version"
    result = run_command(command)
    
    # 1. Check Executor
    assert result["exit_code"] == 0
    assert "psql" in result["stdout"].lower()
    
    # 2. Check Bwrap (Vérifie que la sandbox a été utilisée)
    assert "bwrap" in result["command_executed"]
    
    # 3. Check Audit (Vérifie que c'est bien écrit en DB)
    logs = get_last_logs(limit=1)
    assert len(logs) > 0
    assert logs[0]["command"] == command
    assert logs[0]["exit_code"] == 0

def test_chain_denied_tool():
    """
    Vérifie que la sécurité bloque AVANT l'exécution.
    """
    # 'ls' n'est plus dans ta liste
    command = "ls /tmp"
    result = run_command(command)
    
    assert result["exit_code"] == -1
    assert "not allowed" in result["stderr"]
    
    # Vérifie que la tentative de fraude est quand même auditée
    logs = get_last_logs(limit=1)
    assert logs[0]["command"] == command
    assert "not allowed" in logs[0]["stderr"]

def test_chain_unsafe_pattern():
    """
    Vérifie que la sécurité bloque les patterns dangereux (ex: ;)
    """
    command = "psql --version; whoami"
    result = run_command(command)
    
    assert result["exit_code"] == -1
    # Selon ta logique safety.py
    assert "Unsafe" in result["stderr"] or "not allowed" in result["stderr"]
