import os
import logging
import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
import argparse
import json
import re
from datetime import datetime
from dotenv import load_dotenv
import ollama
from flashrank import Ranker, RerankRequest

# Désactivation des logs verbeux des librairies tierces
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("flashrank").setLevel(logging.WARNING)

# Chargement des variables d'environnement
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

VERBOSE = False
CURRENT_CONTEXT = ""

print(f"[INIT] ⚡ Chargement du Reranker CPU ({RERANK_MODEL})...")
RANKER = Ranker(model_name=RERANK_MODEL, cache_dir="/tmp/flashrank")

# ---------------------------------------------------------------------------
# INITIALISATION DU POOL DE CONNEXIONS POSTGRESQL
# ---------------------------------------------------------------------------
try:
    print("[INIT] 🐘 Initialisation du pool de connexions PostgreSQL...")
    PG_POOL = psycopg2.pool.SimpleConnectionPool(
        minconn=1,
        maxconn=10,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASS,
        host=DB_HOST,
        port=DB_PORT
    )
except Exception as e:
    print(f"❌ [ERREUR CRITIQUE] Impossible d'initialiser le pool de connexions : {e}")
    exit(1)

# ---------------------------------------------------------------------------
# INITIALISATION DES TABLES POSTGRESQL (MIGRATION DE SQLITE COMPLÈTE)
# ---------------------------------------------------------------------------
def init_postgres_tables():
    """Initialise le schéma et les tables d'historique au sein de PostgreSQL"""
    conn = None
    try:
        conn = PG_POOL.getconn()
        cur = conn.cursor()
        
        # 1. Table d'historique de session éphémère (Remplace SQLite)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS rag.chat_history (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                role VARCHAR(20) NOT NULL,
                content TEXT NOT NULL
            );
        """)
        
        # 2. Table de cache sémantique
        cur.execute("""
            CREATE TABLE IF NOT EXISTS rag.semantic_cache (
                id SERIAL PRIMARY KEY,
                question TEXT NOT NULL,
                response TEXT NOT NULL,
                embedding vector(768),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        conn.commit()
        cur.close()
    except Exception as e:
        print(f"❌ [ERREUR INITIALISATION TABLES] : {e}")
    finally:
        if conn:
            PG_POOL.putconn(conn)

# Initialisation automatique au chargement de l'expert
init_postgres_tables()

# ---------------------------------------------------------------------------
# HISTORIQUE CONVERSATIONNEL DE SESSION
# ---------------------------------------------------------------------------
def save_message(role, content):
    """Sauvegarde un message de discussion (user/assistant) dans PostgreSQL"""
    conn = None
    try:
        conn = PG_POOL.getconn()
        cur = conn.cursor()
        cur.execute("INSERT INTO rag.chat_history (role, content) VALUES (%s, %s);", (role, content))
        conn.commit()
        cur.close()
    except Exception as e:
        if VERBOSE: 
            print(f"⚠️ Erreur lors de la sauvegarde du message : {e}")
    finally:
        if conn: 
            PG_POOL.putconn(conn)

def get_recent_history(limit=4):
    """Extrait les derniers messages de la session active pour maintenir le contexte"""
    conn = None
    rows = []
    try:
        conn = PG_POOL.getconn()
        cur = conn.cursor()
        cur.execute("SELECT role, content FROM rag.chat_history ORDER BY id DESC LIMIT %s;", (limit,))
        rows = cur.fetchall()
        cur.close()
    except Exception as e:
        if VERBOSE: 
            print(f"⚠️ Erreur lors de la récupération de l'historique : {e}")
    finally:
        if conn: 
            PG_POOL.putconn(conn)
    return [{"role": r[0], "content": r[1]} for r in reversed(rows)]

def clear_history():
    """Efface l'historique de la session conversationnelle en cours"""
    global CURRENT_CONTEXT
    conn = None
    try:
        conn = PG_POOL.getconn()
        cur = conn.cursor()
        cur.execute("DELETE FROM rag.chat_history;")
        conn.commit()
        cur.close()
        CURRENT_CONTEXT = ""
    except Exception as e:
        if VERBOSE: 
            print(f"⚠️ Erreur lors de la réinitialisation de l'historique : {e}")
    finally:
        if conn: 
            PG_POOL.putconn(conn)

# ---------------------------------------------------------------------------
# GESTION DU CACHE SÉMANTIQUES POSTGRESQL
# ---------------------------------------------------------------------------
def check_semantic_cache(query_embedding, distance_threshold=0.12):
    conn = None
    try:
        conn = PG_POOL.getconn()
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
        return result
    except Exception as e:
        if VERBOSE:
            print(f"[DEBUG] Erreur lors de la lecture du cache sémantique : {e}")
        return None
    finally:
        if conn:
            PG_POOL.putconn(conn)

def save_to_semantic_cache(question, response_text, query_embedding):
    conn = None
    try:
        conn = PG_POOL.getconn()
        cur = conn.cursor()
        cur.execute("INSERT INTO rag.semantic_cache (question, response, embedding) VALUES (%s, %s, %s::vector);", (question, response_text, query_embedding))
        conn.commit()
        cur.close()
    except Exception as e:
        if VERBOSE:
            print(f"[DEBUG] Erreur lors de l'écriture dans le cache sémantique : {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            PG_POOL.putconn(conn)

def delete_cache_entry(entry_id):
    conn = None
    try:
        conn = PG_POOL.getconn()
        cur = conn.cursor()
        cur.execute("DELETE FROM rag.semantic_cache WHERE id = %s;", (entry_id,))
        rows_deleted = cur.rowcount
        conn.commit()
        cur.close()
        return rows_deleted > 0
    except Exception as e:
        print(f"❌ [ERREUR DB] Impossible de supprimer l'entrée : {e}")
        if conn:
            conn.rollback()
        return False
    finally:
        if conn:
            PG_POOL.putconn(conn)

# ---------------------------------------------------------------------------
# INTERROGATION DU CATALOGUE SYSTEME (ANTI-HALLUCINATION)
# ---------------------------------------------------------------------------
def get_table_schema(table_name):
    conn = None
    try:
        conn = PG_POOL.getconn()
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
    finally:
        if conn:
            PG_POOL.putconn(conn)
    return ""


# ---------------------------------------------------------------------------
# COUCHE INTERPRÉTRATION DE LA QUESTION (QUERY REWRITER & INTENT DETECTOR)
# ---------------------------------------------------------------------------
def analyze_and_rewrite_query(user_question):
    if VERBOSE:
        print("[INTENT] 🧠 Interprétation de la question par le LLM...")
    prompt = f"""You are a DBA assistant. Analyze this question to determine if it requires a standard documentation lookup or if it is a direct infrastructure/system action request (like checking disk space, creating directories, listing files, checking process status).
    
    Return a JSON object with:
    - 'intent': string ("documentation" or "system_action")
    - 'keywords': list of technical keywords (strings)
    - 'search_query': string (plain descriptive English search string)
    
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
            lines = raw_content.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines[-1].startswith("```"):
                lines = lines[:-1]
            raw_content = "\n".join(lines).strip()
        analysis = json.loads(raw_content)
        return analysis.get("keywords", []), analysis.get("search_query", user_question), analysis.get("intent", "documentation")
    except Exception as e:
        if VERBOSE:
            print(f"[INTENT] ⚠️ Échec de l'analyse, repli sur le mode par défaut : {e}")
        return [], user_question, "documentation"

# ---------------------------------------------------------------------------
# PIPELINE RAG AVEC APPRENTISSAGE D'INTENTION (HYBRID SEARCH REWRITE)
# ---------------------------------------------------------------------------
def fetch_new_context(query_text, optimized_search, keywords, top_k_postgres=15, final_limit=3):
    if VERBOSE:
        print(f"[INTENT] 🎯 Mots-clés extraits : {keywords}")
        print(f"[INTENT] 🔍 Requête de recherche optimisée : '{optimized_search}'")

    response = ollama.embeddings(model=EMBEDDING_MODEL, prompt=optimized_search)
    optimized_embedding = response['embedding']

    conn = None
    postgres_results = []
    try:
        conn = PG_POOL.getconn()
        cur = conn.cursor()
        
        search_query = """
            SELECT d.source, h.title, h.content, h.final_score 
            FROM rag.hybrid_search(%s, %s::vector, %s) h
            JOIN rag.documents d ON d.id = h.id;
        """
        cur.execute(search_query, (query_text, optimized_embedding, top_k_postgres))
            
        postgres_results = cur.fetchall()
        cur.close()
    except Exception as e:
        print(f"❌ [ERREUR RAG] Erreur lors de la recherche hybride avec jointure : {e}")
    finally:
        if conn:
            PG_POOL.putconn(conn)
        
    passages = [{"id": idx, "text": r[2], "meta": {"source": r[0] if r[0] else "unknown", "title": r[1]}} for idx, r in enumerate(postgres_results)]
    
    if not passages:
        return optimized_embedding, ""
        
    reranked_results = RANKER.rerank(RerankRequest(query=query_text, passages=passages))

    if VERBOSE:
        print(f"\n📊 TABLEAU COMPARATIF CPU (HYBRID SEARCH & RERANK APPLIQUÉS) :")
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
    prompt_path = os.path.join(BASE_DIR, "agency", prompt_filename)
    with open(prompt_path, "r", encoding="utf-8") as f:
        return f.read().format(context=context_data)

def ask_rag(question):
    global CURRENT_CONTEXT
    
    # Extraction de l'intention en amont pour le court-circuit
    keywords, optimized_search, intent = analyze_and_rewrite_query(question)
    
    # COURT-CIRCUIT APPLIQUÉ SUR LES COMMANDES INFRASTRUCTURE/SYSTÈME ⚡
    if intent == "system_action":
        if VERBOSE:
            print("⚡ [INTENT] Détection d'une action système factuelle. Court-circuit complet du RAG engagé.")
        return "DIRECT_SYSTEM_ACTION"

    response = ollama.embeddings(model=EMBEDDING_MODEL, prompt=question)
    raw_embedding = response['embedding']

    cached_hit = check_semantic_cache(raw_embedding, distance_threshold=0.12)
    if cached_hit:
        cache_id, cached_question, cached_response, distance = cached_hit
        print(f"⚡ [CACHE HIT] Correspondance trouvée à {(1 - distance)*100:.1f}% avec : '{cached_question}'")
        save_message("user", question)
        save_message("assistant", cached_response)
        return cached_response + f"\n\n*(Généré depuis le Cache Permanent Postgres - [Cache ID: {cache_id}])*"

    if VERBOSE:
        print("🔄 [RAG] Analyse et recherche vectorielle lancées...")
    
    optimized_embed, CURRENT_CONTEXT = fetch_new_context(question, optimized_search, keywords, top_k_postgres=15, final_limit=3)

    # ---------------------------------------------------------------------------
    # ENRICHISSEMENT DYNAMIQUE DU CATALOGUE
    # ---------------------------------------------------------------------------
    schema_enrichment = ""
    detected_system_objects = re.findall(r'\bpg_[a-z0-9_]+\b', question.lower())

    for table in detected_system_objects:
        if VERBOSE:
            print(f"🔍 [CATALOG] Détection de '{table}'. Lecture de la structure réelle...")
        schema_info = get_table_schema(table)
        if schema_info:
            schema_enrichment += schema_info + "\n"

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

# ---------------------------------------------------------------------------
# SCRIPT ENTRYPOINT (CONSOLE DIRECTE)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Expert PostgreSQL 18 - Console DBA avec Cache Sémantique")
    parser.add_argument("-v", "--verbose", action="store_true", help="Active les logs de debug")
    args = parser.parse_args()

    VERBOSE = args.verbose
    clear_history()

    print("\n" + "="*75)
    print("🐘 POSTGRESQL 18 INTERACTIVE DBA CONSOLE - EXPERT V3.3")
    print(f"    Mode verbeux : {'ACTIVÉ 🟢' if VERBOSE else 'DÉSACTIVÉ ⚪'}")
    print("    Moteurs : Intent Query Rewriter + Catalogue Enricher + Cache Sémantique 🔬")
    print("    Commandes :  /c (clear)  |  /h (history)  |  /d [id] (delete cache item)  |  q (quitter)")
    print("="*75 + "\n")

    while True:
        try:
            ma_question = input("dba > ").strip()
            if not ma_question: continue
            if ma_question.lower() in ['exit', 'quit', 'q']: break
            
            if ma_question.startswith('/'):
                parts = ma_question.split()
                cmd = parts[0].lower()
                
                if cmd in ['/clear', '/c']:
                    clear_history()
                    print("🧠 [SYSTEM] Session réinitialisée. (Le cache permanent Postgres reste actif !)\n")
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
            
            # Fallback local esthétique si la console autonome rencontre le token de court-circuit
            if reponse == "DIRECT_SYSTEM_ACTION":
                print("\n🤖 [EXPERT PG18] :")
                print("💡 *[Note Console]* Cette question concerne une commande système directe.")
                print("En mode agence autonome, l'orchestrateur traitera directement cette demande avec la VM.")
            else:
                print(f"\n🤖 [EXPERT PG18] :\n{reponse}\n")
            
        except KeyboardInterrupt: break
        except Exception as e: print(f"\n❌ Erreur : {e}\n")
        
    if PG_POOL:
        if VERBOSE:
            print("[SHUTDOWN] Fermeture du pool de connexions PostgreSQL...")
        PG_POOL.closeall()
