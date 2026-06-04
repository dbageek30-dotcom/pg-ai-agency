#!/bin/bash

# ==============================================================
#      PostgreSQL AI Agent - Installateur Officiel v1.8.0
#      Focus: Intelligent Auto-Discovery & Sudoers Security
#      Target: FastAPI + Uvicorn Implementation
# ==============================================================

set -euo pipefail

# --- Options & Debug ---
VERBOSE=0
DEBUG=0
while getopts "vV" opt; do
  case $opt in
    v) VERBOSE=1 ;;
    V) DEBUG=1 ;;
  esac
done
[ "$DEBUG" -eq 1 ] && set -x

# --- Couleurs & Logging ---
BLUE="\e[34m" ; GREEN="\e[32m" ; YELLOW="\e[33m" ; RED="\e[31m" ; RESET="\e[0m"
LOG_DIR="/opt/pgagent/logs" ; LOG_FILE="$LOG_DIR/install.log"

log() { echo -e "${BLUE}[$(date '+%Y-%m-%d %H:%M:%S')]${RESET} $*" | tee -a "$LOG_FILE"; }

# --- Check Root ---
[ "$EUID" -ne 0 ] && echo -e "${RED}❌ Root requis. Relancez avec sudo.${RESET}" && exit 1

# --- [0/7] Nettoyage Pré-installation ---
if [ -d "/opt/pgagent" ]; then
    echo -e "${YELLOW}⚠️ Installation existante détectée dans /opt/pgagent.${RESET}"
    read -p "Voulez-vous écraser l'installation ? (o/N) : " CONFIRM
    if [[ "$CONFIRM" =~ ^[oO]$ ]]; then
        log "🧹 Nettoyage de l'ancienne installation..."
        systemctl stop pgagent 2>/dev/null || true
        rm -rf /opt/pgagent
    else
        log "Arrêt de l'installation."
        exit 0
    fi
fi

mkdir -p "$LOG_DIR" && touch "$LOG_FILE"
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
AGENT_SRC_DIR="$(dirname "$SCRIPT_DIR")"

# --- Configuration Interactive ---
echo -e "${BLUE}--- Configuration de l'Agent ---${RESET}"
read -p "Port d'écoute [8432] : " INPUT_PORT ; AGENT_PORT=${INPUT_PORT:-8432}
read -p "Token d'authentification (ex: 123) : " AGENT_TOKEN
read -p "IP de l'Agency (vm-ai-agency) [10.198.0.2] : " ALLOWED_IP ; ALLOWED_IP=${ALLOWED_IP:-10.198.0.2}

echo -e "\n${BLUE}--- Configuration de l'Orchestrateur Distant ---${RESET}"
read -p "IP du serveur Ollama [10.198.0.4] : " INPUT_OLLAMA_HOST ; OLLAMA_HOST=${INPUT_OLLAMA_HOST:-10.198.0.4}
read -p "Modèle de l'Orchestrateur [qwen2.5:14b-instruct] : " INPUT_ORCH_MODEL ; ORCH_MODEL=${INPUT_ORCH_MODEL:-qwen2.5:14b-instruct}

# --- [1/7] Dépendances & Utilisateur ---
log "📦 [1/7] Installation des dépendances système..."
apt update -qq >>"$LOG_FILE" 2>&1
apt install -y -qq python3 python3-pip python3-venv ufw rsync jq curl libpq-dev python3-dev build-essential >>"$LOG_FILE" 2>&1

if ! id "pgagent" &>/dev/null; then
    log "👤 Création de l'utilisateur système pgagent..."
    useradd --system --home-dir /opt/pgagent --shell /bin/false --no-create-home pgagent
fi
usermod -aG postgres pgagent

# --- [2/7] Structure & Code ---
log "📂 [2/7] Déploiement de la structure de fichiers..."
mkdir -p /opt/pgagent/{bin,logs,config}
mkdir -p /opt/pgagent/bin/security

rsync -av \
    --exclude='.git' \
    --exclude='.venv' \
    --exclude='__pycache__' \
    --exclude='discovery.json' \
    "$AGENT_SRC_DIR"/ /opt/pgagent/bin/ >>"$LOG_FILE" 2>&1

