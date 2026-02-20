import pytest
import os
import shutil
from agent.executor import run_command
from agent.runtime.registry import refresh_registry

@pytest.fixture(scope="module", autouse=True)
def setup_registry():
    """Initialise le registry avant les tests pour garantir la résolution des chemins."""
    refresh_registry()

def test_whoami_authorized():
    """Vérifie qu'une commande autorisée fonctionne et passe bien par bwrap."""
    # Note: 'whoami' doit être dans security/allowed_tools.json
    response = run_command("whoami")
    
    assert response["exit_code"] == 0
    # L'utilisateur doit être soit postgres (dev) soit pgagent (prod), mais pas root
    assert "root" not in response["stdout"].lower()
    assert "bwrap" in response["command_executed"]

def test_unauthorized_tool():
    """Vérifie qu'un outil absent de la allowlist est bloqué avant exécution."""
    # 'top' est généralement exclu des allowlists d'agents
    response = run_command("top -b -n 1")
    
    assert response["exit_code"] == -1
    assert "not allowed" in response["stderr"].lower()

def test_dynamic_binary_resolution():
    """Vérifie que l'executor résout le chemin absolu du binaire via le registry."""
    # On utilise 'ls' qui est universel
    expected_path = shutil.which("ls")
    response = run_command("ls /tmp")
    
    assert response["exit_code"] == 0
    # On vérifie que la commande finale utilise bien le chemin complet résolu
    assert expected_path in response["command_executed"]

def test_sandbox_isolation_fs():
    """Vérifie que la sandbox restreint l'accès aux dossiers sensibles non montés."""
    # /root ne fait pas partie des ro-bind standards dans executor.py
    response = run_command("ls /root")
    
    assert response["exit_code"] != 0
    # On attend une erreur de permission ou de fichier introuvable (car masqué)
    error = response["stderr"].lower()
    assert "permission denied" in error or "no such file" in error

def test_sandbox_readonly_system():
    """Vérifie que les dossiers système sont montés en lecture seule."""
    # On tente d'écrire dans /usr, qui est bindé en --ro-bind
    response = run_command("touch /usr/test_sandbox_proxy")
    
    assert response["exit_code"] != 0
    assert "read-only file system" in response["stderr"].lower()

def test_network_isolation():
    """Vérifie que l'isolation réseau (unshare-all) bloque les sorties."""
    # Une tentative de ping vers l'extérieur (ou localhost sans loopback) doit échouer
    response = run_command("ping -c 1 8.8.8.8")
    
    assert response["exit_code"] != 0
    # bwrap avec --unshare-all sans --share-net rend le réseau totalement invisible
    assert "unreachable" in response["stderr"].lower() or response["exit_code"] != 0

def test_postgres_socket_access():
    """Vérifie que le socket PostgreSQL est accessible malgré le sandbox."""
    # Si le socket est monté, le dossier doit être visible dans le sandbox
    response = run_command("ls /var/run/postgresql")
    
    # Si Postgres est installé, ce dossier doit exister et être lisible
    if os.path.exists("/var/run/postgresql"):
        assert response["exit_code"] == 0
    else:
        pytest.skip("Socket PostgreSQL non présent sur l'hôte")
def test_chain_denied_tool():
    """
    Vérifie que la sécurité bloque AVANT l'exécution.
    """
    # On utilise un outil qui ne doit SURTOUT PAS être dans allowed_tools.json
    command = "nmap -sP 192.168.1.0/24" 
    result = run_command(command)
    
    # Doit être bloqué par la Layer 1 (Allowlist)
    assert result["exit_code"] == -1
    assert "not allowed" in result["stderr"].lower()
