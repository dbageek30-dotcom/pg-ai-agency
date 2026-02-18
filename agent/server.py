from flask import Flask, request, jsonify
from executor import run_command
import json
import os
import logging
import time

# ------------------------------------------------------------
# Charger la configuration (port)
# ------------------------------------------------------------
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")

if os.path.exists(CONFIG_PATH):
    with open(CONFIG_PATH, "r") as f:
        CONFIG = json.load(f)
else:
    CONFIG = {"port": 5050}

PORT = int(CONFIG.get("port", 5050))

# ------------------------------------------------------------
# Logging
# ------------------------------------------------------------
logging.basicConfig(
    filename="/var/log/pgagent.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

# ------------------------------------------------------------
# Fonction d'authentification via token systemd
# ------------------------------------------------------------
def check_auth(request):
    expected = os.environ.get("AGENT_TOKEN", "")
    auth = request.headers.get("Authorization", "")
    return auth == f"Bearer {expected}"

# ------------------------------------------------------------
# Allowlist des outils autorisés
# ------------------------------------------------------------
ALLOWED_TOOLS = {
    "patroni",
    "pgbackrest",
    "psql",
    "postgres",
    "pg_ctl",
    "systemctl",  # tu peux restreindre plus tard
}

def extract_tool(command: str) -> str:
    """
    Extrait le premier mot de la commande (le binaire).
    Exemple : "pgbackrest backup" → "pgbackrest"
    """
    return command.strip().split()[0]

# ------------------------------------------------------------
# Application Flask
# ------------------------------------------------------------
app = Flask(__name__)

@app.route("/ping", methods=["GET"])
def ping():
    return jsonify({"status": "ok"})

@app.route("/exec", methods=["POST"])
def exec_command():
    # Vérification du token
    if not check_auth(request):
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json()

    if not data or "command" not in data:
        return jsonify({"error": "Missing 'command'"}), 400

    command = data["command"]
    dry_run = data.get("dry_run", False)
    client_ip = request.remote_addr

    # ------------------------------------------------------------
    # Vérification allowlist
    # ------------------------------------------------------------
    tool = extract_tool(command)
    if tool not in ALLOWED_TOOLS:
        logging.warning(f"[DENY] IP={client_ip} CMD='{command}' TOOL='{tool}'")
        return jsonify({"error": f"Command '{tool}' not allowed"}), 403

    # ------------------------------------------------------------
    # Mode dry-run
    # ------------------------------------------------------------
    if dry_run:
        logging.info(f"[DRY-RUN] IP={client_ip} CMD='{command}'")
        return jsonify({
            "dry_run": True,
            "command": command
        })

    # ------------------------------------------------------------
    # Exécution réelle
    # ------------------------------------------------------------
    start = time.time()
    logging.info(f"[REQUEST] IP={client_ip} CMD='{command}'")

    result = run_command(command)

    duration = round(time.time() - start, 3)
    logging.info(
        f"[RESULT] IP={client_ip} CMD='{command}' EXIT={result['exit_code']} TIME={duration}s"
    )

    return jsonify(result)

# ------------------------------------------------------------
# Lancement du serveur
# ------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)

