import json
import os
# Import corrigé : passage en import absolu pour la structure v1.2.1
from runtime.discovery import discover_binaries

REGISTRY_FILE = "/opt/pgagent/runtime/registry.json"

if not os.path.exists("/opt/pgagent"):
    REGISTRY_FILE = os.path.join(os.path.dirname(__file__), "registry.json")

def refresh_registry():
    """Scanne et force la mise à jour du fichier registry.json."""
    data = discover_binaries()
    os.makedirs(os.path.dirname(REGISTRY_FILE), exist_ok=True)
    with open(REGISTRY_FILE, "w") as f:
        json.dump(data, f, indent=4)
    return data

def get_binary_path(tool_name):
    """Récupère le chemin d'un binaire depuis le registry."""
    if not os.path.exists(REGISTRY_FILE):
        refresh_registry()
        
    try:
        with open(REGISTRY_FILE, "r") as f:
            registry = json.load(f)
        return registry.get("binaries", {}).get(tool_name)
    except Exception:
        return None
