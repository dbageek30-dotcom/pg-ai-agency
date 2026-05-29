import os
import glob
import psycopg2
import hashlib
from json import dumps
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import ollama

load_dotenv()

SOURCE_DIR = "/home/cs2081716/pg-ai-agency/rag/documentations/postgresql/18"
EMBEDDING_MODEL = "nomic-embed-text"

def get_chapter_id(fname):
    if fname.startswith(('sql-', 'queries-', 'syntax-')): return 5
    if fname.startswith('datatype-'): return 8
    if fname.startswith(('functions-', 'typeconv-')): return 9
    if fname.startswith(('indexes-', 'btree', 'gin', 'gist', 'spgist', 'brin', 'hash-index', 'indexam')): return 11
    if fname.startswith('textsearch-'): return 12
    if fname.startswith('app-'): return 15
    if fname.startswith(('install-', 'installation')): return 16
    if fname.startswith(('server-setup', 'server-start', 'server-shutdown', 'creating-cluster', 'kernel-resources')): return 18
    if fname.startswith(('runtime-', 'config-', 'server-', 'manage-ag-config')): return 19
    if fname.startswith(('auth-', 'client-auth', 'user-manag', 'database-roles', 'role-', 'predefined-roles')): return 20
    if fname.startswith(('managing-databases', 'manage-ag-')): return 22
    if fname.startswith(('localization', 'charset', 'collation', 'locale', 'multibyte')): return 23
    if fname.startswith(('maintenance', 'routine-', 'logfile-maintenance')): return 24
    if fname.startswith(('backup-', 'continuous-archiving')): return 25
    if fname.startswith(('high-availability', 'warm-standby', 'hot-standby')): return 26
    if fname.startswith(('monitoring', 'planner-stats', 'diskusage', 'progress-reporting')): return 27
    if fname.startswith(('wal-', 'wal.html', 'checksums', 'reliability')): return 28
    if fname.startswith('logical-replication'): return 29
    if fname.startswith('catalog-'): return 52
    if fname.startswith(('storage-', 'pageinspect', 'protocol')): return 66
    if fname in ['pgstatstatements.html', 'pgbuffercache.html', 'amcheck.html', 'pgstattuple.html']: return 100
    return 0

def smart_chunk(text, title, filename, max_chars=2500):
    prefix = f"Page: {title}\nSource: {filename}\n\n"
    paragraphs = text.split("\n")
    chunks = []
    current_body = ""

    for para in paragraphs:
        if len(prefix) + len(current_body) + len(para) < max_chars:
            current_body += para + "\n"
        else:
            if current_body.strip():
                chunks.append(prefix + current_body.strip())
            current_body = para + "\n"

    if current_body.strip():
        chunks.append(prefix + current_body.strip())
    return chunks

def safe_extract_text(element):
    """Extrait le texte d'un élément de manière sécurisée si l'élément ou son enfant existe."""
    if element:
        return element.get_text(strip=True)
    return None

def run_ingestion():
    conn = psycopg2.connect(
        dbname=os.getenv("DB_NAME", "rag_db"),
        user=os.getenv("DB_USER", "rag"),
        password=os.getenv("DB_PASS", "rag2026"),
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432")
    )
    cur = conn.cursor()

    print("🧹 Nettoyage de la table rag.documents...")
    cur.execute("TRUNCATE TABLE rag.documents RESTART IDENTITY CASCADE;")
    conn.commit()

    files = sorted(glob.glob(os.path.join(SOURCE_DIR, "*.html")))
    total_files = len(files)
    last_inserted_id = None
    global_chunk_count = 0

    print(f"🚀 {total_files} fichiers détectés pour ingestion.")
    print("-" * 70)

    for index, f_path in enumerate(files, 1):
        fname = os.path.basename(f_path)
        if fname in ['index.html', 'admin.html', 'sql.html', 'reference.html']:
            continue

        try:
            with open(f_path, 'r', encoding='utf-8') as f:
                soup = BeautifulSoup(f, 'html.parser')

            structural_div = soup.find("div", class_=["chapter", "sect1", "refentry", "appendix", "sect2", "part"])
            
            # Extraction sécurisée de la structure sémantique
            part_div = soup.find("div", class_="part")
            chap_div = soup.find("div", class_="chapter")
            sect_div = soup.find("div", class_="sect1")
            sect2_div = soup.find("div", class_="sect2")

            doc_structure = {
                "part": safe_extract_text(part_div.find("h1")) if part_div else None,
                "chapter": safe_extract_text(chap_div.find("h1")) if chap_div else None,
                "section": safe_extract_text(sect_div.find("h1")) if sect_div else None,
                "subsection": safe_extract_text(sect2_div.find("h2")) if sect2_div else None,
                "heading": safe_extract_text(structural_div.find(['h1', 'h2'])) if structural_div else None
            }

            for noise in soup.find_all(['div', 'table'], class_=['navheader', 'navfooter', 'toc']):
                noise.decompose()

            title_tag = soup.find(['h1', 'h2'])
            title = title_tag.get_text(strip=True) if title_tag else fname
            
            content_text = structural_div.get_text(separator="\n", strip=True) if structural_div else soup.get_text(separator="\n", strip=True)
            if len(content_text) < 100:
                continue

            chapter_id = get_chapter_id(fname)
            sub_chunks = smart_chunk(content_text, title, fname)
            chunk_count = len(sub_chunks)

            for chunk_idx, chunk in enumerate(sub_chunks):
                content_hash = hashlib.sha256(chunk.encode('utf-8')).hexdigest()
                
                response = ollama.embeddings(model=EMBEDDING_MODEL, prompt=chunk)
                embedding = response['embedding']

                meta = {
                    "filename": fname,
                    "title": title,
                    "chunk_index": chunk_idx,
                    "chunk_count": chunk_count
                }

                cur.execute(
                    """
                    INSERT INTO rag.documents (
                        source, title, content, content_hash, metadata, embedding, chapter_id,
                        part, chapter, section, subsection, heading, chunk_index, chunk_count
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id;
                    """,
                    (
                        fname, title, chunk, content_hash, dumps(meta), embedding, chapter_id,
                        doc_structure["part"], doc_structure["chapter"], doc_structure["section"],
                        doc_structure["subsection"], doc_structure["heading"], chunk_idx, chunk_count
                    )
                )
                current_inserted_id = cur.fetchone()[0]

                if last_inserted_id:
                    cur.execute("UPDATE rag.documents SET next_document_id = %s WHERE id = %s;", (current_inserted_id, last_inserted_id))
                    cur.execute("UPDATE rag.documents SET prev_document_id = %s WHERE id = %s;", (last_inserted_id, current_inserted_id))

                last_inserted_id = current_inserted_id
                global_chunk_count += 1

            print(f"[{index}/{total_files}] ✅ {fname:<40} | Chunks: {chunk_count}")
            conn.commit()

        except Exception as e:
            print(f"❌ ERREUR sur {fname} : {e}")
            conn.rollback()

    cur.close()
    conn.close()
    print(f"\n✨ Ingestion terminée. {global_chunk_count} chunks vectorisés en base.")

if __name__ == "__main__":
    run_ingestion()
