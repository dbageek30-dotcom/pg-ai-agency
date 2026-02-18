import json
import os

ALLOWLIST_PATH = os.path.join(os.path.dirname(__file__), "allowed_tools.json")

with open(ALLOWLIST_PATH, "r") as f:
    CONFIG = json.load(f)

ALLOWED_TOOLS = set(CONFIG.get("allowed_tools", []))

def extract_tool(command: str) -> str:
    return command.strip().split()[0]

def is_tool_allowed(command: str) -> bool:
    tool = extract_tool(command)
    return tool in ALLOWED_TOOLS

