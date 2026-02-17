from flask import Flask, request, jsonify
from executor import run_command
import json
import os

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")

# Charger la configuration
if os.path.exists(CONFIG_PATH):
    with open(CONFIG_PATH, "r") as f:
        CONFIG = json.load(f)
else:
    CONFIG = {"port": 5050}

app = Flask(__name__)

@app.route("/ping", methods=["GET"])
def ping():
    return jsonify({"status": "ok"})

@app.route("/exec", methods=["POST"])
def exec_command():
    data = request.get_json()

    if not data or "command" not in data:
        return jsonify({"error": "Missing 'command'"}), 400

    command = data["command"]

    result = run_command(command)
    return jsonify(result)

if __name__ == "__main__":
    port = CONFIG.get("port", 5050)
    app.run(host="0.0.0.0", port=port)

