import os
import json
import subprocess
from fastapi import FastAPI, HTTPException, Header, Depends
from pydantic import BaseModel
import psycopg2
from psycopg2.extras import RealDictCursor

app = FastAPI(title="PostgreSQL AI Remote Agent API", version="1.8.2")

# --- 1. CHARGEMENT CONFIGURATION & DISCOVERY TRipartie ---
EXPECTED_TOKEN = os.getenv("REMOTE_AGENT_TOKEN", "TOKEN_GENERE_A_LA_VOLEE_S1Cr1t")

PG_DB = os.getenv("PG_DB", "postgres")
PG_USER = os.getenv("PG_USER", "pgagent")
PG_PASS = os.getenv("PG_PASS")
PG_HOST = os.getenv("PG_HOST", "localhost")

# Chargement dynamique depuis le fichier discovery.json
BASE_DIR = "/opt/pgagent/bin"
DISCOVERY_PATH = os.path.join(BASE_DIR, "discovery.json")

# Fallbacks par défaut si le fichier json n'existe pas encore
PG_CONF_PATH = "/var/lib/postgresql/18/data/postgresql.conf"
PG_HBA_PATH = "/var/lib/postgresql/18/data/pg_hba.conf"
PG_CTL_BIN = "/usr/bin/pg_ctl"
TEE_BIN = "/usr/bin/tee"

if os.path.exists(DISCOVERY_PATH):
    try:
        with open(DISCOVERY_PATH, "r") as f:
            disco = json.load(f)
            # 1. Topologie des fichiers
            PG_CONF_PATH = disco.get("postgresql_topology", {}).get("postgresql.conf", PG_CONF_PATH)
            PG_HBA_PATH = disco.get("postgresql_topology", {}).get("pg_hba.conf", PG_HBA_PATH)
            # 2. Binaires Postgres & Système
            PG_CTL_BIN = disco.get("postgresql_binaries", {}).get("pg_ctl", PG_CTL_BIN)
            TEE_BIN = disco.get("system_binaries", {}).get("tee", TEE_BIN)
    except Exception:
        pass # Reste sur les fallbacks en cas de corruption de lecture

# --- 2. MODÈLES DE DONNÉES PYDANTIC ---
class SQLPayload(BaseModel):
    query: str

class ConfigPayload(BaseModel):
    target: str  # "postgresql.conf" ou "pg_hba.conf"
    line_to_add: str

# --- 3. GUARDRAIL D'AUTHENTIFICATION ---
def verify_token(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")
    token = authorization.split(" ")[1]
    if token != EXPECTED_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid Security Token")
    return token

# --- 4. POINTS DE TERMINAISON (ROUTES API) ---

@app.get("/health")
def health_check():
    """Vérification de l'état de l'agent et exposition des capacités réelles au LLM"""
    return {
        "status": "online",
        "agent": "postgresql-remote-agent",
        "database_user": PG_USER,
        "configured_paths": {
            "postgresql.conf": PG_CONF_PATH,
            "pg_hba.conf": PG_HBA_PATH
        },
        "resolved_binaries": {
            "pg_ctl": PG_CTL_BIN,
            "tee": TEE_BIN
        }
    }

@app.post("/api/v1/execute/sql", dependencies=[Depends(verify_token)])
async def execute_sql(payload: SQLPayload):
    """Exécute une vraie requête SQL sur le cluster local via l'utilisateur dédié"""
    conn = None
    try:
        conn = psycopg2.connect(
            dbname=PG_DB, user=PG_USER, password=PG_PASS, host=PG_HOST,
            cursor_factory=RealDictCursor
        )
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(payload.query)
            if cur.description:
                rows = cur.fetchall()
                return {"status": "success", "message": "Requête exécutée avec succès", "data": rows}
            else:
                return {"status": "success", "message": "Commande exécutée avec succès", "data": []}
    except Exception as e:
        return {"status": "error", "message": f"Erreur d'exécution PostgreSQL : {str(e)}", "data": []}
    finally:
        if conn: conn.close()

@app.post("/api/v1/execute/config", dependencies=[Depends(verify_token)])
async def modify_config(payload: ConfigPayload):
    """Modifie les fichiers de configuration via le binaire tee découvert"""
    if payload.target == "postgresql.conf":
        target_file = PG_CONF_PATH
    elif payload.target == "pg_hba.conf":
        target_file = PG_HBA_PATH
    else:
        raise HTTPException(status_code=400, detail="Cible invalide (postgresql.conf ou pg_hba.conf)")

    if not target_file or not os.path.exists(target_file):
        return {
            "status": "error",
            "message": f"Le fichier cible '{payload.target}' n'est pas configuré ou introuvable.",
            "output": ""
        }

    try:
        # Utilisation du binaire tee dynamiquement découvert (Debian vs RHEL)
        cmd = ["sudo", TEE_BIN, "-a", target_file]
        process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stdout, stderr = process.communicate(input=payload.line_to_add + "\n")
        
        if process.returncode != 0:
            return {"status": "error", "message": f"Échec de l'écriture via Sudo tee : {stderr.strip()}", "output": ""}

        # --- RECHARGEMENT DE LA CONFIGURATION (RELOAD) ---
        reload_success = False
        
        # Tentative 1 : Rechargement via SQL natif
        try:
            conn = psycopg2.connect(dbname=PG_DB, user=PG_USER, password=PG_PASS, host=PG_HOST)
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute("SELECT pg_reload_conf();")
                reload_success = True
            conn.close()
        except Exception:
            pass

        # Tentative 2 : Repli via le vrai binaire pg_ctl découvert (Debian vs RHEL)
        if not reload_success:
            try:
                subprocess.run(
                    ["sudo", "-u", "postgres", PG_CTL_BIN, "reload"], 
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5
                )
            except Exception:
                return {
                    "status": "success",
                    "message": f"Ligne ajoutée dans {payload.target}, mais le reload a échoué ou expiré.",
                    "output": payload.line_to_add
                }

        return {
            "status": "success",
            "message": f"Ligne ajoutée avec succès dans {payload.target} et configuration PostgreSQL rechargée.",
            "output": payload.line_to_add
        }

    except Exception as e:
        return {"status": "error", "message": f"Erreur système : {str(e)}", "output": ""}
