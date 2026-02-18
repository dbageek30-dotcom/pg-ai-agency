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

def test_command_builder_generates_expected_command():
    builder = CommandBuilder(env)
    cmd = builder.build(manifest)
    assert cmd == "pg_basebackup -D /var/backups/pg -X stream --progress"

