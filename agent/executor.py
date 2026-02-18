import subprocess
import shlex
import os
import json
import shutil

# Imports corrigés (Absolus pour v1.2.1)
from runtime.registry import get_binary_path
from runtime.audit import log_execution
from security.allowlist import is_tool_allowed
from security.safety import is_safe, get_unsafe_reason

USE_SANDBOX = os.environ.get("AGENT_SANDBOX", "1") == "1"

# Chargement dynamique du chemin de la allowlist
ALLOWLIST_PATH = os.path.join(os.path.dirname(__file__), "security", "allowed_tools.json")

def load_allowed_tools():
    """Charge la liste brute des noms d'outils autorisés."""
    try:
        if os.path.exists(ALLOWLIST_PATH):
            with open(ALLOWLIST_PATH, "r") as f:
                config = json.load(f)
            return config.get("allowed_tools", [])
    except Exception:
        pass
    return []

ALLOWED_TOOL_NAMES = load_allowed_tools()

def build_bwrap_command(command: str) -> list:
    """
    Construit la commande bwrap pour isoler l'exécution.
    """
    args = shlex.split(command)
    if not args:
        raise ValueError("Commande vide")
    
    tool_name = args[0]

    # Résolution du chemin via le registry
    resolved_path = get_binary_path(tool_name) or shutil.which(tool_name)
        
    if not resolved_path:
        raise RuntimeError(f"Tool '{tool_name}' not found on system.")

    tool_dir = os.path.dirname(resolved_path)
    
    # Construction des arguments Bubblewrap
    cmd = [
        "bwrap",
        "--unshare-all",
        "--die-with-parent",
        "--new-session",
        "--proc", "/proc",
        "--dev", "/dev",
        "--ro-bind", "/usr", "/usr",
        "--ro-bind", "/bin", "/bin",
        "--ro-bind", "/lib", "/lib",
        "--ro-bind", "/lib64", "/lib64",
        "--ro-bind", "/etc", "/etc",
        "--ro-bind", "/usr/bin", "/usr/bin", # Ajout explicite pour certains binaires
        "--ro-bind", tool_dir, tool_dir,
        "--tmpfs", "/tmp",
    ]

    # Montage du socket PostgreSQL pour permettre la connexion locale
    if os.path.exists("/var/run/postgresql"):
        cmd += ["--ro-bind", "/var/run/postgresql", "/var/run/postgresql"]

    args[0] = resolved_path
    cmd += args
    return cmd

def run_command(command: str) -> dict:
    """
    Exécute une commande avec isolation Bubblewrap et enregistre l'audit.
    """
    # 1. Vérification de sécurité Allowlist
    if not is_tool_allowed(command):
        error_msg = f"Tool not allowed in security policy."
        log_execution(command, "REJECTED_BY_ALLOWLIST", -1, "", error_msg)
        return {"stdout": "", "stderr": error_msg, "exit_code": -1}

    # 2. Vérification de sécurité Patterns (Safety)
    if not is_safe(command):
        reason = get_unsafe_reason(command)
        error_msg = f"Unsafe command detected: {reason}"
        log_execution(command, "REJECTED_BY_SAFETY", -1, "", error_msg)
        return {"stdout": "", "stderr": error_msg, "exit_code": -1}

    executed_cmd_str = command
    try:
        if USE_SANDBOX:
            cmd_list = build_bwrap_command(command)
            executed_cmd_str = " ".join(cmd_list)
        else:
            cmd_list = shlex.split(command)
            resolved = get_binary_path(cmd_list[0]) or shutil.which(cmd_list[0])
            if resolved:
                cmd_list[0] = resolved
            executed_cmd_str = " ".join(cmd_list)

        # Exécution du processus
        process = subprocess.Popen(
            cmd_list,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        stdout, stderr = process.communicate()
        exit_code = process.returncode

    except Exception as e:
        stdout = ""
        stderr = str(e)
        exit_code = -1

    # 3. Enregistrement systématique dans l'Audit SQLite
    log_execution(command, executed_cmd_str, exit_code, stdout, stderr)

    return {
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": exit_code,
        "command_executed": executed_cmd_str
    }
