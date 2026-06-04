import os
import sys
import json
import subprocess
import psycopg2
from flask import Flask, request, jsonify

app = Flask(__name__)

# Chemin absolu standardisé où le fichier sera lu sur la vm-pg
CONFIG_PATH = "/opt/pgagent/config/config.json"

try:
    with open(CONFIG_PATH, "r") as f:
        config = json.load(f)
except Exception as e:
    print(f"❌ Erreur lors du chargement de la configuration : {e}")
    sys.exit(1)

SECRET_TOKEN = config.get("secret_token")
DB_DSN = config.get("db_dsn")

def check_auth():
    """Vérification du token Bearer dans les headers HTTP"""
    token = request.headers.get("Authorization")
    return token == f"Bearer {SECRET_TOKEN}"

@app.route("/api/v1/execute/sql", methods=["POST"])
def execute_sql():
    if not check_auth():
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    
    data = request.get_json()
    sql_query = data.get("query")
    params = data.get("params", [])
    
    if not sql_query:
        return jsonify({"status": "error", "message": "Missing 'query' parameter"}), 400
    
    conn = None
    try:
        conn = psycopg2.connect(DB_DSN)
        cur = conn.cursor()
        cur.execute(sql_query, params)
        
        # Si la requête renvoie des lignes (SELECT, SHOW, etc.)
        if cur.description:
            columns = [desc[0] for desc in cur.description]
            rows = cur.fetchall()
            results = [dict(zip(columns, row)) for row in rows]
        else:
            conn.commit()
            results = {"rows_affected": cur.rowcount}
            
        cur.close()
        return jsonify({"status": "success", "data": results})
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        if conn: conn.close()

@app.route("/api/v1/execute/system", methods=["POST"])
def execute_system():
    if not check_auth():
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    
    data = request.get_json()
    command = data.get("command")
    
    # Liste blanche stricte des commandes système de diagnostic autorisées
    allowed_commands = ["df -h", "free -m", "uptime", "pg_ctl status"]
    if command not in allowed_commands:
        return jsonify({"status": "error", "message": "Command not allowed"}), 403
        
    try:
        output = subprocess.check_output(command, shell=True, stderr=subprocess.STDOUT).decode("utf-8")
        return jsonify({"status": "success", "output": output})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    # L'agent écoute sur le port 8432
    app.run(host="0.0.0.0", port=8432)
