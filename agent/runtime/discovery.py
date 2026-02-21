import os
import glob
import json
import subprocess
from datetime import datetime

# Import dynamique des outils autorisés pour le croisement immédiat
try:
    from security.allowlist import ALLOWED_TOOLS
except ImportError:
    # Ajustement du path si nécessaire pour trouver security.allowlist
    import sys
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from security.allowlist import ALLOWED_TOOLS

CONFIG_PATH = "/opt/pgagent/config/config.json"
REGISTRY_PATH = "/opt/pgagent/runtime/registry.json"

# Métadonnées pour enrichir la "boîte à outils" de l'IA
DBA_TOOLS_METADATA = {
    "pgbackrest": {"cmd": "--version", "desc": "Backup & Restore tool"},
    "patronictl": {"cmd": "version", "desc": "High-Availability manager"},
    "psql": {"cmd": "--version", "desc": "PostgreSQL CLI"},
    "pg_verifybackup": {"cmd": "--version", "desc": "Backup validation tool"},
    "repmgr": {"cmd": "--version", "desc": "Replication manager"},
    "pg_basebackup": {"cmd": "--version", "desc": "PostgreSQL base backup tool"},
    "ls": {"cmd": "--version", "desc": "List directory contents"}
}

def load_config():
    if not os.path.exists(CONFIG_PATH):
        return {}
    try:
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def get_tool_metadata(name, path):
    """Interroge le binaire pour obtenir sa version réelle et sa description."""
    metadata = {"name": name, "path": path, "version": "unknown", "description": ""}
    if name in DBA_TOOLS_METADATA:
        try:
            cmd = DBA_TOOLS_METADATA[name]["cmd"]
            result = subprocess.run([path, cmd], capture_output=True, text=True, timeout=2)
            if result.returncode == 0:
                metadata["version"] = result.stdout.strip().split('\n')[0]
            metadata["description"] = DBA_TOOLS_METADATA[name]["desc"]
        except Exception:
            pass
    return metadata

def resolve_and_detect_conflicts(found_binaries):
    """
    Applique les règles de priorité et détecte les ambiguïtés.
    """
    final_tools = {}
    conflicts = {}

    for name, paths in found_binaries.items():
        if len(paths) == 1:
            final_tools[name] = paths[0]
        else:
            # Priorité : on dégage /usr/bin et /bin s'il y a un chemin spécifique (Postgres lib)
            expert_paths = [p for p in paths if not p.startswith(('/usr/bin/', '/bin/'))]
            eval_paths = expert_paths if expert_paths else paths
            
            if len(eval_paths) > 1:
                conflicts[name] = eval_paths
            else:
                final_tools[name] = eval_paths[0]
                
    return final_tools, conflicts

def discover_binaries(allowed_tools=ALLOWED_TOOLS):
    """
    Scanne avec croisement STRICT et IMMÉDIAT.
    """
    SEARCH_PATHS = [
        "/usr/lib/postgresql/*/bin",
        "/usr/pgsql-*/bin",
        "/opt/pgagent/bin",
        "/usr/bin",
        "/usr/local/bin"
    ]
    
    found_binaries = {}
    
    # On itère sur les chemins de recherche
    for pattern in SEARCH_PATHS:
        for p in glob.glob(pattern):
            if not os.path.isdir(p):
                continue
            
            # On ne liste pas tout le dossier si c'est un gros dossier comme /usr/bin
            # On vérifie uniquement la présence des outils autorisés pour gagner du temps
            for tool_name in allowed_tools:
                full_path = os.path.join(p, tool_name)
                if os.path.exists(full_path) and os.path.isfile(full_path):
                    if os.access(full_path, os.X_OK):
                        if tool_name not in found_binaries:
                            found_binaries[tool_name] = []
                        if full_path not in found_binaries[tool_name]:
                            found_binaries[tool_name].append(full_path)

    # Résolution des doublons et conflits
    verified_paths, conflicts = resolve_and_detect_conflicts(found_binaries)

    registry = {
        "last_scan": datetime.now().isoformat(),
        "tools": [], # Boîte à outils enrichie pour le LLM
        "binaries": verified_paths, # Pour l'exécuteur
        "has_conflicts": len(conflicts) > 0,
        "conflicts": conflicts,
        "capabilities": {"os_info": os.uname().sysname}
    }

    # On n'ajoute que les outils résolus (sans conflit) à la boîte à outils du LLM
    for name, path in verified_paths.items():
        registry["tools"].append(get_tool_metadata(name, path))
        
    return registry

def get_registry():
    if not os.path.exists(REGISTRY_PATH):
        return discover_binaries(ALLOWED_TOOLS)
    with open(REGISTRY_PATH, "r") as f:
        return json.load(f)

def refresh_registry():
    """Force un nouveau scan et sauvegarde le résultat."""
    data = discover_binaries(ALLOWED_TOOLS)
    os.makedirs(os.path.dirname(REGISTRY_PATH), exist_ok=True)
    with open(REGISTRY_PATH, "w") as f:
        json.dump(data, f, indent=2)
    return data

if __name__ == "__main__":
    print(json.dumps(discover_binaries(ALLOWED_TOOLS), indent=2))
