import json
import os
from .discovery import discover_binaries

REGISTRY_FILE = "/opt/pgagent/runtime/registry.json"
# Fallback pour le développement local si le chemin /opt n'existe pas
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
        
    with open(REGISTRY_FILE, "r") as f:
        registry = json.load(f)
    
    return registry.get("binaries", {}).get(tool_name)
