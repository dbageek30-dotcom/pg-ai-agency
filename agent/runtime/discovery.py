import os
import glob
import json
import re
from datetime import datetime

# Dossiers de recherche ordonnés par pertinence (Distributions variées)
SEARCH_PATHS = [
    "/usr/lib/postgresql/*/bin",   # Ubuntu/Debian
    "/usr/pgsql-*/bin",            # RHEL/CentOS
    "/usr/pgsql*/bin",             # Variantes RHEL
    "/opt/pgagent/bin",
    "/opt/patroni/bin",
    "/opt/pgbackrest/bin",
    "/usr/local/bin",
    "/usr/bin",
    "/usr/sbin"
]

def get_version_from_path(path):
    """Extrait le numéro de version d'un chemin (ex: '13' ou '9.2')."""
    # Cherche un nombre après 'postgresql/' ou 'pgsql-' ou 'pgsql'
    match = re.search(r'(?:postgresql/|pgsql-|pgsql)(\d+\.?\d*)', path)
    return match.group(1) if match else None

def discover_binaries():
    """Scanne le système avec gestion intelligente des versions multiples."""
    registry = {
        "last_scan": datetime.now().isoformat(),
        "binaries": {}
    }

    # Liste pour stocker les dossiers trouvés afin de les trier par version
    found_dirs = []
    for pattern in SEARCH_PATHS:
        for p in glob.glob(pattern):
            if os.path.isdir(p):
                found_dirs.append(p)

    # On trie les dossiers pour que les versions les plus hautes soient traitées en premier
    # Ainsi, 'psql' pointera par défaut vers la version la plus récente
    found_dirs.sort(key=lambda x: (get_version_from_path(x) or "0"), reverse=True)

    for base_path in found_dirs:
        version = get_version_from_path(base_path)
        
        try:
            with os.scandir(base_path) as it:
                for entry in it:
                    try:
                        if entry.is_file() and os.access(entry.path, os.X_OK):
                            # 1. Alias par défaut (ex: psql) 
                            # Le premier trouvé (le plus récent dû au tri) gagne
                            if entry.name not in registry["binaries"]:
                                registry["binaries"][entry.name] = entry.path
                            
                            # 2. Alias versionné (ex: psql-13, pg_dump-9.2)
                            # Permet à l'IA de forcer une version sur des serveurs legacy
                            if version:
                                versioned_name = f"{entry.name}-{version}"
                                if versioned_name not in registry["binaries"]:
                                    registry["binaries"][versioned_name] = entry.path
                                    
                    except OSError:
                        continue
        except PermissionError:
            continue 

    return registry

if __name__ == "__main__":
    # Test local pour visualiser le registre généré
    print(json.dumps(discover_binaries(), indent=4))
