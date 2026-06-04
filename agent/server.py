import os
from fastapi import FastAPI, HTTPException, Header, Depends
from pydantic import BaseModel

app = FastAPI(title="PG 18 Remote Agent API")

# Récupération sécurisée du Token défini par le script d'installation
EXPECTED_TOKEN = os.getenv("REMOTE_AGENT_TOKEN", "TOKEN_GENERE_A_LA_VOLEE_S1Cr1t")

class SQLPayload(BaseModel):
    query: str

class SystemPayload(BaseModel):
    command: str

def verify_token(authorization: str = Header(None)):
    """Vérification stricte du Bearer Token dans les headers HTTP"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")
    
    token = authorization.split(" ")[1]
    if token != EXPECTED_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid Security Token")
    return token

@app.get("/health")
def health_check():
    return {"status": "online", "agent": "postgresql-18-agent"}

@app.post("/api/v1/execute/sql", dependencies=[Depends(verify_token)])
async def execute_sql(payload: SQLPayload):
    # C'est ici qu'on branchera la connexion à ta base locale Postgres 18 plus tard
    return {"status": "success", "message": f"Ordre SQL reçu : {payload.query}", "data": []}

@app.post("/api/v1/execute/system", dependencies=[Depends(verify_token)])
async def execute_system(payload: SystemPayload):
    # C'est ici qu'on branchera ton script discovery.py pour valider et lancer la commande
    return {"status": "success", "message": f"Ordre Système reçu : {payload.command}", "output": "Simulation active"}
