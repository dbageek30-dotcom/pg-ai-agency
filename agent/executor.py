import subprocess
import shlex
import os
import json
import shutil

# Imports v1.2.1
from runtime.registry import get_binary_path
from runtime.audit import log_execution
from security.allowlist import is_tool_allowed
from security.safety import is_safe, get_unsafe_reason

USE_SANDBOX = os.environ.get("AGENT_SANDBOX", "1") == "1"

def build_bwrap_command(command: str) -> list:
    """
    Construit la commande bwrap pour isoler l'exécution.
    Résout le binaire via le registry (prioritaire) ou le PATH.
    """
    args = shlex.split(command)
    if not args:
        raise ValueError("Commande vide")
    
    tool_name = args[0]

    # 1. Résolution du chemin (Priorité au Registry pour psql-18, etc.)
    resolved_path = get_binary_path(tool_name) or shutil.which(tool_name)
        
    if not resolved_path:
        raise RuntimeError(f"Tool '{tool_name}' not found on system registry or PATH.")

    # On récupère le dossier du binaire pour l'autoriser dans le sandbox
    tool_dir = os.path.dirname(resolved_path)
    
    # 2. Construction des arguments Bubblewrap
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
        "--ro-bind", "/usr/bin", "/usr/bin",
        "--ro-bind", tool_dir, tool_dir,  # Autorise le dossier spécifique du binaire
        "--tmpfs", "/tmp",
    ]

    # 3. Montage du socket PostgreSQL pour permettre la connexion locale (UDS)
    if os.path.exists("/var/run/postgresql"):
        cmd += ["--ro-bind", "/var/run/postgresql", "/var/run/postgresql"]

    # Remplacement de l'alias par le chemin absolu résolu
    args[0] = resolved_path
    cmd += args
    return cmd

def run_command(command: str) -> dict:
    """
    Point d'entrée principal : Sécurité -> Sandbox -> Audit.
    """
    # --- 1. SÉCURITÉ : Allowlist ---
    if not is_tool_allowed(command):
        error_msg = "Tool not allowed in security policy."
        log_execution(command, "REJECTED_BY_ALLOWLIST", -1, "", error_msg)
        return {"stdout": "", "stderr": error_msg, "exit_code": -1}

    # --- 2. SÉCURITÉ : Safety Patterns ---
    if not is_safe(command):
        reason = get_unsafe_reason(command)
        error_msg = f"Unsafe command detected: {reason}"
        log_execution(command, "REJECTED_BY_SAFETY", -1, "", error_msg)
        return {"stdout": "", "stderr": error_msg, "exit_code": -1}

    executed_cmd_str = command
    try:
        if USE_SANDBOX:
            cmd_list = build_bwrap_command(command)
        else:
            cmd_list = shlex.split(command)
            resolved = get_binary_path(cmd_list[0]) or shutil.which(cmd_list[0])
            if resolved:
                cmd_list[0] = resolved
        
        executed_cmd_str = " ".join(cmd_list)

        # --- 3. EXÉCUTION ---
        process = subprocess.Popen(
            cmd_list,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        stdout, stderr = process.communicate(timeout=45) # Timeout de sécurité
        exit_code = process.returncode

    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate()
        exit_code = 124
        stderr = (stderr or "") + "\nError: Process timed out (45s)"
    except Exception as e:
        stdout = ""
        stderr = str(e)
        exit_code = -1

    # --- 4. AUDIT : Enregistrement SQLite ---
    log_execution(command, executed_cmd_str, exit_code, stdout, stderr)

    return {
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": exit_code,
        "command_executed": executed_cmd_str
    }
