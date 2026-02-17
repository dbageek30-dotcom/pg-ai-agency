class ManifestValidator:
    VALID_TYPES = {"string", "integer", "boolean", "enum", "path", "size", "list"}

    def validate(self, manifest: dict) -> dict:
        cleaned = {}

        cleaned["tool"] = manifest.get("tool", "").strip()
        cleaned["version"] = manifest.get("version", "").strip()
        cleaned["description"] = manifest.get("description", "")
        cleaned["category"] = manifest.get("category", "general")

        commands = manifest.get("commands", {})
        cleaned["commands"] = {}

        for cmd_name, cmd_data in commands.items():
            cleaned_cmd = {
                "description": cmd_data.get("description", ""),
                "parameters": {},
                "examples": cmd_data.get("examples", [])
            }

            params = cmd_data.get("parameters", {})
            for flag, p in params.items():
                cleaned_param = {
                    "type": p.get("type", "string"),
                    "required": bool(p.get("required", False)),
                    "default": p.get("default"),
                    "allowed_values": p.get("allowed_values", []),
                    "deprecated": bool(p.get("deprecated", False)),
                    "added_in": p.get("added_in"),
                    "removed_in": p.get("removed_in"),
                    "conflicts_with": p.get("conflicts_with", []),
                    "depends_on": p.get("depends_on", [])
                }

                if cleaned_param["type"] not in self.VALID_TYPES:
                    cleaned_param["type"] = "string"

                cleaned_cmd["parameters"][flag] = cleaned_param

            cleaned["commands"][cmd_name] = cleaned_cmd

        cleaned["notes"] = manifest.get("notes", [])

        return cleaned

