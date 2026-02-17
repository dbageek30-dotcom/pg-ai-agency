import os
import sys
import psycopg2
from dotenv import load_dotenv
from sentence_transformers import CrossEncoder

# Path pour llm.client
sys.path.append(os.getcwd())
from llm.client import OllamaClient

load_dotenv()

def search_bge(query):
    ai = OllamaClient()
    
    # 1. RETRIEVAL : Vectoriel large (Top 20)
    conn = psycopg2.connect(
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASS"),
        host=os.getenv("DB_HOST")
    )
    cur = conn.cursor()
    
    query_emb = ai.get_embedding(query)
    cur.execute("""
        SELECT content, metadata->>'title', metadata->>'section'
        FROM documents
        ORDER BY embedding <=> %s::vector
        LIMIT 20;
    """, (query_emb,))
    candidates = cur.fetchall()
    cur.close()
    conn.close()

    if not candidates:
        print("Aucun document trouvé.")
        return

    # 2. RERANKING : Chargement du modèle BGE (Python "Lourd")
    # Modèle recommandé : BAAI/bge-reranker-base (ou large pour encore plus de précision)
    model = CrossEncoder('BAAI/bge-reranker-base', device='cpu') # Utilise 'cpu' si pas de GPU
    
    # On prépare les paires (Query, Doc) pour le scoring
    pairs = [[query, c[0]] for c in candidates]
    scores = model.predict(pairs)

    # 3. TRI : On combine scores et candidats
    scored_candidates = sorted(zip(scores, candidates), key=lambda x: x[0], reverse=True)

    print(f"\n🔎 Résultats Rerankés pour : '{query}'")
    print("-" * 80)
    
    # On affiche le Top 3 final
    for score, doc in scored_candidates[:3]:
        content, title, section = doc
        print(f"[Score BGE: {score:.4f}] | {title} > {section}")
        print(f"   Preview: {content[:150]}...")
        print("-" * 40)

if __name__ == "__main__":
    if len(sys.argv) > 1:
        search_bge(" ".join(sys.argv[1:]))
    else:
        search_bge("how to create a role with login permission")
