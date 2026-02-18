from flask import Flask, request, jsonify
from executor import run_command
from security.allowlist import is_tool_allowed, extract_tool
from security.safety import is_safe, get_unsafe_reason
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
    # Vérification allowlist dynamique
    # ------------------------------------------------------------
    if not is_tool_allowed(command):
        tool = extract_tool(command)
        logging.warning(f"[DENY] IP={client_ip} CMD='{command}' TOOL='{tool}'")
        return jsonify({"error": f"Command '{tool}' not allowed"}), 403

    # ------------------------------------------------------------
    # Vérification sécurité (patterns dangereux)
    # ------------------------------------------------------------
    if not is_safe(command):
        reason = get_unsafe_reason(command)
        logging.warning(f"[UNSAFE] IP={client_ip} CMD='{command}' REASON='{reason}'")
        return jsonify({
            "error": "Unsafe command",
            "reason": reason
        }), 400

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

