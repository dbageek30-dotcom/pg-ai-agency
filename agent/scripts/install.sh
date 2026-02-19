#!/bin/bash
# ==============================================================
#      PostgreSQL AI Agent - Installateur Officiel v1.2.1
# ==============================================================

if [ "$EUID" -ne 0 ]; then
  echo "❌ Erreur : ce script doit être exécuté en root (sudo)."
  exit 1
fi

# 1. Détection des chemins (robuste quel que soit le dossier d'exécution)
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
# On considère que le dossier 'agent/' est le parent du dossier 'scripts/'
AGENT_SRC_DIR="$(dirname "$SCRIPT_DIR")"

echo "📂 Source détectée : $AGENT_SRC_DIR"

# 2. Questionnaire
echo "--- Configuration ---"
read -p "Port d'écoute [5050] : " AGENT_PORT
AGENT_PORT=${AGENT_PORT:-5050}

read -p "Token d'authentification (obligatoire) : " AGENT_TOKEN
if [ -z "$AGENT_TOKEN" ]; then
    echo "❌ Erreur : Le token est obligatoire pour la sécurité."
    exit 1
fi

read -p "IP autorisée (Agency) : " ALLOWED_IP
if [ -z "$ALLOWED_IP" ]; then
    echo "❌ Erreur : L'IP de l'agence est requise pour le firewall."
    exit 1
fi

# [1/6] Dépendances et Utilisateur
echo "📦 [1/6] Installation des paquets système..."
apt update -q && apt install -y python3 python3-pip python3-venv ufw bubblewrap unzip

if ! id "pgagent" &>/dev/null; then
    echo "👤 Création de l'utilisateur système pgagent..."
    useradd --system --home-dir /opt/pgagent --shell /bin/false pgagent
    usermod -aG postgres pgagent
fi

# [2/6] Structure des dossiers
echo "📂 [2/6] Préparation de /opt/pgagent..."
# On nettoie l'ancien code s'il existe mais on garde runtime/ (données persistantes)
mkdir -p /opt/pgagent/{bin,runtime,logs,config}
rm -rf /opt/pgagent/bin/*

# Copie du code source
cp -r "$AGENT_SRC_DIR"/* /opt/pgagent/bin/

# [3/6] Environnement Virtuel Python
echo "🐍 [3/6] Configuration du Virtualenv..."
python3 -m venv /opt/pgagent/venv
/opt/pgagent/venv/bin/pip install --upgrade pip -q
if [ -f "/opt/pgagent/bin/requirements.txt" ]; then
    /opt/pgagent/venv/bin/pip install -r /opt/pgagent/bin/requirements.txt -q
fi

# [4/6] Initialisation Config et Registry
echo "⚙️ [4/6] Initialisation des composants..."
# Config via template
if [ -f "/opt/pgagent/bin/config.json.template" ]; then
    sed "s/__PORT__/$AGENT_PORT/g" /opt/pgagent/bin/config.json.template > /opt/pgagent/config/config.json
fi

# Copie de la allowlist par défaut si absente
if [ ! -f "/opt/pgagent/config/allowed_tools.json" ]; then
    cp /opt/pgagent/bin/security/allowed_tools.json /opt/pgagent/config/ 2>/dev/null || true
fi

# Scan des binaires (Registry)
export PYTHONPATH=/opt/pgagent/bin
/opt/pgagent/venv/bin/python3 /opt/pgagent/bin/runtime/discovery.py > /dev/null

# [5/6] Permissions et Bubblewrap
echo "🔐 [5/6] Sécurisation (SUID & Permissions)..."
# Indispensable pour que pgagent puisse lancer bubblewrap
chmod u+s /usr/bin/bwrap

# Permissions fichiers
chown -R root:root /opt/pgagent/bin /opt/pgagent/venv
chown -R pgagent:pgagent /opt/pgagent/runtime /opt/pgagent/logs /opt/pgagent/config
chmod -R 770 /opt/pgagent/runtime /opt/pgagent/logs

# [6/6] Service Systemd et Firewall
echo "🚀 [6/6] Activation du service..."
cat /opt/pgagent/bin/pgagent.service.template \
  | sed "s/__TOKEN__/$AGENT_TOKEN/g" \
  | sed "s/__PORT__/$AGENT_PORT/g" \
  > /etc/systemd/system/pgagent.service

systemctl daemon-reload
systemctl enable pgagent --now

# Firewall
ufw allow from "$ALLOWED_IP" to any port "$AGENT_PORT" comment 'PG-AI-AGENT'

echo "=============================================="
echo " ✅ Installation v1.2.1 terminée avec succès !"
echo "=============================================="
systemctl status pgagent --no-pager
