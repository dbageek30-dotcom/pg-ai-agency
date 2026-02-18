from flask import Flask, request, jsonify
from executor import run_command
import json
import os

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

    # Exécution de la commande
    result = run_command(command)
    return jsonify(result)

# ------------------------------------------------------------
# Lancement du serveur
# ------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)

