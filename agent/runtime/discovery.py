import os
import glob
import json
from datetime import datetime

# Dossiers où chercher les binaires (ajout de chemins courants pour PG)
SEARCH_PATHS = [
    "/usr/bin",
    "/usr/local/bin",
    "/usr/sbin",
    "/usr/lib/postgresql/*/bin",
    "/opt/patroni/bin",
    "/opt/pgbackrest/bin"
]

def discover_binaries():
    """Scanne le système à la recherche d'exécutables utiles."""
    registry = {
        "last_scan": datetime.now().isoformat(),
        "binaries": {}
    }

    for pattern in SEARCH_PATHS:
        # glob.glob gère les jokers comme '*' pour les versions de Postgres
        for base_path in glob.glob(pattern):
            if not os.path.isdir(base_path):
                continue
            
            try:
                with os.scandir(base_path) as it:
                    for entry in it:
                        # On ne garde que les fichiers exécutables
                        try:
                            if entry.is_file() and os.access(entry.path, os.X_OK):
                                # Priorité au premier trouvé (souvent le chemin système standard)
                                if entry.name not in registry["binaries"]:
                                    registry["binaries"][entry.name] = entry.path
                        except OSError:
                            continue
            except PermissionError:
                continue 

    return registry

if __name__ == "__main__":
    # Test local
    print(json.dumps(discover_binaries(), indent=2))
