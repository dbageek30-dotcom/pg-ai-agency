import os
import readline
import sys
import json
import argparse
import requests
from dotenv import load_dotenv
import ollama

# Alignement des chemins pour l'import de l'expert RAG
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import agency.expert as expert  # Contient clear_history, get_recent_history, etc.

load_dotenv()

ORCHESTRATOR_MODEL = os.getenv("ORCHESTRATOR_MODEL", "qwen2.5:14b-instruct")
REMOTE_AGENT_URL = os.getenv("REMOTE_AGENT_URL", "http://localhost:8432")
REMOTE_AGENT_TOKEN = os.getenv("REMOTE_AGENT_TOKEN", "TOKEN_GENERE_A_LA_VOLEE_S1Cr1t")
CACHE_14B_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_payload_cache.json")

VERBOSE = False
readline.parse_and_bind("tab: complete")

# ---------------------------------------------------------------------------
# GESTION DU CACHE DE CHARGE UTILE (LLM 14B)
# ---------------------------------------------------------------------------
def load_payload_cache() -> dict:
    if os.path.exists(CACHE_14B_PATH):
        try:
            with open(CACHE_14B_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_payload_cache(cache_data: dict):
    try:
        with open(CACHE_14B_PATH, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        if VERBOSE:
            print(f"⚠️ Erreur lors de l'écriture du cache payload : {e}")

# ---------------------------------------------------------------------------
# COMMUNICATIONS RÉSEAU
# ---------------------------------------------------------------------------
def call_pgagent(endpoint: str, payload: dict) -> dict:
    """Envoie l'ordre HTTP au service pgagent distant"""
    url = f"{REMOTE_AGENT_URL}/api/v1/execute/{endpoint}"
    headers = {
        "Authorization": f"Bearer {REMOTE_AGENT_TOKEN}",
        "Content-Type": "application/json"
    }
    if VERBOSE:
        print(f"   ⚙️ [DEBUG NETWORK] POST {url}")
        print(f"   ⚙️ [DEBUG NETWORK] Payload: {json.dumps(payload)}")
        
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=15)
        return response.json()
    except Exception as e:
        return {"status": "error", "message": f"Échec de connexion à pgagent : {e}"}

# ---------------------------------------------------------------------------
# COUCHE EXTRACTION ET DIRECTIVES LLM
# ---------------------------------------------------------------------------
def parse_action_with_llm(user_question: str, rag_output: str) -> dict:
    """Le LLM 14B extrait le code SQL ou la modification de configuration de la réponse du RAG"""
    cache_key = user_question.strip().lower()
    payload_cache = load_payload_cache()

    # 1. Tentative de récupération depuis le cache local du 14B
    if cache_key in payload_cache:
        if VERBOSE:
            print("   🧠 [2/3] Extraction : ⚡ [PAYLOAD CACHE HIT] Récupération de la commande validée...")
        return payload_cache[cache_key]

    # 2. Cache Miss : Interrogation d'Ollama
    prompt = f"""You are a strict API translation layer. Your ONLY job is to convert a technical recommendation into a raw JSON object.
You are strictly FORBIDDEN to reply with prose, explanations, markdown blocks, or warnings. Return raw JSON.

Technical Recommendation to parse:
\"\"\"
{rag_output}
\"\"\"

Expected JSON schema if it is a regular SQL query (SELECT, SHOW, ALTER SYSTEM, etc.):
{{
    "type": "sql",
    "query": "the raw SQL query string"
}}

Expected JSON schema if it is a physical parameter configuration change (shared_buffers, max_connections, etc.):
{{
    "type": "config",
    "target": "postgresql.conf",
    "line_to_add": "parameter = 'value'"
}}"""

    ollama_host = os.getenv("OLLAMA_HOST", "http://10.198.0.4:11434")

    if VERBOSE:
        print(f"   ⚙️ [DEBUG LLM] Connexion ciblée vers Ollama : {ollama_host}")
        print(f"   ⚙️ [DEBUG LLM] Modèle demandé : {ORCHESTRATOR_MODEL}")

    try:
        client = ollama.Client(host=ollama_host)
        response = client.chat(
            model=ORCHESTRATOR_MODEL,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.0},
            format="json"
        )
        
        raw_output = response['message']['content'].strip()
        
        if VERBOSE:
            print(f"   ⚙️ [DEBUG LLM] Réponse brute reçue : {raw_output}")
            
        parsed_payload = json.loads(raw_output)
        
        # Sauvegarde au cache si l'extraction est conforme
        if "type" in parsed_payload and ( "query" in parsed_payload or "line_to_add" in parsed_payload ):
            payload_cache[cache_key] = parsed_payload
            save_payload_cache(payload_cache)
            
        return parsed_payload

    except Exception as e:
        if VERBOSE:
            print(f"   ❌ [DEBUG LLM ERROR] L'appel Ollama (extraction) a échoué : {e}")
        return {"type": "none", "message": f"Erreur d'extraction : {e}"}

