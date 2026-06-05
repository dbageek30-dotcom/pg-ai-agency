import os
import subprocess
from fastapi import FastAPI, HTTPException, Header, Depends
from pydantic import BaseModel
import psycopg2
from psycopg2.extras import RealDictCursor

app = FastAPI(title="PostgreSQL AI Remote Agent API", version="1.8.1")

# --- 1. CHARGEMENT DES VARIABLES D'ENVIRONNEMENT (INJECTÉES PAR SYSTEMD) ---
EXPECTED_TOKEN = os.getenv("REMOTE_AGENT_TOKEN", "TOKEN_GENERE_A_LA_VOLEE_S1Cr1t")

PG_DB = os.getenv("PG_DB", "postgres")
PG_USER = os.getenv("PG_USER", "pgagent")
PG_PASS = os.getenv("PG_PASS")
PG_HOST = os.getenv("PG_HOST", "localhost")

# Chemins physiques découverts par le script d'installation
PG_CONF_PATH = os.getenv("PG_CONF_PATH", "/etc/postgresql/18/main/postgresql.conf")
PG_HBA_PATH = os.getenv("PG_HBA_PATH", "/etc/postgresql/18/main/pg_hba.conf")

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
    """Vérification de l'état de l'agent et exposition des capacités"""
    return {
        "status": "online",
        "agent": "postgresql-remote-agent",
        "database_user": PG_USER,
        "configured_paths": {
            "postgresql.conf": PG_CONF_PATH,
            "pg_hba.conf": PG_HBA_PATH
        }
    }

@app.post("/api/v1/execute/sql", dependencies=[Depends(verify_token)])
async def execute_sql(payload: SQLPayload):
    """Exécute une vraie requête SQL sur le cluster local via l'utilisateur dédié"""
    conn = None
    try:
        # Connexion avec les identifiants de l'utilisateur pgagent
        conn = psycopg2.connect(
            dbname=PG_DB,
            user=PG_USER,
            password=PG_PASS,
            host=PG_HOST,
            cursor_factory=RealDictCursor
        )
        conn.autocommit = True
        
        with conn.cursor() as cur:
            cur.execute(payload.query)
            
            # Si la requête retourne des données (SELECT, SHOW, EXPLAIN...)
            if cur.description:
                rows = cur.fetchall()
                return {
                    "status": "success",
                    "message": "Requête exécutée avec succès",
                    "data": rows
                }
            else:
                return {
                    "status": "success",
                    "message": "Commande exécutée avec succès (aucune ligne retournée)",
                    "data": []
                }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Erreur d'exécution PostgreSQL : {str(e)}",
            "data": []
        }
    finally:
        if conn:
            conn.close()

@app.post("/api/v1/execute/config", dependencies=[Depends(verify_token)])
async def modify_config(payload: ConfigPayload):
    """Modifie de manière sécurisée les fichiers de configuration via la règle Sudoers"""
    
    # Résolution du fichier cible basé sur la découverte de l'installateur
    if payload.target == "postgresql.conf":
        target_file = PG_CONF_PATH
    elif payload.target == "pg_hba.conf":
        target_file = PG_HBA_PATH
    else:
        raise HTTPException(status_code=400, detail="Cible de configuration invalide (postgresql.conf ou pg_hba.conf uniquement)")

    if not target_file or not os.path.exists(target_file):
        return {
            "status": "error",
            "message": f"Le chemin du fichier cible '{payload.target}' n'est pas configuré ou introuvable sur le système.",
            "output": ""
        }

    try:
        # Exécution chirurgicale via Sudo + Tee sans casser le mode du répertoire PGDATA
        cmd = ["sudo", "/usr/bin/tee", "-a", target_file]
        process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stdout, stderr = process.communicate(input=payload.line_to_add + "\n")
        
        if process.returncode != 0:
            return {
                "status": "error",
                "message": f"Échec de l'écriture via Sudo tee : {stderr.strip()}",
                "output": ""
            }

        # --- RECHARGEMENT DE LA CONFIGURATION (RELOAD) ---
        reload_success = False
        
        # Tentative 1 : Rechargement via SQL natif (Si le rôle pgagent possède l'attribut pg_signal_backend)
        try:
            conn = psycopg2.connect(dbname=PG_DB, user=PG_USER, password=PG_PASS, host=PG_HOST)
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute("SELECT pg_reload_conf();")
                reload_success = True
            conn.close()
        except Exception:
            pass  # Si échec, on bascule automatiquement sur la méthode système

        # Tentative 2 : Repli via commande système pg_ctl whitelisto-sudoers
        if not reload_success:
            try:
                subprocess.run(
                    ["sudo", "-u", "postgres", "/usr/bin/pg_ctl", "reload"], 
                    stdout=subprocess.DEVNULL, 
                    stderr=subprocess.DEVNULL,
                    timeout=5
                )
            except Exception:
                return {
                    "status": "success",
                    "message": f"Ligne ajoutée dans {payload.target}, mais le signal de rechargement (reload) a expiré ou a échoué.",
                    "output": payload.line_to_add
                }

        return {
            "status": "success",
            "message": f"Ligne ajoutée avec succès dans {payload.target} et configuration PostgreSQL rechargée.",
            "output": payload.line_to_add
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Erreur système lors de la modification de la configuration : {str(e)}",
            "output": ""
        }
