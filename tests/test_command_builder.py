from tools.command_builder import CommandBuilder

manifest = {
    "tool": "pg_basebackup",
    "commands": {
        "default": {
            "parameters": {
                "-D": {"type": "path", "required": True},
                "-X": {"type": "enum", "default": "stream"},
                "--progress": {"type": "boolean", "default": True}
            }
        }
    }
}

env = {
    "BACKUP_DIR": "/var/backups/pg"
}

builder = CommandBuilder(env)
cmd = builder.build(manifest)

print("\n=== COMMANDE GÉNÉRÉE ===")
print(cmd)

