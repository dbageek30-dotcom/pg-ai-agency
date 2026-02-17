import os
import glob
import psycopg2
import sys
from json import dumps
from bs4 import BeautifulSoup

# Fix pour l'import des modules locaux
sys.path.append(os.getcwd())
from llm.client import OllamaClient

def run_ingestion():
    ai = OllamaClient()
    
    # --- CONFIGURATION DU CHEMIN RÉEL ---
    base_dir = "/var/lib/postgresql/pg-ai-agency/documentation/postgresql/18/admin"
    
    if not os.path.exists(base_dir):
        print(f"❌ ERREUR : Le dossier n'existe pas : {base_dir}")
        return

    files = glob.glob(os.path.join(base_dir, "*.html"))
    if not files:
        print(f"❌ ERREUR : Aucun fichier .html trouvé dans {base_dir}")
        return

    print(f"🔍 Scan terminé : {len(files)} fichiers détectés dans l'Admin Guide.")

    try:
        conn = psycopg2.connect(dbname="rag", user="postgres", host="localhost")
        cur = conn.cursor()
        
        print("🧹 Nettoyage de la table documents...")
        cur.execute("TRUNCATE TABLE documents RESTART IDENTITY;")
        
        total_chunks = 0
        
        for f_path in files:
            fname = os.path.basename(f_path)
            with open(f_path, 'r', encoding='utf-8') as f:
                soup = BeautifulSoup(f, 'html.parser')
                
                # Récupération du titre de la page
                title_tag = soup.find(['h1', 'h2', 'h3'], class_='title')
                page_title = title_tag.get_text(strip=True) if title_tag else "N/A"
                
                # Récupération du chapitre parent dans le header navigation
                parent_tag = soup.find('th', width="60%")
                parent_chapter = parent_tag.get_text(strip=True) if parent_tag else "Admin Guide"

                chunks_count_before = total_chunks

                # 1. Extraction VariableList (Termes techniques)
                for vlist in soup.find_all('div', class_='variablelist'):
                    items = vlist.find_all(['dt', 'dd'])
                    for i in range(0, len(items) - 1, 2):
                        term = items[i].get_text(strip=True)
                        definition = items[i+1].get_text(separator=' ', strip=True)
                        
                        content = f"Context: {parent_chapter} > {page_title}\nTerm: {term}\nDefinition: {definition}"
                        meta = {
                            "source": fname, 
                            "title": page_title, 
                            "section": term, 
                            "type": "definition"
                        }
                        
                        emb = ai.get_embedding(content)
                        cur.execute(
                            "INSERT INTO documents (source, content, metadata, embedding) VALUES (%s, %s, %s, %s)",
                            (f_path, content, dumps(meta), emb)
                        )
                        total_chunks += 1

                # 2. Extraction Blocs de Code et Paragraphes
                for p in soup.find_all(['p', 'pre']):
                    # On évite de dupliquer ce qui est déjà dans une liste
                    if not p.find_parent('div', class_='variablelist'):
                        text = p.get_text(separator=' ', strip=True)
                        if len(text) > 80:
                            content = f"Context: {parent_chapter} > {page_title}\nContent: {text}"
                            meta = {
                                "source": fname, 
                                "title": page_title, 
                                "section": "General", 
                                "type": "content"
                            }
                            emb = ai.get_embedding(content)
                            cur.execute(
                                "INSERT INTO documents (source, content, metadata, embedding) VALUES (%s, %s, %s, %s)",
                                (f_path, content, dumps(meta), emb)
                            )
                            total_chunks += 1

                print(f"✅ {fname.ljust(30)} | +{total_chunks - chunks_count_before} chunks")

        conn.commit()
        print(f"\n🚀 Ingestion réussie ! Total : {total_chunks} chunks insérés.")
        
        # --- PETITE VALIDATION SQL ---
        cur.execute("SELECT metadata->>'section', left(content, 60) FROM documents WHERE metadata->>'type' = 'definition' LIMIT 3;")
        check = cur.fetchall()
        print("\n📊 Échantillon de validation (Définitions) :")
        for row in check:
            print(f"   - [{row[0]}] : {row[1]}...")

    except Exception as e:
        print(f"💥 Erreur : {e}")
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    run_ingestion()