# --- [3/7] Python Environment ---
log "🐍 [3/7] Création du Virtualenv & Packages..."
python3 -m venv /opt/pgagent/venv >>"$LOG_FILE" 2>&1
/opt/pgagent/venv/bin/pip install --upgrade pip -q
/opt/pgagent/venv/bin/pip install requests fastapi uvicorn psycopg2-binary pydantic -q

# --- [4/7] PostgreSQL Cross-Check Discovery & Permissions ---
log "🔍 [4/7] Cross-Check : Localisation du cluster PostgreSQL actif..."

# Extraction du dossier de données (-D) depuis le processus en cours d'exécution
PG_PROCESS_DATA_DIR=$(ps -ef | grep "[p]ostgres" | grep "\-D" | awk -F '-D ' '{print $2}' | awk '{print $1}' || echo "")
PG_PROCESS_DATA_DIR="${PG_PROCESS_DATA_DIR%/}"

if [ -n "$PG_PROCESS_DATA_DIR" ]; then
    log "🐘 Cluster actif identifié dans : $PG_PROCESS_DATA_DIR"
    # Filtrage du find pour cibler la bonne instance active
    PG_CONF_FILE=$(find / -type f -name "postgresql.conf" 2>/dev/null | grep "$PG_PROCESS_DATA_DIR" | head -n 1 || echo "")
    PG_HBA_FILE=$(find / -type f -name "pg_hba.conf" 2>/dev/null | grep "$PG_PROCESS_DATA_DIR" | head -n 1 || echo "")
else
    log "⚠️ Aucun processus Postgres actif avec flag -D trouvé. Repli sur le find global..."
    PG_CONF_FILE=$(find /etc /var /lib/postgresql -type f -name "postgresql.conf" 2>/dev/null | head -n 1 || echo "")
    PG_HBA_FILE=$(find /etc /var /lib/postgresql -type f -name "pg_hba.conf" 2>/dev/null | head -n 1 || echo "")
fi

if [ -z "$PG_CONF_FILE" ] || [ -z "$PG_HBA_FILE" ]; then
    log "${RED}❌ Erreur critique : Fichiers de configuration PostgreSQL introuvables.${RESET}"
    exit 1
fi

log "🎯 Configuration ciblée : $PG_CONF_FILE"
log "🎯 Authentification ciblée : $PG_HBA_FILE"

# --- Configuration des privilèges SQL Rôles ---
echo -e "\n${YELLOW}Choisissez le profil de privilèges SQL pour le rôle 'pgagent' :${RESET}"
echo "1) 👤 Monitor  (SQL: pg_monitor, pg_signal_backend | Recommandé)"
echo "2) 🛠 Admin    (SQL: Createdb + Monitor)"
echo "3) ⚡ Superuser(SQL: Superuser | Prudence !)"
read -p "Niveau [1, 2 ou 3] (défaut 1) : " PRIV_LEVEL
PRIV_LEVEL=${PRIV_LEVEL:-1}

read -s -p "Définissez le mot de passe PostgreSQL pour le rôle 'pgagent' : " AGENT_DB_PASSWORD ; echo ""

# Injection du rôle PostgreSQL en passant par l'utilisateur système local postgres
sudo -u postgres psql -c "DO \$\$ 
BEGIN 
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'pgagent') THEN 
    CREATE ROLE pgagent WITH LOGIN PASSWORD '$AGENT_DB_PASSWORD'; 
  ELSE 
    ALTER ROLE pgagent WITH PASSWORD '$AGENT_DB_PASSWORD' LOGIN; 
  END IF; 
END \$\$;" >>"$LOG_FILE" 2>&1

case $PRIV_LEVEL in
    2)
        sudo -u postgres psql -c "ALTER ROLE pgagent CREATEDB; GRANT pg_monitor TO pgagent;" >>"$LOG_FILE" 2>&1
        ;;
    3)
        sudo -u postgres psql -c "ALTER ROLE pgagent SUPERUSER;" >>"$LOG_FILE" 2>&1
        ;;
    *)
        sudo -u postgres psql -c "GRANT pg_monitor TO pgagent;" >>"$LOG_FILE" 2>&1
        ;;
esac
sudo -u postgres psql -c "GRANT pg_signal_backend TO pgagent;" >>"$LOG_FILE" 2>&1

