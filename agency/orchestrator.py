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
import agency.expert as expert  

load_dotenv()

ORCHESTRATOR_MODEL = os.getenv("ORCHESTRATOR_MODEL", "qwen2.5:32b-instruct") # Idéalement 30B+
REMOTE_AGENT_URL = os.getenv("REMOTE_AGENT_URL", "http://localhost:8432")
REMOTE_AGENT_TOKEN = os.getenv("REMOTE_AGENT_TOKEN", "123")
CACHE_ORCH_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_payload_cache.json")

VERBOSE = False
readline.parse_and_bind("tab: complete")

def load_payload_cache() -> dict:
    if os.path.exists(CACHE_ORCH_PATH):
        try:
            with open(CACHE_ORCH_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_payload_cache(cache_data: dict):
    try:
        with open(CACHE_ORCH_PATH, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        if VERBOSE:
            print(f"⚠️ Erreur lors de l'écriture du cache payload : {e}")

def call_pgagent(endpoint: str, payload: dict) -> dict:
    url = f"{REMOTE_AGENT_URL}/api/v1/execute/{endpoint}"
    headers = {
        "Authorization": f"Bearer {REMOTE_AGENT_TOKEN}",
        "Content-Type": "application/json"
    }
    if VERBOSE:
        print(f"    ⚙️ [DEBUG NETWORK] POST {url}")
        print(f"    ⚙️ [DEBUG NETWORK] Payload: {json.dumps(payload)}")
        
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=15)
        return response.json()
    except Exception as e:
        return {"status": "error", "message": f"Échec de connexion à pgagent : {e}"}

def get_agent_context() -> dict:
    url = f"{REMOTE_AGENT_URL}/health"
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            return response.json()
    except Exception:
        pass
    return {}

def parse_action_with_llm(user_question: str, rag_output: str, agent_context: dict) -> dict:
    cache_key = user_question.strip().lower()
    payload_cache = load_payload_cache()

    if cache_key in payload_cache:
        if VERBOSE:
            print("    🧠 [2/3] Extraction : ⚡ [PAYLOAD CACHE HIT] Récupération de la commande validée...")
        return payload_cache[cache_key]

    paths_context = agent_context.get("configured_paths", {})
    allowed_cmds = agent_context.get("whitelisted_system_commands", [])
    
    context_str = f"""
--- REAL REMOTE AGENT CONTEXT ---
PostgreSQL Configured Paths:
- Target Database Directory (PGDATA): "/var/lib/postgresql/18/data" (STRICT MONO-INSTANCE)
- postgresql.conf path: "{paths_context.get('postgresql.conf', 'Unknown')}"
- pg_hba.conf path: "{paths_context.get('pg_hba.conf', 'Unknown')}"

Strictly Allowed Base System/PostgreSQL Commands (Whitelist):
{json.dumps(allowed_cmds)}
---------------------------------
"""

    prompt = f"""You are a strict API translation layer. Your ONLY job is to convert a technical recommendation into a raw JSON object matching one of the schemas below.
You are strictly FORBIDDEN to reply with prose, explanations, markdown blocks, or warnings. Return raw JSON.

{context_str}

Technical Recommendation to parse:
\"\"\"
{rag_output}
\"\"\"

User original intent: "{user_question}"

CRITICAL PIPELINE ROUTING RULES:
1. ANY request that modifies a PostgreSQL parameter (e.g., shared_buffers, port, max_connections) MUST EXCLUSIVELY use the "type": "config" schema.
2. You are STRICTLY FORBIDDEN to use system commands like 'tee', 'sed', 'echo' to modify or append to "postgresql.conf" or "pg_hba.conf".
3. The cluster path is strictly "/var/lib/postgresql/18/data". Do not assume or invent any other directory like data2.

Expected JSON schema if it is a regular SQL query (SELECT, SHOW, ALTER SYSTEM, etc.):
{{
    "type": "sql",
    "query": "the raw SQL query string"
}}

Expected JSON schema if it is a physical parameter configuration change:
CRITICAL: The "target" field MUST be EXACTLY the string "postgresql.conf" or "pg_hba.conf". DO NOT put absolute paths here.
{{
    "type": "config",
    "target": "postgresql.conf",
    "line_to_add": "parameter = 'value'"
}}

Expected JSON schema if it requires executing an allowed system tool or PostgreSQL utility:
{{
    "type": "system",
    "command": "base_command_name_only",
    "arguments": ["arg1", "arg2"]
}}"""

    ollama_host = os.getenv("OLLAMA_HOST", "http://10.198.0.4:11434")

    try:
        client = ollama.Client(host=ollama_host)
        response = client.chat(
            model=ORCHESTRATOR_MODEL,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.0},
            format="json"
        )
        
        raw_output = response['message']['content'].strip()
        parsed_payload = json.loads(raw_output)
        
        # Validation des clés minimales pour éviter un crash d'exécution
        if "type" in parsed_payload and any(k in parsed_payload for k in ["query", "line_to_add", "command"]):
            payload_cache[cache_key] = parsed_payload
            save_payload_cache(payload_cache)
            return parsed_payload

    except Exception as e:
        if VERBOSE:
            print(f"    ❌ [DEBUG LLM ERROR] L'appel Ollama (extraction) a échoué : {e}")
    return {"type": "none", "message": "Extraction invalide ou impossible."}

