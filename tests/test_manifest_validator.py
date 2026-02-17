from tools.manifest_validator import ManifestValidator

raw = {
    "tool": "pg_basebackup",
    "version": "",
    "commands": {
        "default": {
            "parameters": {
                "-D": {"type": "directory"},  # type invalide
                "-X": {"type": "enum", "allowed_values": ["stream", "fetch"]},
            }
        }
    }
}

validator = ManifestValidator()
clean = validator.validate(raw)

print("\n=== MANIFEST VALIDÉ ===")
print(clean)

