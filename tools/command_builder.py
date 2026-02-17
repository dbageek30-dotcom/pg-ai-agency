import os

class CommandBuilder:
    def __init__(self, env: dict):
        self.env = env

    def build(self, manifest: dict, command_name: str = "default") -> str:
        """
        Construit une commande CLI à partir d'un manifeste validé + .env.
        """

        tool = manifest["tool"]
        cmd_data = manifest["commands"].get(command_name)

        if not cmd_data:
            raise ValueError(f"Commande inconnue : {command_name}")

        params = cmd_data["parameters"]
        parts = [tool]

        for flag, meta in params.items():
            value = None

            # 1. Valeur fournie par l'utilisateur (plus tard)
            # (tu ajouteras ça quand tu feras l'interface agent)

            # 2. Valeur issue du .env
            env_key = self._env_key_for_flag(flag)
            if env_key in self.env:
                value = self.env[env_key]

            # 3. Valeur par défaut du manifeste
            if value is None and meta.get("default") is not None:
                value = meta["default"]

            # 4. Si le paramètre est obligatoire mais toujours vide → erreur
            if meta.get("required") and value is None:
                raise ValueError(f"Paramètre obligatoire manquant : {flag}")

            # 5. Si aucune valeur → on ignore le flag
            if value is None:
                continue

            # 6. Construction du flag final
            if meta["type"] == "boolean":
                if value in ["true", True, "1", 1]:
                    parts.append(flag)
            else:
                parts.append(f"{flag} {value}")

        return " ".join(parts)

    def _env_key_for_flag(self, flag: str) -> str:
        """
        Convertit un flag CLI en clé .env probable.
        Exemple : -D → BACKUP_DIR, --stanza → PGBACKREST_STANZA
        """
        flag = flag.lstrip("-")

        # conventions simples
        mapping = {
            "D": "BACKUP_DIR",
            "stanza": "PGBACKREST_STANZA",
            "host": "PGHOST",
            "port": "PGPORT",
            "user": "PGUSER",
            "dbname": "PGDATABASE",
        }

        return mapping.get(flag, flag.upper())

