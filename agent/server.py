from flask import Flask, request, jsonify
import json
import os
import logging
import time

# Imports structure v1.2.1
from executor import run_command
from security.allowlist import is_tool_allowed, extract_tool
from security.safety import is_safe, get_unsafe_reason
from runtime.audit import get_last_logs, log_execution, init_db
from runtime.registry import refresh_registry, get_registry
# --- NOUVEL IMPORT ---
from runtime.toolbox import ToolboxManager 

# ------------------------------------------------------------
# Configuration
# ------------------------------------------------------------
CONFIG_PATH = os.environ.get("AGENT_CONFIG", "/opt/pgagent/config/config.json")
if not os.path.exists(CONFIG_PATH):
    CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json.template")

try:
    with open(CONFIG_PATH, "r") as f:
        CONFIG = json.load(f)
except Exception:
    CONFIG = {"port": 5050}

PORT = int(os.environ.get("AGENT_PORT", CONFIG.get("port", 5050)))

# ------------------------------------------------------------
# Logging
# ------------------------------------------------------------
LOG_FILE = "/opt/pgagent/logs/pgagent.log"
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

def check_auth(req):
    expected = os.environ.get("AGENT_TOKEN", "")
    auth = req.headers.get("Authorization", "")
    return auth == f"Bearer {expected}" or auth == expected

# ------------------------------------------------------------
# Application Flask
# ------------------------------------------------------------
app = Flask(__name__)

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "service": "pg-ai-agent",
        "version": "1.2.1",
        "timestamp": time.time()
    })

@app.route("/registry", methods=["GET"])
def get_agent_registry():
    if not check_auth(request):
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify(get_registry())

# --- NOUVELLE ROUTE : EXPLORE ---
@app.route("/explore/<tool>", methods=["GET"])
def explore_tool(tool):
    """Génère la boîte à outils JSON pour un binaire spécifique."""
    if not check_auth(request):
        return jsonify({"error": "Unauthorized"}), 401

    # Sécurité : On vérifie si l'outil est autorisé avant de l'explorer
    if not is_tool_allowed(tool):
        return jsonify({"error": f"Tool '{tool}' not allowed for exploration"}), 403

    subcommand = request.args.get("sub")
    toolbox = ToolboxManager()
    
    logging.info(f"[EXPLORE] Tool='{tool}' Sub='{subcommand}'")
    result = toolbox.get_structured_help(tool, subcommand)
    
    return jsonify(result)

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

    if not is_tool_allowed(command):
        tool = extract_tool(command)
        logging.warning(f"[DENY] IP={client_ip} CMD='{command}' TOOL='{tool}'")
        return jsonify({"error": f"Command '{tool}' not allowed"}), 403

    if not is_safe(command):
        reason = get_unsafe_reason(command)
        logging.warning(f"[UNSAFE] IP={client_ip} CMD='{command}' REASON='{reason}'")
        return jsonify({"error": "Unsafe command", "reason": reason}), 400

    if dry_run:
        return jsonify({"dry_run": True, "command": command})

    start = time.time()
    logging.info(f"[REQUEST] IP={client_ip} CMD='{command}'")

    result = run_command(command)
    duration = round(time.time() - start, 3)
    
    try:
        log_execution(
            command=command,
            executed_command=result.get("command_executed", ""),
            exit_code=result.get("exit_code", -1),
            stdout=result.get("stdout", ""),
            stderr=result.get("stderr", "")
        )
    except Exception as e:
        logging.error(f"Audit log failed: {e}")

    logging.info(f"[RESULT] IP={client_ip} EXIT={result['exit_code']} TIME={duration}s")
    return jsonify(result)

@app.route("/audit", methods=["GET"])
def get_audit():
    if not check_auth(request):
        return jsonify({"error": "Unauthorized"}), 401
    limit = request.args.get("limit", 20, type=int)
    return jsonify(get_last_logs(limit))

if __name__ == "__main__":
    print("🔍 Initializing PgAgent v1.2.1...")
    init_db()          
    refresh_registry() 
    app.run(host="0.0.0.0", port=PORT)
