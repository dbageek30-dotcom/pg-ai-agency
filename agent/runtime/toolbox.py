import re
import json
import logging
from executor import run_command

logger = logging.getLogger(__name__)

class ToolboxManager:
    def __init__(self):
        # On définit des patterns de parsing pour différents styles de help
        self.option_pattern = re.compile(r"^\s*(-\w,?\s+--[\w-]+|--[\w-]+)\s+(.*)")
        self.command_pattern = re.compile(r"^\s+([\w-]+)\s{2,}(.*)")

    def get_structured_help(self, tool_name, subcommand=None):
        """
        Récupère le help et le transforme en dictionnaire structuré.
        """
        full_cmd = f"{tool_name} {subcommand} --help" if subcommand else f"{tool_name} --help"
        
        logger.info(f"🧰 Génération de la toolbox pour: {full_cmd}")
        result = run_command(full_cmd)
        
        if result["exit_code"] != 0:
            return {"error": f"Impossible d'exécuter {full_cmd}", "details": result["stderr"]}

        return self._parse_raw_text(result["stdout"], tool_name, subcommand)

    def _parse_raw_text(self, text, tool, sub):
        """
        Analyse le texte brut pour en extraire les options et commandes.
        """
        blueprint = {
            "tool": tool,
            "subcommand": sub,
            "options": [],
            "available_commands": [],
            "usage": ""
        }

        lines = text.split('\n')
        is_command_section = False

        for line in lines:
            # Capture de l'usage (souvent la première ligne non vide)
            if "Usage:" in line and not blueprint["usage"]:
                blueprint["usage"] = line.strip()

            # Détection de la section des commandes (pour Patroni/Repmgr)
            if any(key in line for key in ["Commands:", "Available Commands:"]):
                is_command_section = True
                continue

            # 1. Extraction des Options (--flag)
            opt_match = self.option_pattern.match(line)
            if opt_match:
                blueprint["options"].append({
                    "flag": opt_match.group(1).strip(),
                    "description": opt_match.group(2).strip()
                })
                continue

            # 2. Extraction des Sous-commandes
            if is_command_section:
                cmd_match = self.command_pattern.match(line)
                if cmd_match:
                    blueprint["available_commands"].append({
                        "command": cmd_match.group(1).strip(),
                        "description": cmd_match.group(2).strip()
                    })

        return blueprint

# Test rapide si lancé en direct
if __name__ == "__main__":
    toolbox = ToolboxManager()
    print(json.dumps(toolbox.get_structured_help("patronictl"), indent=2))
