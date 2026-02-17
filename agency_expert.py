import os
import sys
import time
import psycopg2
from dotenv import load_dotenv
from sentence_transformers import CrossEncoder

# Path pour llm.client
sys.path.append(os.getcwd())
from llm.client import OllamaClient

load_dotenv()

class DBAgencyExpert:
    def __init__(self):
        print("⚙️  Initialisation de l'expert (CPU Reranker + Fast LLM)...")
        self.ai = OllamaClient()
        self.fast_model = os.getenv("FAST_MODEL")
        
        # Chargement du reranker sur CPU
        self.reranker = CrossEncoder('BAAI/bge-reranker-base', device='cpu')
        
        self.db_params = {
            "dbname": os.getenv("DB_NAME"),
            "user": os.getenv("DB_USER"),
            "password": os.getenv("DB_PASS"),
            "host": os.getenv("DB_HOST"),
            "port": os.getenv("DB_PORT")
        }

    def ask(self, query):
        start_time = time.time()

        # 1. RETRIEVAL (Vector Search)
        print(f"\n🔍 Recherche vectorielle pour : {query}")
        try:
            conn = psycopg2.connect(**self.db_params)
            cur = conn.cursor()
            
            query_emb = self.ai.get_embedding(query)
            cur.execute("""
                SELECT content, metadata->>'title', metadata->>'section'
                FROM documents
                ORDER BY embedding <=> %s::vector
                LIMIT 20;
            """, (query_emb,))
            candidates = cur.fetchall()
            cur.close()
            conn.close()
        except Exception as e:
            return f"❌ Erreur DB: {e}"
        
        t_retrieval = time.time() - start_time

        if not candidates:
            return "Désolé, la recherche vectorielle n'a retourné aucun candidat."

        # 2. RERANKING (BGE Cross-Encoder)
        print(f"⚖️  Reranking de {len(candidates)} chunks...")
        pairs = [[query, c[0]] for c in candidates]
        scores = self.reranker.predict(pairs)
        
        # Fusion et tri par score décroissant
        scored_docs = sorted(zip(scores, candidates), key=lambda x: x[0], reverse=True)
        
        # --- DEBUG : Affichage des Top Scores ---
        print("📊 Top 5 scores BGE détectés :")
        for i in range(min(5, len(scored_docs))):
            s, c = scored_docs[i]
            print(f"   [{i+1}] Score: {s:.4f} | {c[1][:40]} > {c[2]}")

        # Seuil abaissé à 0.3 pour capturer plus de contexte technique
        threshold = 0.3
        top_chunks = [doc for score, doc in scored_docs if score > threshold][:3]
        
        t_rerank = time.time() - (start_time + t_retrieval)

        # 3. GENERATION (LLM)
        if not top_chunks:
            # On affiche quand même le meilleur score pour comprendre le refus
            best_score = scored_docs[0][0]
            return f"Désolé, je n'ai pas trouvé assez d'informations pertinentes (Meilleur score BGE: {best_score:.4f}, Seuil: {threshold})."

        context = "\n---\n".join([f"DOC: {c[1]} > {c[2]}\n{c[0]}" for c in top_chunks])
        
        print(f"🧠 Génération avec {self.fast_model}...")
        response = self.ai.chat(query, context=context, model=self.fast_model)
        
        t_total = time.time() - start_time

        # Statistiques de performance
        print(f"\n⏱️  Perfs : Retrieval {t_retrieval:.2f}s | Rerank {t_rerank:.2f}s | Total {t_total:.2f}s")
        return response

if __name__ == "__main__":
    expert = DBAgencyExpert()
    
    if len(sys.argv) > 1:
        question = " ".join(sys.argv[1:])
        answer = expert.ask(question)
        print("\n" + "="*60)
        print("🤖 RÉPONSE DE L'AGENT :")
        print(answer)
        print("="*60)
    else:
        print("Usage: python3 agency_expert.py 'votre question'")
