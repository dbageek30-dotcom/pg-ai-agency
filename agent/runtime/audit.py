import sqlite3
import os
from datetime import datetime

AUDIT_DB_PATH = "/opt/pgagent/runtime/audit.db"

# Fallback pour le dev
if not os.path.exists("/opt/pgagent"):
    AUDIT_DB_PATH = os.path.join(os.path.dirname(__file__), "audit.db")

def init_db():
    """Crée la table d'audit si elle n'existe pas."""
    os.makedirs(os.path.dirname(AUDIT_DB_PATH), exist_ok=True)
    with sqlite3.connect(AUDIT_DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                command TEXT,
                executed_command TEXT,
                exit_code INTEGER,
                stdout TEXT,
                stderr TEXT
            )
        """)

def log_execution(command, executed_command, exit_code, stdout, stderr):
    """Enregistre une exécution dans la base SQLite."""
    try:
        with sqlite3.connect(AUDIT_DB_PATH) as conn:
            conn.execute(
                "INSERT INTO audit_logs (timestamp, command, executed_command, exit_code, stdout, stderr) VALUES (?, ?, ?, ?, ?, ?)",
                (datetime.now().isoformat(), command, executed_command, exit_code, stdout, stderr)
            )
    except Exception as e:
        # On utilise print ici car le logger de server.py n'est pas forcément importé ici
        print(f"CRITICAL: Failed to write audit log: {e}")

def get_last_logs(limit=10):
    """Récupère les derniers logs pour l'API /audit."""
    try:
        with sqlite3.connect(AUDIT_DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM audit_logs ORDER BY id DESC LIMIT ?", (limit,))
            return [dict(row) for row in cursor.fetchall()]
    except Exception:
        return []
