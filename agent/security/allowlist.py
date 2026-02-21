import json
import os
import logging

ALLOWLIST_PATH = os.path.join(os.path.dirname(__file__), "allowed_tools.json")

def load_allowed_tools():
    """Charge la liste des outils autorisés avec sécurité."""
    if not os.path.exists(ALLOWLIST_PATH):
        # Fallback de sécurité : on autorise le minimum vital si le fichier manque
        logging.warning(f"Allowlist file {ALLOWLIST_PATH} not found. Using default minimal set.")
        return {"psql", "pg_dump", "patronictl"}
    
    try:
        with open(ALLOWLIST_PATH, "r") as f:
            config = json.load(f)
        return set(config.get("allowed_tools", []))
    except Exception as e:
        logging.error(f"Error loading allowlist: {e}")
        return set()

# Chargement initial
ALLOWED_TOOLS = load_allowed_tools()

def extract_tool(command: str) -> str:
    """Extrait le nom du binaire d'une ligne de commande."""
    if not command:
        return ""
    return command.strip().split()[0]

def is_tool_allowed(command: str) -> bool:
    tool = extract_tool(command)
    allowed = tool in ALLOWED_TOOLS
    # Ce print apparaîtra dans les logs de ton service (journalctl -u pgagent)
    print(f"DEBUG ALLOWLIST: tool='{tool}', allowed={allowed}, list={ALLOWED_TOOLS}")
    return allowed
