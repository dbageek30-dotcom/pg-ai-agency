import os
import sys
import json
import requests
from dotenv import load_dotenv
import ollama

# Alignement des chemins pour l'import de l'expert RAG
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agency.expert import ask_rag

load_dotenv()

ORCHESTRATOR_MODEL = os.getenv("ORCHESTRATOR_MODEL", "qwen2.5:14b-instruct")
REMOTE_AGENT_URL = os.getenv("REMOTE_AGENT_URL", "http://localhost:8432")
REMOTE_AGENT_TOKEN = os.getenv("REMOTE_AGENT_TOKEN", "TOKEN_GENERE_A_LA_VOLEE_S1Cr1t")

VERBOSE = False

def call_pgagent(endpoint: str, payload: dict) -> dict:
    """Envoie l'ordre HTTP au service pgagent distant"""
    url = f"{REMOTE_AGENT_URL}/api/v1/execute/{endpoint}"
    headers = {
        "Authorization": f"Bearer {REMOTE_AGENT_TOKEN}",
        "Content-Type": "application/json"
    }
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=15)
        return response.json()
    except Exception as e:
        return {"status": "error", "message": f"Échec de connexion à pgagent : {e}"}

def parse_action_with_llm(rag_output: str) -> dict:
    """Le LLM 14B extrait le code SQL ou la commande Bash de la réponse du RAG"""
    prompt = f"""You are an infrastructure automation compiler. Analyze this technical expert recommendation:
\"\"\"
{rag_output}
\"\"\"

Extract the exact command or query to execute.
Return a strict JSON object. Do NOT include markdown blocks like ```json.

Allowed system commands: ["df -h", "free -m", "uptime", "pg_ctl status"]

JSON Format expected:
{{
    "type": "sql" | "system",
    "payload": "the exact raw query or allowed system command"
}}"""

    try:
        response = ollama.chat(
            model=ORCHESTRATOR_MODEL,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.0},
            format="json"
        )
        return json.loads(response['message']['content'].strip())
    except Exception as e:
        return {"type": "none", "payload": f"Erreur d'extraction : {e}"}

def execute_action_pipeline(user_question: str):
    """MODE AGENT ACTIF : RAG -> Extraction de commande -> Exécution sur VM-PG -> Synthèse"""
    print("\n📚 [1/3] RAG : Recherche de la procédure d'action...")
    rag_response = ask_rag(user_question)
    
    print(f"🧠 [2/3] Extraction : Génération de la charge utile via {ORCHESTRATOR_MODEL}...")
    action = parse_action_with_llm(rag_response)
    
    if action.get("type") not in ["sql", "system"] or not action.get("payload"):
        print("⚠️ [ERREUR] L'Orchestrateur n'a pas pu isoler une commande sécurisée à exécuter.")
        print(f"Recommandation théorique originale :\n{rag_response}")
        return

    # Routage vers pgagent
    print(f"📡 [3/3] Exécution : Envoi de l'ordre ({action['type'].upper()}) à la vm-pg...")
    if action["type"] == "sql":
        execution_result = call_pgagent("sql", {"query": action["payload"]})
    else:
        execution_result = call_pgagent("system", {"command": action["payload"]})

    # Restitution finale
    print("\n✍️ Syntèse du rapport d'exécution :")
    final_prompt = f"""You are an expert DBA. You executed an automated action on the remote server.
Action Sent: {action['payload']}
Server Result: {json.dumps(execution_result)}

Provide a concise, professional summary of the results returned by the server to the user. State clearly if the execution was a success or failure."""

    try:
        response = ollama.chat(model=ORCHESTRATOR_MODEL, messages=[{"role": "user", "content": final_prompt}])
        print(f"\n🎯 [RAPPORT ACTION] :\n{response['message']['content'].strip()}\n")
    except Exception as e:
        print(f"❌ Erreur lors de la génération du rapport final : {e}")

if __name__ == "__main__":
    print("\n" + "="*75)
    print("🗼 POSTGRESQL 18 AGENCY - CENTRAL ORCHESTRATOR")
    print("   -> Posez une question directement pour le mode INFORMATION 📖")
    print("   -> Préfixez par /a ou /action pour déclencher une ACTION RÉELLE ⚡")
    print("="*75 + "\n")
    
    while True:
        try:
            user_input = input("agency > ").strip()
            if not user_input: continue
            if user_input.lower() in ['q', 'quit', 'exit']: break
            
            # Routage des intentions
            if user_input.startswith(('/a ', '/action ')):
                # On extrait la commande en enlevant le préfixe
                clean_question = user_input.split(maxsplit=1)[1]
                execute_action_pipeline(clean_question)
            else:
                # MODE INFORMATION : On appelle directement le RAG, pas d'exécution réseau
                print("\n📖 [MODE INFORMATION] Consultation de la base de connaissances...")
                reponse = ask_rag(user_input)
                print(f"\n🤖 [EXPERT PG18] :\n{reponse}\n")
                
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"❌ Erreur : {e}")