# Création du fichier d'authentification natif pour l'agent
echo "localhost:*:*:pgagent:${AGENT_DB_PASSWORD}" > /opt/pgagent/.pgpass
chmod 600 /opt/pgagent/.pgpass
chown pgagent:pgagent /opt/pgagent/.pgpass

# --- [5/7] Configuration .env ---
log "⚙️ [5/7] Génération du fichier d'environnement..."
cat <<EOF > /opt/pgagent/config/.env
REMOTE_AGENT_TOKEN=$AGENT_TOKEN
OLLAMA_HOST=http://$OLLAMA_HOST:11434
ORCHESTRATOR_MODEL=$ORCH_MODEL
PG_USER=pgagent
PG_PASS=$AGENT_DB_PASSWORD
PG_HOST=localhost
PG_DB=postgres
PG_CONF_PATH=$PG_CONF_FILE
PG_HBA_PATH=$PG_HBA_FILE
EOF
chown pgagent:pgagent /opt/pgagent/config/.env
chmod 600 /opt/pgagent/config/.env

# --- [6/7] Configuration Sudoers & Permissions Fichiers ---
log "🔐 [6/7] Sécurisation et écriture des règles Sudoers..."

# Initialisation de la whitelist par défaut si absente
if [ ! -f /opt/pgagent/bin/security/allowed_tools.json ]; then
    echo '{"allowed_commands": ["df -h", "free -m", "uptime", "pg_ctl status"]}' > /opt/pgagent/bin/security/allowed_tools.json
fi

# Application de la règle Sudoers chirurgicale basée sur les chemins découverts
cat <<EOF > /etc/sudoers.d/pgagent
# Droits restreints pour l'agent : modification des deux fichiers cibles et rechargement
pgagent ALL=(ALL) NOPASSWD: /usr/bin/tee -a $PG_CONF_FILE
pgagent ALL=(ALL) NOPASSWD: /usr/bin/tee -a $PG_HBA_FILE
pgagent ALL=(postgres) NOPASSWD: /usr/bin/pg_ctl reload
EOF
chmod 440 /etc/sudoers.d/pgagent

# Verrouillage du code source appartenant à root (Anti-tampering)
chown -R root:root /opt/pgagent/bin
chown -R pgagent:pgagent /opt/pgagent/logs /opt/pgagent/config
chmod 755 /opt/pgagent
chmod -R 750 /opt/pgagent/bin/security

# Exécution du discovery.py sous l'identité pgagent
chown pgagent:pgagent /opt/pgagent/bin
sudo -u pgagent HOME=/opt/pgagent /opt/pgagent/venv/bin/python3 /opt/pgagent/bin/discovery.py >>"$LOG_FILE" 2>&1 || log "${YELLOW}⚠️ Note: discovery.py s'est exécuté avec des avertissements.${RESET}"
chown root:root /opt/pgagent/bin

# --- [7/7] Systemd Service ---
log "🚀 [7/7] Déploiement et activation du service Systemd..."
cat <<EOF > /etc/systemd/system/pgagent.service
[Unit]
Description=PostgreSQL AI Remote Agent (pgagent)
After=network.target postgresql.service

[Service]
User=pgagent
Group=pgagent
WorkingDirectory=/opt/pgagent/bin
EnvironmentFile=/opt/pgagent/config/.env
Environment=HOME=/opt/pgagent
Environment=PGPASSFILE=/opt/pgagent/.pgpass
ExecStart=/opt/pgagent/venv/bin/python3 -m uvicorn server:app --host 0.0.0.0 --port $AGENT_PORT
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable pgagent --now

if command -v ufw >/dev/null; then
    log "🧱 Configuration UFW : Ouverture du port $AGENT_PORT pour l'Agency ($ALLOWED_IP)"
    ufw allow from "$ALLOWED_IP" to any port "$AGENT_PORT" comment "PG-Agent-Agency" >>"$LOG_FILE" 2>&1 || true
fi

log "=========================================================================="
log "${GREEN}✔ Installation v1.8.0 Réussie !${RESET}"
log "  -> Fichiers PG sécurisés détectés et configurés dans Sudoers."
log "  -> Statut de l'agent :  systemctl status pgagent"
log "=========================================================================="
