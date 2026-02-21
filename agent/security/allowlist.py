import json
import os
import logging

ALLOWLIST_PATH = os.path.join(os.path.dirname(__file__), "allowed_tools.json")

def load_allowed_tools():
    """Charge la liste des outils autorisés avec sécurité."""
    if not os.path.exists(ALLOWLIST_PATH):
        logging.warning(f"Allowlist file {ALLOWLIST_PATH} not found. Using default minimal set.")
        return {"psql", "pg_dump", "patronictl", "ls"}
    
    try:
        with open(ALLOWLIST_PATH, "r") as f:
            config = json.load(f)
        return set(config.get("allowed_tools", []))
    except Exception as e:
        logging.error(f"Error loading allowlist: {e}")
        return set()

# Chargement initial
ALLOWED_TOOLS = load_allowed_tools()

def extract_tool_name(command_or_path: str) -> str:
    """Extrait le nom court (ex: /usr/bin/ls -> ls)."""
    if not command_or_path:
        return ""
    first_part = command_or_path.strip().split()[0]
    return os.path.basename(first_part)

# ALIAS pour la compatibilité avec server.py et orchestrator.py
extract_tool = extract_tool_name

def is_tool_allowed(command: str) -> bool:
    """Vérifie si le binaire est autorisé."""
    current_allowed = load_allowed_tools()
    tool_name = extract_tool_name(command)
    allowed = tool_name in current_allowed
    
    if not allowed:
        # On logue l'erreur pour journalctl
        logging.warning(f"SECURITY REJECTED: tool='{tool_name}' not in {current_allowed}")
        
    return allowed
