from tools.help_parser import HelpParser

parser = HelpParser()

manifest = parser.parse("pg_basebackup")

print("\n=== MANIFEST BRUT ===")
for flag, meta in manifest["commands"]["default"]["parameters"].items():
    print(flag, "→", meta["type"])

