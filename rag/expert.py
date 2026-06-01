import os
import logging
import psycopg2
import argparse
import sqlite3
import json
from datetime import datetime
from dotenv import load_dotenv
import ollama
from flashrank import Ranker, RerankRequest

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("flashrank").setLevel(logging.WARNING)

load_dotenv()

DB_NAME = os.getenv("DB_NAME", "rag_db")
DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASS")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "nomic-embed-text")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen2.5:7b-instruct")
RERANK_MODEL = os.getenv("RERANK_MODEL", "ms-marco-TinyBERT-L-2-v2")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SQLITE_DB_PATH = os.path.join(BASE_DIR, "rag", "rag_history.db")

VERBOSE = False
CURRENT_CONTEXT = ""

print(f"[INIT] ⚡ Chargement du Reranker CPU ({RERANK_MODEL})...")
RANKER = Ranker(model_name=RERANK_MODEL, cache_dir="/tmp/flashrank")

# ---------------------------------------------------------------------------
# STRUCTURES DE SESSIONS ET CACHE
# ---------------------------------------------------------------------------
def init_sqlite_db():
    conn = sqlite3.connect(SQLITE_DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, role TEXT, content TEXT
        )
    """)
    conn.commit()
    conn.close()

def save_message(role, content):
    conn = sqlite3.connect(SQLITE_DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO chat_history (timestamp, role, content) VALUES (?, ?, ?)", (datetime.now().isoformat(), role, content))
    conn.commit()
    conn.close()

def get_recent_history(limit=4):
    conn = sqlite3.connect(SQLITE_DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT role, content FROM chat_history ORDER BY id DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [{"role": r[0], "content": r[1]} for r in reversed(rows)]

def clear_history():
    global CURRENT_CONTEXT
    conn = sqlite3.connect(SQLITE_DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM chat_history")
    conn.commit()
    conn.close()
    CURRENT_CONTEXT = ""

def check_semantic_cache(query_embedding, distance_threshold=0.12):
    conn = psycopg2.connect(dbname=DB_NAME, user=DB_USER, password=DB_PASS, host=DB_HOST, port=DB_PORT)
    cur = conn.cursor()
    cache_query = """
        SELECT id, question, response, (embedding <=> %s::vector) as distance 
        FROM rag.semantic_cache 
        WHERE (embedding <=> %s::vector) < %s
        ORDER BY distance ASC LIMIT 1;
    """
    cur.execute(cache_query, (query_embedding, query_embedding, distance_threshold))
    result = cur.fetchone()
    cur.close()
    conn.close()
    return result

def save_to_semantic_cache(question, response_text, query_embedding):
    try:
        conn = psycopg2.connect(dbname=DB_NAME, user=DB_USER, password=DB_PASS, host=DB_HOST, port=DB_PORT)
        cur = conn.cursor()
        cur.execute("INSERT INTO rag.semantic_cache (question, response, embedding) VALUES (%s, %s, %s::vector);", (question, response_text, query_embedding))
        conn.commit()
        cur.close()
        conn.close()
    except Exception:
        pass

def delete_cache_entry(entry_id):
    """Supprime une entrée spécifique du cache sémantique Postgres"""
    try:
        conn = psycopg2.connect(dbname=DB_NAME, user=DB_USER, password=DB_PASS, host=DB_HOST, port=DB_PORT)
        cur = conn.cursor()
        cur.execute("DELETE FROM rag.semantic_cache WHERE id = %s;", (entry_id,))
        rows_deleted = cur.rowcount
        conn.commit()
        cur.close()
        conn.close()
        return rows_deleted > 0
    except Exception as e:
        print(f"❌ [ERREUR DB] Impossible de supprimer l'entrée : {e}")
        return False

# ---------------------------------------------------------------------------
# INTERROGATION DU CATALOGUE SYSTEME (ANTI-HALLUCINATION)
# ---------------------------------------------------------------------------
def get_table_schema(table_name):
    """Récupère la structure réelle de l'objet depuis le catalogue pour l'injecter au LLM"""
    try:
        conn = psycopg2.connect(dbname="postgres", user="postgres", password=DB_PASS, host=DB_HOST, port=DB_PORT)
        cur = conn.cursor()
        
        query = """
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = %s
            ORDER BY ordinal_position;
        """
        cur.execute(query, (table_name,))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        
        if rows:
            schema_str = f"\n📊 [REAL SCHEMA FROM CATALOG] Structure actuelle de la vue/table '{table_name}' dans PostgreSQL 18 :\n"
            for col, dtype in rows:
                schema_str += f" - {col} ({dtype})\n"
            schema_str += "CRITICAL RULE: You must ONLY use these columns if you write an SQL query regarding this table. Do NOT invent columns.\n"
            return schema_str
    except Exception as e:
        if VERBOSE:
            print(f"[DEBUG] Impossible de lire le catalogue pour {table_name}: {e}")
        return ""
    return ""

# ---------------------------------------------------------------------------
# COUCHE INTERPRÉTRATION DE LA QUESTION (QUERY REWRITER)
# ---------------------------------------------------------------------------
def analyze_and_rewrite_query(user_question):
    if VERBOSE:
        print("[INTENT] 🧠 Interprétation de la question par le LLM...")
        
    prompt = f"""You are a DBA assistant. Analyze this question and extract technical keywords (like system views, function names, or parameters) and build an optimized vector search query.
    Return a JSON object with 'keywords' (list of strings) and 'search_query' (string).
    
    CRITICAL RULE: Do NOT write SQL queries, SELECT commands, or code in the 'search_query' field. It must be a plain descriptive English search string.
    
    Question: {user_question}"""
    
    try:
        response = ollama.chat(
            model=LLM_MODEL, 
            messages=[{"role": "user", "content": prompt}], 
            options={"temperature": 0.0},
            format="json" 
        )
        raw_content = response['message']['content'].strip()
        
        if raw_content.startswith("```"):
            raw_content = raw_content.split("```")[1]
            if raw_content.startswith("json"):
                raw_content = raw_content[4:]
        
        analysis = json.loads(raw_content.strip())
        return analysis.get("keywords", []), analysis.get("search_query", user_question)
    except Exception as e:
        if VERBOSE:
            print(f"[INTENT] ⚠️ Échec de l'analyse, repli sur la question brute: {e}")
        return [], user_question

# ---------------------------------------------------------------------------
# PIPELINE RAG AVEC APPRENTISSAGE D'INTENTION
# ---------------------------------------------------------------------------
def fetch_new_context(query_text, top_k_postgres=15, final_limit=3):
    keywords, optimized_search = analyze_and_rewrite_query(query_text)
    
    if VERBOSE:
        print(f"[INTENT] 🎯 Mots-clés extraits : {keywords}")
        print(f"[INTENT] 🔍 Requête de recherche optimisée : '{optimized_search}'")

    response = ollama.embeddings(model=EMBEDDING_MODEL, prompt=optimized_search)
    optimized_embedding = response['embedding']

    conn = psycopg2.connect(dbname=DB_NAME, user=DB_USER, password=DB_PASS, host=DB_HOST, port=DB_PORT)
    cur = conn.cursor()
    
    if keywords:
        boost_conditions = " + ".join([f"(CASE WHEN content ILIKE %s THEN 0.2 ELSE 0 END)" for _ in keywords])
        search_query = f"""
            SELECT source, title, content, 
                   ((embedding <=> %s::vector) - ({boost_conditions})) as distance 
            FROM rag.documents 
            ORDER BY distance ASC 
            LIMIT %s;
        """
        query_params = [optimized_embedding] + [f"%{k}%" for k in keywords] + [top_k_postgres]
        cur.execute(search_query, query_params)
    else:
        search_query = "SELECT source, title, content, (embedding <=> %s::vector) as distance FROM rag.documents ORDER BY distance ASC LIMIT %s;"
        cur.execute(search_query, (optimized_embedding, top_k_postgres))
        
    postgres_results = cur.fetchall()
    cur.close()
    conn.close()
    
    passages = [{"id": idx, "text": r[2], "meta": {"source": r[0], "title": r[1]}} for idx, r in enumerate(postgres_results)]
    reranked_results = RANKER.rerank(RerankRequest(query=query_text, passages=passages))

    if VERBOSE:
        print(f"\n📊 TABLEAU COMPARATIF CPU (REWRITING APPLIQUÉ) :")
        print(f"{'FICHIER HTML':<35} | SCORE RERANK")
        print("-" * 55)
    
    context_chunks = []
    seen_sources = set()

    for item in reranked_results:
        source_file = item['meta']['source']
        if VERBOSE:
            print(f"{source_file:<35} | {item['score']:.4f}")
            
        if source_file not in seen_sources and len(context_chunks) < final_limit:
            context_chunks.append(item["text"])
            seen_sources.add(source_file)
            
    for item in reranked_results:
        if len(context_chunks) >= final_limit: break
        if item["text"] not in context_chunks:
            context_chunks.append(item["text"])

    return optimized_embedding, "\n\n--- EXTRAIT DE DOCUMENTATION ---\n\n".join(context_chunks)

def load_system_prompt(prompt_filename, context_data):
    prompt_path = os.path.join(BASE_DIR, "rag", prompt_filename)
    with open(prompt_path, "r", encoding="utf-8") as f:
        return f.read().format(context=context_data)

def ask_rag(question):
    global CURRENT_CONTEXT
    
    # 1. Calcul de l'embedding pour le cache sémantique
    response = ollama.embeddings(model=EMBEDDING_MODEL, prompt=question)
    raw_embedding = response['embedding']

    # 2. VÉRIFICATION DU CACHE SÉMANTIQUE PERMANENT
    cached_hit = check_semantic_cache(raw_embedding, distance_threshold=0.12)
    if cached_hit:
        cache_id, cached_question, cached_response, distance = cached_hit
        print(f"⚡ [CACHE HIT] Correspondance trouvée à {(1 - distance)*100:.1f}% avec : '{cached_question}'")
        save_message("user", question)
        save_message("assistant", cached_response)
        return cached_response + f"\n\n*(Généré depuis le Cache Permanent Postgres - [Cache ID: {cache_id}])*"

    # 3. CACHE MISS : Recherche de contexte documentaire RAG
    if VERBOSE:
        print("🔄 [RAG] Analyse et recherche vectorielle lancées...")
    
    optimized_embed, CURRENT_CONTEXT = fetch_new_context(question, top_k_postgres=15, final_limit=3)

    # 4. ENRICHISSEMENT VIA CATALOGUE SYSTÈME (Vérification anti-hallucination des tables)
    schema_enrichment = ""
    target_tables = ["pg_stat_replication", "pg_stat_activity", "pg_stat_progress_vacuum", "pg_stat_database"]
    for table in target_tables:
        if table in question.lower():
            if VERBOSE:
                print(f"🔍 [CATALOG] Détection de '{table}'. Lecture de la structure réelle...")
            schema_enrichment = get_table_schema(table)
            break

    # Combinaison de la documentation HTML et de la vraie structure des tables
    extended_context = CURRENT_CONTEXT + "\n" + schema_enrichment
    prompt_system = load_system_prompt("prompt_rag", extended_context)
    
    save_message("user", question)
    history = get_recent_history(limit=4)
    
    messages = [{"role": "system", "content": prompt_system}]
    messages.extend(history)
    
    if VERBOSE:
        print(f"[DEBUG] 🤖 Envoi au LLM {LLM_MODEL}...")
        
    response = ollama.chat(model=LLM_MODEL, messages=messages)
    reply = response['message']['content'].strip()
    
    save_message("assistant", reply)
    save_to_semantic_cache(question, reply, raw_embedding)
    
    return reply

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Expert PostgreSQL 18 - Console DBA avec Cache Sémantique")
    parser.add_argument("-v", "--verbose", action="store_true", help="Active les logs de debug")
    args = parser.parse_args()

    VERBOSE = args.verbose
    init_sqlite_db()
    clear_history()

    print("\n" + "="*75)
    print("🐘 POSTGRESQL 18 INTERACTIVE DBA CONSOLE - EXPERT V3.2")
    print(f"    Mode verbeux : {'ACTIVÉ 🟢' if VERBOSE else 'DÉSACTIVÉ ⚪'}")
    print("    Moteurs : Intent Query Rewriter + Catalogue Enricher + Cache Sémantique 🔬")
    print("    Commandes :  /c (clear)  |  /h (history)  |  /d [id] (delete cache item)  |  q (quitter)")
    print("="*75 + "\n")

    while True:
        try:
            ma_question = input("dba > ").strip()
            if not ma_question: continue
            if ma_question.lower() in ['exit', 'quit', 'q']: break
            
            # --- INTERCEPTEUR DE COMMANDES SYSTÈME ---
            if ma_question.startswith('/'):
                parts = ma_question.split()
                cmd = parts[0].lower()
                
                if cmd in ['/clear', '/c']:
                    clear_history()
                    print("🧠 [SYSTEM] Session réinitialisée. (Note : Le cache permanent Postgres reste actif !)\n")
                elif cmd in ['/history', '/h']:
                    history = get_recent_history(limit=10)
                    if not history:
                        print("📜 [HISTORY] Aucun message dans la session actuelle.\n")
                    else:
                        print("\n📜 --- HISTORIQUE DE LA SESSION ---")
                        for msg in history:
                            prefix = "👤 [VOUS]" if msg['role'] == 'user' else "🤖 [EXPERT]"
                            print(f"{prefix} : {msg['content']}")
                        print("-----------------------------------\n")
                elif cmd == '/v':
                    VERBOSE = not VERBOSE
                    print(f"⚙️ [SYSTEM] Mode verbeux global : {'ACTIVÉ 🟢' if VERBOSE else 'DÉSACTIVÉ ⚪'}\n")
                elif cmd in ['/delete', '/d']:
                    if len(parts) < 2:
                        print("❌ [ERREUR] Syntaxe incorrecte. Utilisation : /d [ID_DU_CACHE] (ex: /d 14)\n")
                    else:
                        target_id = parts[1]
                        if delete_cache_entry(target_id):
                            print(f"✂️  [CACHE] L'entrée ID #{target_id} a été retirée définitivement de Postgres.\n")
                        else:
                            print(f"⚠️ [CACHE] Aucune entrée trouvée avec l'ID #{target_id}.\n")
                elif cmd in ['/help', '/?']:
                    print("\n💡 --- COMMANDES DISPONIBLES ---")
                    print("   /c, /clear   : Réinitialiser l'historique de la session")
                    print("   /h, /history : Afficher les 10 derniers messages")
                    print("   /d [id]      : Supprimer une ligne spécifique du cache permanent Postgres")
                    print("   /v           : Activer/Désactiver dynamiquement les logs de debug")
                    print("   q, quit      : Quitter l'application\n")
                else:
                    print(f"❌ [ERREUR] Commande système '{ma_question}' inconnue. Tapez /help pour voir la liste.\n")
                continue
            
            reponse = ask_rag(ma_question)
            print(f"\n🤖 [EXPERT PG18] :\n{reponse}\n")
            
        except KeyboardInterrupt: break
        except Exception as e: print(f"\n❌ Erreur : {e}\n")
