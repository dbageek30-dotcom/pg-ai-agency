import os
import glob
import json
import re
import subprocess
from datetime import datetime

# Dossiers de recherche ordonnés par pertinence
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
    """Extrait proprement le numéro de version d'un chemin PostgreSQL."""
    # Capture le nombre juste après le nom du package (ex: /postgresql/16/bin)
    match = re.search(r'(?:postgresql|pgsql)[/-]?(\d+\.?\d*)', path)
    return match.group(1) if match else None

def discover_pg_extensions():
    """Découvre les extensions actives via psql sans casser le flux."""
    extensions = {}
    try:
        # On utilise -Atc pour un formatage minimal (parfait pour le parsing)
        # On cible uniquement les extensions installées sur l'instance par défaut
        query = "SELECT name, installed_version FROM pg_available_extensions WHERE installed_version IS NOT NULL;"
        result = subprocess.run(
            ["psql", "-Atc", query],
            capture_output=True, 
            text=True, 
            timeout=5
        )
        
        if result.returncode == 0:
            for line in result.stdout.strip().split('\n'):
                if '|' in line:
                    name, version = line.split('|')
                    extensions[name] = version
    except Exception:
        # En cas d'absence de psql ou de DB injoignable, on retourne un dict vide
        pass
    return extensions

def discover_binaries():
    """Scanne le système et construit le registre des capacités."""
    registry = {
        "last_scan": datetime.now().isoformat(),
        "binaries": {},
        "capabilities": {
            "extensions": {},
            "os_info": os.uname().sysname if hasattr(os, 'uname') else "unknown"
        }
    }

    found_dirs = []
    for pattern in SEARCH_PATHS:
        for p in glob.glob(pattern):
            if os.path.isdir(p):
                found_dirs.append(p)

    # Tri : les versions les plus hautes en premier
    found_dirs.sort(key=lambda x: (get_version_from_path(x) or "0"), reverse=True)

    for base_path in found_dirs:
        version = get_version_from_path(base_path)
        
        try:
            with os.scandir(base_path) as it:
                for entry in it:
                    try:
                        if entry.is_file() and os.access(entry.path, os.X_OK):
                            # 1. Alias principal (le premier trouvé/plus récent gagne)
                            if entry.name not in registry["binaries"]:
                                registry["binaries"][entry.name] = entry.path
                            
                            # 2. Alias versionné (ex: psql-16)
                            if version:
                                versioned_name = f"{entry.name}-{version}"
                                if versioned_name not in registry["binaries"]:
                                    registry["binaries"][versioned_name] = entry.path
                                    
                    except OSError:
                        continue
        except PermissionError:
            continue 

    # AJOUT : Si psql est trouvé, on enrichit les capacités SQL
    if "psql" in registry["binaries"]:
        registry["capabilities"]["extensions"] = discover_pg_extensions()

    return registry

if __name__ == "__main__":
    # Génération du JSON final
    print(json.dumps(discover_binaries(), indent=4))
