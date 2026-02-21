import os
import glob
import json
import subprocess
from datetime import datetime

# Import dynamique du client LLM
try:
    from runtime.llm_client import MockLLM, OllamaClient
except ImportError:
    from llm_client import MockLLM, OllamaClient

CONFIG_PATH = "/opt/pgagent/config/config.json"
REGISTRY_PATH = "/opt/pgagent/runtime/registry.json"

# Métadonnées pour enrichir la "boîte à outils" de l'IA
DBA_TOOLS_METADATA = {
    "pgbackrest": {"cmd": "--version", "desc": "Backup & Restore tool"},
    "patronictl": {"cmd": "version", "desc": "High-Availability manager"},
    "psql": {"cmd": "--version", "desc": "PostgreSQL CLI"},
    "pg_verifybackup": {"cmd": "--version", "desc": "Backup validation tool"},
    "repmgr": {"cmd": "--version", "desc": "Replication manager"},
    "pg_basebackup": {"cmd": "--version", "desc": "PostgreSQL base backup tool"}
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
                # On nettoie la sortie pour n'avoir que la ligne de version
                metadata["version"] = result.stdout.strip().split('\n')[0]
            metadata["description"] = DBA_TOOLS_METADATA[name]["desc"]
        except Exception:
            pass
    return metadata

def resolve_and_detect_conflicts(found_binaries):
    """
    Applique tes règles :
    1. Priorité aux chemins spécifiques (ex: /usr/lib/postgresql/...) sur /usr/bin.
    2. Si plusieurs chemins spécifiques subsistent -> Conflit.
    """
    final_tools = {}
    conflicts = {}

    for name, paths in found_binaries.items():
        if len(paths) == 1:
            final_tools[name] = paths[0]
        else:
            # Règle : on écarte /usr/bin/ et /bin/ si on a des chemins experts
            expert_paths = [p for p in paths if not p.startswith(('/usr/bin/', '/bin/'))]
            
            # On réévalue avec les chemins filtrés
            eval_paths = expert_paths if expert_paths else paths
            
            if len(eval_paths) > 1:
                # Toujours plusieurs versions après filtrage -> Arbitrage requis
                conflicts[name] = eval_paths
            else:
                final_tools[name] = eval_paths[0]
                
    return final_tools, conflicts

def discover_binaries(allowed_tools=None):
    """
    Scanne le système, filtre selon l'allowlist, gère les priorités 
    de chemins et détecte les conflits.
    """
    SEARCH_PATHS = [
        "/usr/lib/postgresql/*/bin",
        "/usr/pgsql-*/bin",
        "/opt/pgagent/bin",
        "/usr/bin",
        "/usr/local/bin"
    ]
    
    found_binaries = {} # Temporaire : {"psql": ["/path1", "/path2"]}

    for pattern in SEARCH_PATHS:
        for p in glob.glob(pattern):
            if os.path.isdir(p):
                with os.scandir(p) as it:
                    for entry in it:
                        if entry.is_file() and os.access(entry.path, os.X_OK):
                            # Si allowed_tools est fourni, on filtre immédiatement
                            if allowed_tools and entry.name not in allowed_tools:
                                continue
                            
                            if entry.name not in found_binaries:
                                found_binaries[entry.name] = []
                            if entry.path not in found_binaries[entry.name]:
                                found_binaries[entry.name].append(entry.path)

    # Résolution des priorités et détection de conflits
    verified_paths, conflicts = resolve_and_detect_conflicts(found_binaries)

    registry = {
        "last_scan": datetime.now().isoformat(),
        "tools": [], # Liste enrichie pour le LLM
        "binaries": verified_paths, # Map simple pour l'exécuteur
        "has_conflicts": len(conflicts) > 0,
        "conflicts": conflicts,
        "capabilities": {"os_info": os.uname().sysname}
    }

    # Enrichissement avec les métadonnées (version, desc) pour le LLM
    for name, path in verified_paths.items():
        registry["tools"].append(get_tool_metadata(name, path))
        
    return registry

def get_registry():
    """Charge le registre depuis le fichier ou lance un scan si absent."""
    if not os.path.exists(REGISTRY_PATH):
        # Pour le scan auto, on peut charger la liste depuis le module security
        from security.allowlist import ALLOWED_TOOLS
        return discover_binaries(ALLOWED_TOOLS)
    with open(REGISTRY_PATH, "r") as f:
        return json.load(f)

_cached_client = None

def get_llm_client():
    global _cached_client
    if _cached_client:
        return _cached_client

    cfg = load_config().get("llm", {})
    provider = cfg.get("provider", "mock")

    if provider == "ollama":
        _cached_client = OllamaClient(
            url=cfg.get("url", "http://10.214.0.8:11434"),
            model=cfg.get("model", "qwen2.5:7b-instruct-q4_K_M")
        )
    else:
        _cached_client = MockLLM()
    
    return _cached_client

if __name__ == "__main__":
    # Test direct du scan
    from security.allowlist import ALLOWED_TOOLS
    print(json.dumps(discover_binaries(ALLOWED_TOOLS), indent=2))
