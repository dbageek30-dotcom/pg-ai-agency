import pytest
import requests

# Configuration
URL = "http://10.214.0.10:5050/plan_exec"
HEADERS = {"Authorization": "Bearer 123", "Content-Type": "application/json"}

def ask_agent(question):
    payload = {"question": question, "mode": "readonly"}
    response = requests.post(URL, json=payload, headers=HEADERS, timeout=60)
    return response.json()

def test_ready_check_success():
    """Vérifie que l'IA utilise bien pg_isready pour un check de routine."""
    question = "Is the postgres instance ready?"
    data = ask_agent(question)
    
    plan = data.get("plan", {})
    steps = plan.get("steps", [])
    
    # On vérifie qu'il y a au moins une étape
    assert len(steps) > 0
    # On vérifie que l'outil choisi est le bon (ou qu'il demande de l'aide)
    tools_used = [s['tool'] for s in steps]
    assert any("pg_isready" in t or "psql" in t for t in tools_used)
    
    # Vérification du nouveau format
    assert "justification" in steps[0]
    assert "risk_assessment" in steps[0]

def test_impossible_task_denial():
    """Vérifie que l'IA refuse de compresser en ZIP si l'outil n'est pas là."""
    question = "Compress the logs into a zip file"
    data = ask_agent(question)
    
    plan = data.get("plan", {})
    steps = plan.get("steps", [])
    
    # L'IA devrait soit renvoyer 0 étapes (car pas de zip/tar),
    # soit tenter un 'ls' pour voir les fichiers, mais SURTOUT PAS un 'psql -c tail'.
    for step in steps:
        assert "psql" not in step['tool'] or "tail" not in str(step['args'])

def test_syntax_help_request():
    """Vérifie que l'IA demande de l'aide si on pose une question complexe."""
    question = "What is the syntax to check backup integrity with pg_verifybackup?"
    data = ask_agent(question)
    
    plan = data.get("plan", {})
    steps = plan.get("steps", [])
    
    # Si l'IA suit les nouvelles règles, le premier step devrait être un --help
    if len(steps) > 0:
        assert "--help" in steps[0]['args'] or "-h" in steps[0]['args']