def execute_action_pipeline(user_question: str):
    agent_context = get_agent_context()

    print("\n📚 [1/3] RAG : Recherche de la procédure d'action...")
    rag_response = expert.ask_rag(user_question)
    
    if rag_response == "DIRECT_SYSTEM_ACTION":
        rag_response = f"Direct infrastructure execution requested by user. Translate the user query directly using the provided remote agent whitelist context."

    print(f"🧠 [2/3] Extraction : Génération de la charge utile via {ORCHESTRATOR_MODEL}...")
    action = parse_action_with_llm(user_question, rag_response, agent_context)
    
    if action.get("type") not in ["sql", "config", "system"]:
        print("⚠️ [ERREUR] L'Orchestrateur n'a pas pu isoler une commande structurelle reconnue par l'agent.")
        return

    # Guardrail : Sécurisation de la cible de config pour le mono-instance
    if action["type"] == "config":
        target_clean = os.path.basename(action.get("target", ""))
        if target_clean not in ["postgresql.conf", "pg_hba.conf"]:
            print(f"⚠️ [GUARDRAIL] Cible de configuration invalide détectée : {action.get('target')}")
            return
        action["target"] = target_clean

    print(f"📡 [3/3] Exécution : Envoi de l'ordre ({action['type'].upper()}) à la vm-pg...")
    execution_result = {}
    sent_command = ""

    if action["type"] == "sql":
        if not action.get("query"):
            print("⚠️ [ERREUR] Requête SQL définie mais vide.")
            return
        execution_result = call_pgagent("sql", {"query": action["query"]})
        sent_command = action["query"]

    elif action["type"] == "config":
        if not action.get("line_to_add"):
            print("⚠️ [ERREUR] Paramètres de configuration incomplets.")
            return
        execution_result = call_pgagent("config", {
            "target": action["target"],
            "line_to_add": action["line_to_add"]
        })
        sent_command = f"[{action['target']}] -> {action['line_to_add']}"

    elif action["type"] == "system":
        if not action.get("command"):
            print("⚠️ [ERREUR] Commande système vide.")
            return
        execution_result = call_pgagent("system", {
            "command": action["command"],
            "arguments": action.get("arguments", [])
        })
        sent_command = f"{action['command']} {' '.join(action.get('arguments', []))}"

    print("\n✍️ Synthèse du rapport d'exécution...")
    final_prompt = f"""You are an expert DBA. You executed an automated action on the remote server.
Action Sent: {sent_command}
Server Result: {json.dumps(execution_result)}

Provide a concise, professional summary of the results returned by the server to the user. State clearly if the execution was a success or failure."""

    try:
        ollama_host = os.getenv("OLLAMA_HOST", "http://10.198.0.4:11434")
        client = ollama.Client(host=ollama_host)
        response = client.chat(model=ORCHESTRATOR_MODEL, messages=[{"role": "user", "content": final_prompt}])
        rapport_final = response['message']['content'].strip()
        print(f"\n🎯 [RAPPORT ACTION] :\n{rapport_final}\n")
        
        raw_payload_json = json.dumps(action, ensure_ascii=False)
        expert.save_action(
            user_query=user_question,
            action_type=action["type"],
            payload=raw_payload_json,
            description=rapport_final  
        )
    except Exception as e:
        print(f"❌ Erreur lors de la génération du rapport final ou de l'historisation : {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Tower of Control - Central AI Orchestrator for PostgreSQL 18")
    parser.add_argument("-v", "--verbose", action="store_true", help="Active les logs de debug")
    args = parser.parse_args()

    VERBOSE = args.verbose
    expert.VERBOSE = args.verbose

    print("\n" + "="*75)
    print("🗼 POSTGRESQL 18 AGENCY - CENTRAL ORCHESTRATOR (ALIGNED)")
    print("="*75 + "\n")
    
    while True:
        try:
            prompt_prefix = "agency (verbose) > " if VERBOSE else "agency > "
            user_input = input(prompt_prefix).strip()
            if not user_input: continue
            if user_input.lower() in ['q', 'quit', 'exit']: break
            
            if user_input.startswith(('/a ', '/action ')):
                clean_question = user_input.split(maxsplit=1)[1]
                execute_action_pipeline(clean_question)
                continue
            
            elif user_input.startswith('/'):
                parts = user_input.split()
                cmd = parts[0].lower()
                
                if cmd in ['/clear', '/c']:
                    expert.clear_history()
                    print("🧠 [SYSTEM] Session réinitialisée.\n")
                    
                elif cmd in ['/history', '/h']:
                    history = expert.get_recent_history(limit=5)
                    print("\n📜 --- SOUVENIRS DU MODE CONVERSATION ---")
                    if not history:
                        print("Aucun message textuel.")
                    else:
                        for msg in history:
                            prefix = "👤 [VOUS]" if msg['role'] == 'user' else "🤖 [EXPERT]"
                            print(f"{prefix} : {msg['content']}")

                    print("\n⚡ --- DERNIÈRES ACTIONS EXÉCUTÉES (history_actions) ---")
                    conn = None
                    try:
                        conn = expert.PG_POOL.getconn()
                        cur = conn.cursor()
                        # CORRECTION DU NOM DE COLONNE CRITICAL BUG: updated_at
                        cur.execute("SELECT action_type, user_query, updated_at FROM rag.history_actions ORDER BY id DESC LIMIT 5;")
                        actions = cur.fetchall()
                        cur.close()

                        if not actions:
                            print("Aucune action physique enregistrée.")
                        else:
                            for act in actions:
                                print(f"⏱️ [{act[2].strftime('%H:%M:%S')}] [{act[0].upper()}] -> Requête : {act[1]}")
                    except Exception as e:
                        print(f"Impossible de charger l'historique des actions : {e}")
                    finally:
                        if conn:
                            expert.PG_POOL.putconn(conn)
                    print("-----------------------------------\n")

                elif cmd in ['/delete', '/d']:
                    if len(parts) < 2:
                        print("❌ [ERREUR] Syntaxe : /d [ID]\n")
                    else:
                        target_id = parts[1]
                        if expert.delete_cache_entry(target_id):
                            print(f"✂️  [CACHE] L'entrée ID #{target_id} retirée.\n")
                        else:
                            print(f"⚠️ [CACHE] Aucun ID #{target_id}.\n")
                            
                elif cmd == '/clear-payload':
                    if os.path.exists(CACHE_ORCH_PATH):
                        os.remove(CACHE_ORCH_PATH)
                        print("🗑️  [CACHE ORCHESTRATOR] Cache des charges utiles vidé !\n")
                    else:
                        print("ℹ️  [CACHE ORCHESTRATOR] Déjà vide.\n")

                elif cmd == '/v':
                    VERBOSE = not VERBOSE
                    expert.VERBOSE = VERBOSE
                    print(f"🔬 [SYSTEM] Mode verbeux : {'ACTIVÉ 🟢' if VERBOSE else 'DÉSACTIVÉ ⚪'}\n")
                else:
                    print(f"❌ [ERREUR] Commande '{cmd}' inconnue.\n")
                continue
            
            else:
                print("\n📖 [MODE INFORMATION] Consultation de la base de connaissances...")
                reponse = expert.ask_rag(user_input)
                if reponse == "DIRECT_SYSTEM_ACTION":
                    print("\n🤖 [EXPERT PG18] :\n💡 Commande système requise. Utilisez `/a` pour exécuter.\n")
                else:
                    print(f"\n🤖 [EXPERT PG18] :\n{reponse}\n")
                
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"❌ Erreur générale : {e}")

    if expert.PG_POOL:
        expert.PG_POOL.closeall()
