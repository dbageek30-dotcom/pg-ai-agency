from tools.help_parser import HelpParser
from tools.manifest_validator import ManifestValidator
from tools.command_builder import CommandBuilder

parser = HelpParser()
validator = ManifestValidator()

# 1. Parser
raw = parser.parse("pg_basebackup")

# 2. Validation
manifest = validator.validate(raw)

# 3. Command Builder
env = {
    "BACKUP_DIR": "/var/backups/pg"
}

builder = CommandBuilder(env)
cmd = builder.build(manifest)

print("\n=== CHAÎNE COMPLÈTE ===")
print(cmd)

