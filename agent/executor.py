import subprocess
import shlex
import os

USE_SANDBOX = os.environ.get("AGENT_SANDBOX", "1") == "1"

def build_sandbox_command(command: str) -> list:
    """
    Construit une commande systemd-run sandboxée.
    """
    return [
        "systemd-run",
        "--user",
        "--scope",
        "-p", "PrivateTmp=yes",
        "-p", "ProtectSystem=strict",
        "-p", "ProtectHome=yes",
        "-p", "NoNewPrivileges=yes",
        "-p", "ProtectKernelTunables=yes",
        "-p", "ProtectControlGroups=yes",
        "--"
    ] + shlex.split(command)

def run_command(command: str) -> dict:
    """
    Exécute une commande locale dans une sandbox systemd-run (si activée).
    """
    try:
        if USE_SANDBOX:
            cmd = build_sandbox_command(command)
        else:
            cmd = shlex.split(command)

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        stdout, stderr = process.communicate()

        return {
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": process.returncode
        }

    except Exception as e:
        return {
            "stdout": "",
            "stderr": str(e),
            "exit_code": -1
        }