# ---------------------------------------------------------------------------
# PIPELINE D'EXÉCUTION PRINCIPAL
# ---------------------------------------------------------------------------
def execute_action_pipeline(user_question: str):
    """MODE AGENT ACTIF : RAG -> Extraction de commande -> Exécution sur VM-PG -> Synthèse"""
    print("\n📚 [1/3] RAG : Recherche de la procédure d'action...")
    rag_response = expert.ask_rag(user_question)
    
    print(f"🧠 [2/3] Extraction : Génération de la charge utile via {ORCHESTRATOR_MODEL}...")
    action = parse_action_with_llm(user_question, rag_response)
    
    if action.get("type") not in ["sql", "config"]:
        print("⚠️ [ERREUR] L'Orchestrateur n'a pas pu isoler une commande structurelle reconnue par l'agent.")
        return

    # Routage unifié vers le serveur d'exécution distant
    print(f"📡 [3/3] Exécution : Envoi de l'ordre ({action['type'].upper()}) à la vm-pg...")
    if action["type"] == "sql":
        if not action.get("query"):
            print("⚠️ [ERREUR] Requête SQL vide.")
            return
        execution_result = call_pgagent("sql", {"query": action["query"]})
        sent_command = action["query"]
    else:
        if not action.get("target") or not action.get("line_to_add"):
            print("⚠️ [ERREUR] Paramètres de configuration incomplets.")
            return
        execution_result = call_pgagent("config", {
            "target": action["target"],
            "line_to_add": action["line_to_add"]
        })
        sent_command = f"[{action['target']}] -> {action['line_to_add']}"

    if VERBOSE:
        print(f"   ⚙️ [DEBUG NETWORK] Retour brut reçu du serveur : {json.dumps(execution_result, indent=2)}")

    # Restitution finale (Synthèse métier rédigée)
    print("\n✍️ Syntèse du rapport d'exécution...")
    final_prompt = f"""You are an expert DBA. You executed an automated action on the remote server.
Action Sent: {sent_command}
Server Result: {json.dumps(execution_result)}

Provide a concise, professional summary of the results returned by the server to the user. State clearly if the execution was a success or failure."""

    try:
        ollama_host = os.getenv("OLLAMA_HOST", "http://10.198.0.4:11434")
        client = ollama.Client(host=ollama_host)
        
        response = client.chat(model=ORCHESTRATOR_MODEL, messages=[{"role": "user", "content": final_prompt}])
        print(f"\n🎯 [RAPPORT ACTION] :\n{response['message']['content'].strip()}\n")
    except Exception as e:
        print(f"❌ Erreur lors de la génération du rapport final : {e}")

