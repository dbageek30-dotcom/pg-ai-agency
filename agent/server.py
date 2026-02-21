from flask import Flask, request, jsonify
import json
import os
import logging
import time
import sys

# Imports structure v1.2.1
from executor import run_command
from security.allowlist import is_tool_allowed, extract_tool
from security.safety import is_safe, get_unsafe_reason
from runtime.audit import get_last_logs, log_execution, init_db
from runtime.registry import refresh_registry, get_registry
from runtime.toolbox import ToolboxManager

# --- IMPORTS PLANNER & ORCHESTRATOR ---
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from planner import plan_actions
from orchestrator import run_plan

# ------------------------------------------------------------
# Configuration
# ------------------------------------------------------------
CONFIG_PATH = os.environ.get("AGENT_CONFIG", "/opt/pgagent/config/config.json")
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
    expected = os.environ.get("AGENT_TOKEN", "123") # "123" par défaut pour tes tests
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

@app.route("/plan_exec", methods=["POST"])
def plan_and_exec():
    if not check_auth(request):
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json() or {}
    question = data.get("question")
    mode = data.get("mode", "readonly")

    if not question:
        return jsonify({"error": "Missing 'question'"}), 400

    try:
        # 1. Récupération du registre (Discovery dynamique)
        registry = get_registry()

        # 2. GESTION DES CONFLITS DE VERSION (Arbitrage utilisateur)
        if registry.get("has_conflicts"):
            logging.warning(f"[CONFLICT] Version ambiguity detected for: {list(registry['conflicts'].keys())}")
            return jsonify({
                "error": "VERSION_CONFLICT",
                "message": "Plusieurs versions spécifiques détectées pour un même outil.",
                "details": registry.get("conflicts"),
                "instruction": "Veuillez préciser la version ou le chemin complet dans votre question."
            }), 409

        # 3. Préparation de la "Boîte à outils" enrichie pour le LLM
        # On passe la liste des objets {name, version, description, path}
        enriched_tools = registry.get("tools", [])
        
        # Note: pg_version peut être extrait dynamiquement du registry si besoin
        pg_version = "unknown" 

        # 4. Génération du plan via le Planner (qui reçoit la boîte à outils)
        plan = plan_actions(
            question=question,
            tools_help=enriched_tools, # L'IA a maintenant accès aux versions/descriptions
            pg_version=pg_version,
            mode=mode
        )

        # 5. Exécution sécurisée du plan
        # On utilise registry["binaries"] qui contient les chemins résolus et uniques
        state = run_plan(plan, registry.get("binaries", {}))

        return jsonify({
            "question": question,
            "plan": plan,
            "state": state
        })

    except Exception as e:
        logging.exception("Plan/Exec failed")
        return jsonify({"error": str(e)}), 500

# Les autres routes (/exec, /audit, /explore) restent inchangées dans leur logique
# mais s'appuieront sur le nouveau registry rafraîchi.

@app.route("/exec", methods=["POST"])
def exec_command():
    # ... (Ta logique exec_command existante)
    if not check_auth(request): return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json()
    command = data.get("command")
    # Utilisation du registry résolu pour l'exécution directe si besoin
    result = run_command(command)
    return jsonify(result)

if __name__ == "__main__":
    print("🔍 Initializing PgAgent v1.2.1...")
    init_db()
    # On force un premier scan au démarrage
    refresh_registry()
    app.run(host="0.0.0.0", port=PORT)
