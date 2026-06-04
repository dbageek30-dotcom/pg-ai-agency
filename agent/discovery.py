import os
import glob
import json
from datetime import datetime

# Liste des outils autorisés par défaut si l'import de l'allowlist échoue
ALLOWED_TOOLS = {"psql", "pg_dump", "pg_restore", "pg_ctl", "cat", "grep", "tail", "ls", "sed"}

def discover_binaries(allowed_tools=ALLOWED_TOOLS):
    """
    Scanne le système et retourne un dictionnaire {nom: chemin_absolu}.
    Priorise les versions spécifiques à PostgreSQL.
    """
    all_list = list(allowed_tools)

    # Chemins standards de recherche des binaires PostgreSQL et OS
    SEARCH_PATHS = [
        "/usr/lib/postgresql/*/bin", 
        "/usr/pgsql-*/bin", 
        "/usr/bin", 
        "/usr/local/bin"
    ]
    
    found_map = {}
    for pattern in SEARCH_PATHS:
        for p in glob.glob(pattern):
            if not os.path.isdir(p): 
                continue
            for tool_name in all_list:
                full_path = os.path.join(p, tool_name)
                
                if os.path.exists(full_path) and os.path.isfile(full_path) and os.access(full_path, os.X_OK):
                    if tool_name not in found_map:
                        found_map[tool_name] = []
                    if full_path not in found_map[tool_name]:
                        found_map[tool_name].append(full_path)
    
    # Construction du registre léger
    registry = {
        "last_scan": datetime.now().isoformat(),
        "binaries": {},
        "capabilities": {"os_info": os.uname().sysname}
    }
    
    for name, paths in found_map.items():
        # Règle de priorité d'un bon DBA : 
        # On favorise les chemins contenant 'postgresql' ou 'pgsql'
        # On trie par longueur de chemin (le plus long est souvent le plus précis, ex: v18)
        sorted_paths = sorted(
            paths, 
            key=lambda p: ("/postgresql/" in p or "/pgsql-" in p, len(p)), 
            reverse=True
        )
        # On ne garde que la meilleure correspondance
        registry["binaries"][name] = sorted_paths[0]
        
    return registry

def get_registry(force_rescan=False):
    """Charge le JSON existant ou lance un scan léger."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base_dir, "discovery.json")
    
    if force_rescan or not os.path.exists(path):
        results = discover_binaries()
        try:
            with open(path, "w") as f:
                json.dump(results, f, indent=2)
        except: 
            pass
        return results
        
    with open(path, "r") as f:
        return json.load(f)

if __name__ == "__main__":
    print("🔍 [OPTIMIZED DISCOVERY] Scan en cours...")
    results = discover_binaries() 
    
    base_dir = os.path.dirname(os.path.abspath(__file__))
    output_path = os.path.join(base_dir, "discovery.json")
    
    try:
        with open(output_path, "w") as f:
            json.dump(results, f, indent=2)
        print(f"✅ Registre minimaliste généré : {output_path}")
        print(f"📊 {len(results['binaries'])} outils prêts pour le LLM.")
        for name, path in results['binaries'].items():
            print(f"   ∟ {name.ljust(12)}: {path}")
    except Exception as e:
        print(f"❌ Erreur lors de l'écriture du registre : {e}")
