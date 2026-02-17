import subprocess
import re

class HelpParser:
    """
    Parser générique pour analyser la sortie d'un outil CLI (--help)
    et produire un manifeste brut exploitable par le LLM + validateur.
    """

    FLAG_REGEX = re.compile(r"^\s*(-{1,2}[A-Za-z0-9][A-Za-z0-9\-]*)\s*(.*)$")

    def run_help(self, tool: str) -> str:
        """
        Exécute 'tool --help' et retourne la sortie brute.
        """
        try:
            result = subprocess.run(
                [tool, "--help"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True
            )
            return result.stdout
        except FileNotFoundError:
            raise RuntimeError(f"Outil introuvable : {tool}")

    def parse(self, tool: str) -> dict:
        """
        Analyse la sortie de --help et construit un manifeste brut.
        """
        help_text = self.run_help(tool)
        lines = help_text.splitlines()

        manifest = {
            "tool": tool,
            "version": "unknown",
            "description": "",
            "category": "general",
            "commands": {
                "default": {
                    "description": "",
                    "parameters": {},
                    "examples": []
                }
            }
        }

        params = manifest["commands"]["default"]["parameters"]

        for line in lines:
            line = line.rstrip()

            # 1. Détection d'un flag
            match = self.FLAG_REGEX.match(line)
            if match:
                flag = match.group(1)
                desc = match.group(2).strip()

                params[flag] = {
                    "type": self._infer_type_from_description(desc),
                    "required": False,
                    "default": None,
                    "allowed_values": [],
                    "deprecated": False,
                    "added_in": None,
                    "removed_in": None,
                    "conflicts_with": [],
                    "depends_on": []
                }
                continue

            # 2. Détection d'une description générale
            if not manifest["description"] and len(line) > 10:
                manifest["description"] = line

        return manifest

    def _infer_type_from_description(self, desc: str) -> str:
        """
        Déduit un type probable à partir de la description du flag.
        """
        desc = desc.lower()

        if "directory" in desc or "path" in desc:
            return "path"
        if "size" in desc or "bytes" in desc:
            return "size"
        if "true" in desc or "false" in desc:
            return "boolean"
        if "level" in desc or "number" in desc or "count" in desc:
            return "integer"
        if "mode" in desc or "method" in desc:
            return "enum"

        return "string"

