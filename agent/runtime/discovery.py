import os
import glob
import json
import shutil
from datetime import datetime

# Dossiers où chercher les binaires
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
        for base_path in glob.glob(pattern):
            if not os.path.isdir(base_path):
                continue
            
            try:
                with os.scandir(base_path) as it:
                    for entry in it:
                        # On ne garde que les fichiers exécutables
                        if entry.is_file() and os.access(entry.path, os.X_OK):
                            # Si le binaire existe déjà (ex: psql dans /usr/bin 
                            # et dans /usr/lib/pg/bin), on garde le premier trouvé
                            if entry.name not in registry["binaries"]:
                                registry["binaries"][entry.name] = entry.path
            except PermissionError:
                continue # On ignore les dossiers où on n'a pas accès

    return registry

if __name__ == "__main__":
    # Test local
    print(json.dumps(discover_binaries(), indent=2))
