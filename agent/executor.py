import subprocess
import shlex
import os
import json

USE_SANDBOX = os.environ.get("AGENT_SANDBOX", "1") == "1"

# Chargement de la allowlist depuis le JSON
ALLOWLIST_PATH = os.path.join(os.path.dirname(__file__), "security", "allowed_tools.json")

with open(ALLOWLIST_PATH, "r") as f:
    ALLOWED_TOOLS = json.load(f)

# On récupère uniquement les chemins binaires
ALLOWED_BINARIES = list(ALLOWED_TOOLS.values())


def build_bwrap_command(command: str) -> list:
    """
    Construit une commande bubblewrap (bwrap) sandboxée.
    """
    cmd = [
        "bwrap",
        "--unshare-all",
        "--die-with-parent",
        "--new-session",

        # Filesystem minimal
        "--proc", "/proc",
        "--dev", "/dev",

        # /tmp privé
        "--tmpfs", "/tmp",

        # On autorise /usr en lecture seule
        "--ro-bind", "/usr", "/usr",
    ]

    # On autorise uniquement les binaires explicitement listés
    for binary in ALLOWED_BINARIES:
        if os.path.exists(binary):
            cmd += ["--ro-bind", binary, binary]

    # Commande finale
    cmd += shlex.split(command)
    return cmd


def run_command(command: str) -> dict:
    """
    Exécute une commande locale dans une sandbox bwrap (si activée).
    """
    try:
        if USE_SANDBOX:
            cmd = build_bwrap_command(command)
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

