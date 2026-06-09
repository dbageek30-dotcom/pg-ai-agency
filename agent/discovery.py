import os
import glob
import json
import subprocess
from datetime import datetime

# ==============================================================================
# WHITELISTS STRICTES DES OUTILS AUTORISÉS POUR LE LLM 14B
# ==============================================================================
# Outils natifs PostgreSQL pour l'administration et la maintenance de la base
POSTGRES_TOOLS = {"psql", "pg_ctl", "pg_dump", "initdb"}

# Outils système pour l'analyse des ressources, de l'espace disque et l'édition
SYSTEM_TOOLS = {"vi", "cat", "sed", "du", "df", "free", "lscpu", "ps"}


def get_pg_topology():
    """
    Interroge PostgreSQL pour récupérer dynamiquement le chemin PGDATA 
    et l'emplacement réel des fichiers de configuration principaux.
    """
    topology = {"PGDATA": None, "postgresql.conf": None, "pg_hba.conf": None}
    try:
        # Exécution locale en tant que postgres pour lire la configuration active
        cmd = [
            "psql", "-U", "postgres", "-t", "-A", "-c", 
            "SELECT name, setting FROM pg_settings WHERE name IN ('data_directory', 'config_file', 'hba_file');"
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        
        for line in res.stdout.strip().split("\n"):
            if "|" in line:
                name, val = line.split("|", 1)
                if name == "data_directory": 
                    topology["PGDATA"] = val
                elif name == "config_file": 
                    topology["postgresql.conf"] = val
                elif name == "hba_file": 
                    topology["pg_hba.conf"] = val
    except Exception:
        # Fallback de secours si l'instance PostgreSQL est éteinte lors du scan
        topology["PGDATA"] = "/var/lib/postgresql/18/data"
        topology["postgresql.conf"] = "/var/lib/postgresql/18/data/postgresql.conf"
        topology["pg_hba.conf"] = "/var/lib/postgresql/18/data/pg_hba.conf"
    return topology


def scan_binaries(tools_set):
    """
    Scanne les répertoires standards Linux pour trouver les chemins absolus.
    Gère nativement les arborescences Debian/Ubuntu et RHEL/Rocky/AlmaLinux.
    """
    SEARCH_PATHS = [
        "/usr/lib/postgresql/*/bin",  # Standard Debian / Ubuntu
        "/usr/pgsql-*/bin",            # Standard RHEL / Rocky / Alma
        "/usr/bin",                    # Binaires système standards
        "/usr/local/bin",              # Binaires locaux / custom
        "/bin"                         # Compatibilité chemins legacy
    ]
    found = {}
    
    for pattern in SEARCH_PATHS:
        for folder in glob.glob(pattern):
            if not os.path.isdir(folder): 
                continue
            for tool in tools_set:
                full_path = os.path.join(folder, tool)
                # Vérification de l'existence, du type fichier et des droits d'exécution
                if os.path.exists(full_path) and os.path.isfile(full_path) and os.access(full_path, os.X_OK):
                    # Règle de priorité : On favorise le binaire spécifique à PostgreSQL (/postgresql/ ou /pgsql/)
                    if tool not in found or "postgresql" in full_path or "pgsql" in full_path:
                        found[tool] = full_path
    return found


def main():
    print("🔍 [DISCOVERY] Début de la cartographie tripartie du serveur...")
    
    # 1. Collecte de la topologie de la base de données
    topology = get_pg_topology()
    
    # 2. Collecte des exécutables PostgreSQL autorisés
    pg_bins = scan_binaries(POSTGRES_TOOLS)
    
    # 3. Collecte des exécutables Système autorisés
    sys_bins = scan_binaries(SYSTEM_TOOLS)
    
    # Construction du registre final structuré pour le contexte du LLM 14B
    registry = {
        "last_scan": datetime.now().isoformat(),
        "postgresql_topology": topology,
        "postgresql_binaries": pg_bins,
        "system_binaries": sys_bins
    }
    
    # Écriture propre du fichier de registre JSON
    base_dir = os.path.dirname(os.path.abspath(__file__))
    output_path = os.path.join(base_dir, "discovery.json")
    
    try:
        with open(output_path, "w") as f:
            json.dump(registry, f, indent=2)
        print(f"✅ Registre DBA généré avec succès dans : {output_path}")
        
        # Petit récapitulatif visuel dans la console
        print(f"   ∟ Fichiers de conf  : {len([k for k,v in topology.items() if v])} détecté(s)")
        print(f"   ∟ Outils Postgres   : {len(pg_bins)} / {len(POSTGRES_TOOLS)} trouvé(s)")
        print(f"   ∟ Outils Système    : {len(sys_bins)} / {len(SYSTEM_TOOLS)} trouvé(s)")
    except Exception as e:
        print(f"❌ Erreur critique lors de l'écriture du registre JSON : {e}")


if __name__ == "__main__":
    main()