# ---------------------------------------------------------------------------
# SCRIPT ENTRYPOINT
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Tower of Control - Central AI Orchestrator for PostgreSQL 18")
    parser.add_argument("-v", "--verbose", action="store_true", help="Active les logs de debug sous le capot dès le démarrage")
    args = parser.parse_args()

    VERBOSE = args.verbose
    expert.VERBOSE = args.verbose

    print("\n" + "="*75)
    print("🗼 POSTGRESQL 18 AGENCY - CENTRAL ORCHESTRATOR")
    print(f"    Mode verbeux initial : {'ACTIVÉ 🟢' if VERBOSE else 'DÉSACTIVÉ ⚪'}")
    print("    -> Posez une question directement pour le mode INFORMATION 📖")
    print("    -> Préfixez par /a ou /action pour déclencher une ACTION RÉELLE ⚡")
    print("    -> Commandes :  /c (clear)  |  /h (history)  |  /d [id] (del cache sem)  |  /v (verbose)  |  /clear-payload")
    print("="*75 + "\n")
    
    while True:
        try:
            prompt_prefix = "agency (verbose) > " if VERBOSE else "agency > "
            user_input = input(prompt_prefix).strip()
            if not user_input: continue
            if user_input.lower() in ['q', 'quit', 'exit']: break
            
            # ------------------------------------------------------------------
            # 1. ROUTAGE DES INTENTIONS D'ACTION
            # ------------------------------------------------------------------
            if user_input.startswith(('/a ', '/action ')):
                clean_question = user_input.split(maxsplit=1)[1]
                execute_action_pipeline(clean_question)
                continue
            
            # ------------------------------------------------------------------
            # 2. INTERCEPTION DES COMMANDES INTERFACE
            # ------------------------------------------------------------------
            elif user_input.startswith('/'):
                parts = user_input.split()
                cmd = parts[0].lower()
                
                if cmd in ['/clear', '/c']:
                    expert.clear_history()
                    print("🧠 [SYSTEM] Session réinitialisée. (Le cache sémantique Postgres reste actif !)\n")
                    
                elif cmd in ['/history', '/h']:
                    history = expert.get_recent_history(limit=10)
                    if not history:
                        print("📜 [HISTORY] Aucun message dans la session actuelle.\n")
                    else:
                        print("\n📜 --- HISTORIQUE DE LA SESSION ---")
                        for msg in history:
                            prefix = "👤 [VOUS]" if msg['role'] == 'user' else "🤖 [EXPERT]"
                            print(f"{prefix} : {msg['content']}")
                        print("-----------------------------------\n")
                        
                elif cmd in ['/delete', '/d']:
                    if len(parts) < 2:
                        print("❌ [ERREUR] Syntaxe incorrecte. Utilisation : /d [ID_DU_CACHE]\n")
                    else:
                        target_id = parts[1]
                        if expert.delete_cache_entry(target_id):
                            print(f"✂️  [CACHE] L'entrée ID #{target_id} a été retirée définitivement du cache RAG.\n")
                        else:
                            print(f"⚠️ [CACHE] Aucune entrée trouvée avec l'ID #{target_id} dans le cache RAG.\n")
                            
                elif cmd == '/clear-payload':
                    if os.path.exists(CACHE_14B_PATH):
                        os.remove(CACHE_14B_PATH)
                        print("🗑️  [CACHE 14B] Le cache local des charges utiles d'extraction a été vidé !\n")
                    else:
                        print("ℹ️  [CACHE 14B] Le cache d'extraction était déjà vide.\n")

                elif cmd == '/v':
                    VERBOSE = not VERBOSE
                    expert.VERBOSE = VERBOSE
                    print(f"🔬 [SYSTEM] Mode verbeux global basculé : {'ACTIVÉ 🟢' if VERBOSE else 'DÉSACTIVÉ ⚪'}\n")
                
                else:
                    print(f"❌ [ERREUR] Commande '{cmd}' inconnue.\n")
                continue
            
            # ------------------------------------------------------------------
            # 3. MODE INFORMATION PAR DÉFAUT
            # ------------------------------------------------------------------
            else:
                print("\n📖 [MODE INFORMATION] Consultation de la base de connaissances...")
                reponse = expert.ask_rag(user_input)
                print(f"\n🤖 [EXPERT PG18] :\n{reponse}\n")
                
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"❌ Erreur générale : {e}")

    # Nettoyage propre du pool Postgres
    if expert.PG_POOL:
        if VERBOSE:
            print("\n[SHUTDOWN] Fermeture du pool de connexions PostgreSQL...")
        expert.PG_POOL.closeall()
