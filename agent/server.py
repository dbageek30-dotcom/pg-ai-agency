from flask import Flask, request, jsonify
import json
import os
import logging
import time

# Imports relatifs liés à notre nouvelle structure
from .executor import run_command
from .security.allowlist import is_tool_allowed, extract_tool
from .security.safety import is_safe, get_unsafe_reason
from .runtime.audit import get_last_logs
from .runtime.registry import refresh_registry

# ------------------------------------------------------------
# Charger la configuration
# ------------------------------------------------------------
# En prod, la config est dans /opt/pgagent/config/config.json
CONFIG_PATH = os.environ.get("AGENT_CONFIG", os.path.join(os.path.dirname(__file__), "..", "config", "config.json"))

if not os.path.exists(CONFIG_PATH):
    # Fallback pour le mode dev
    CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json.template")

try:
    with open(CONFIG_PATH, "r") as f:
        CONFIG = json.load(f)
except Exception:
    CONFIG = {"port": 5050}

PORT = int(os.environ.get("AGENT_PORT", CONFIG.get("port", 5050)))

# ------------------------------------------------------------
# Logging (Dossier /opt/pgagent/logs/ si possible)
# ------------------------------------------------------------
LOG_FILE = "/opt/pgagent/logs/pgagent.log"
if not os.access(os.path.dirname(LOG_FILE), os.W_OK):
    LOG_FILE = "pgagent.log" # Fallback local

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

# ------------------------------------------------------------
# Fonction d'authentification
# ------------------------------------------------------------
def check_auth(req):
    expected = os.environ.get("AGENT_TOKEN", "")
    auth = req.headers.get("Authorization", "")
    # Supporte "Bearer token" ou le token brut pour la compatibilité
    return auth == f"Bearer {expected}" or auth == expected

# ------------------------------------------------------------
# Application Flask
# ------------------------------------------------------------
app = Flask(__name__)

@app.route("/ping", methods=["GET"])
@app.route("/health", methods=["GET"])
def ping():
    return jsonify({
        "status": "ok",
        "service": "pg-ai-agent",
        "timestamp": time.time()
    })

@app.route("/exec", methods=["POST"])
def exec_command():
    if not check_auth(request):
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json()
    if not data or "command" not in data:
        return jsonify({"error": "Missing 'command'"}), 400

    command = data["command"]
    dry_run = data.get("dry_run", False)
    client_ip = request.remote_addr

    # 1. Vérification allowlist
    if not is_tool_allowed(command):
        tool = extract_tool(command)
        logging.warning(f"[DENY] IP={client_ip} CMD='{command}' TOOL='{tool}'")
        return jsonify({"error": f"Command '{tool}' not allowed"}), 403

    # 2. Vérification patterns dangereux
    if not is_safe(command):
        reason = get_unsafe_reason(command)
        logging.warning(f"[UNSAFE] IP={client_ip} CMD='{command}' REASON='{reason}'")
        return jsonify({"error": "Unsafe command", "reason": reason}), 400

    # 3. Mode dry-run
    if dry_run:
        logging.info(f"[DRY-RUN] IP={client_ip} CMD='{command}'")
        return jsonify({"dry_run": True, "command": command})

    # 4. Exécution réelle
    start = time.time()
    logging.info(f"[REQUEST] IP={client_ip} CMD='{command}'")

    result = run_command(command)

    duration = round(time.time() - start, 3)
    logging.info(
        f"[RESULT] IP={client_ip} CMD='{command}' EXIT={result['exit_code']} TIME={duration}s"
    )

    return jsonify(result)

@app.route("/audit", methods=["GET"])
def get_audit():
    """Récupère les logs SQLite via l'API."""
    if not check_auth(request):
        return jsonify({"error": "Unauthorized"}), 401
    
    limit = request.args.get("limit", 20, type=int)
    return jsonify(get_last_logs(limit))

# ------------------------------------------------------------
# Lancement
# ------------------------------------------------------------
if __name__ == "__main__":
    # Scan des outils au démarrage
    print("🔍 Scanning tools...")
    refresh_registry()
    app.run(host="0.0.0.0", port=PORT)
