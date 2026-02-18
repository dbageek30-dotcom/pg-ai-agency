import subprocess
import shlex
import os
import json
import shutil

USE_SANDBOX = os.environ.get("AGENT_SANDBOX", "1") == "1"

# Charger la allowlist JSON
ALLOWLIST_PATH = os.path.join(os.path.dirname(__file__), "security", "allowed_tools.json")

with open(ALLOWLIST_PATH, "r") as f:
    CONFIG = json.load(f)

ALLOWED_TOOL_NAMES = CONFIG.get("allowed_tools", [])

# Résoudre les chemins complets des binaires
ALLOWED_BINARIES = []
for tool in ALLOWED_TOOL_NAMES:
    path = shutil.which(tool)
    if path:
        ALLOWED_BINARIES.append(path)


def build_bwrap_command(command: str) -> list:
    cmd = [
        "bwrap",
        "--unshare-all",
        "--die-with-parent",
        "--new-session",

        "--proc", "/proc",
        "--dev", "/dev",

        # FS minimal mais fonctionnel
        "--ro-bind", "/usr", "/usr",
        "--ro-bind", "/bin", "/bin",
        "--ro-bind", "/lib", "/lib",
        "--ro-bind", "/lib64", "/lib64",
        "--ro-bind", "/etc", "/etc",

        "--tmpfs", "/tmp",
    ]

    # Résolution du binaire en chemin absolu
    args = shlex.split(command)
    tool = args[0]

    resolved = shutil.which(tool)
    if not resolved:
        raise RuntimeError(f"Tool {tool} not found")

    args[0] = resolved
    cmd += args

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

