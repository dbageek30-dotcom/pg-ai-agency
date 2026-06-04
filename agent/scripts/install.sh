#!/bin/bash

# Verrouillage de sécurité : le script doit être exécuté en root
if [ "$EUID" -ne 0 ]; then
  echo "❌ [ERREUR] Ce script doit être exécuté en tant que root (sudo)."
  exit 1
fi

# Configuration des chemins fixes
AGENT_DIR="/root/agent"
VENV_DIR="/root/.agent_venv"
SERVICE_FILE="/etc/systemd/system/pgagent.service"
SECURITY_DIR="/opt/pgagent/bin/security"

echo "==========================================================================="
echo "⚙️  STARTING DEPLOYMENT: PostgreSQL 18 AI Remote Agent (pgagent)"
echo "==========================================================================="

# 1. Prérequis Système
echo "📦 [1/6] Vérification des paquets Python3 et Venv..."
apt-get update -y && apt-get install -y python3 python3-venv python3-pip python3-dev libpq-dev build-essential

# 2. Environnement Virtuel (Isolation)
if [ ! -d "$VENV_DIR" ]; then
    echo "🐍 [2/6] Création de l'environnement virtuel dans $VENV_DIR..."
    python3 -m venv "$VENV_DIR"
fi

# 3. Installation des Dépendances Python (FastAPI & Drivers)
echo "🚀 [3/6] Installation des packages requis dans le venv..."
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install fastapi uvicorn requests psycopg2-binary

# 4. Initialisation du Garde-Fou de Sécurité (Whitelist)
mkdir -p "$SECURITY_DIR"
if [ ! -f "$SECURITY_DIR/allowed_tools.json" ]; then
    echo "🔒 [4/6] Initialisation de la whitelist de sécurité..."
    echo '{"allowed_commands": ["df -h", "free -m", "uptime", "pg_ctl status"]}' > "$SECURITY_DIR/allowed_tools.json"
    chmod 644 "$SECURITY_DIR/allowed_tools.json"
fi

# 5. Création de la configuration Systemd
echo "🤖 [5/6] Écriture du fichier d'unité Systemd..."
cat <<EOF > "$SERVICE_FILE"
[Unit]
Description=PostgreSQL 18 AI Remote Agent (pgagent)
After=network.target postgresql.service

[Service]
Type=simple
User=root
WorkingDirectory=/root
Environment="REMOTE_AGENT_TOKEN=TOKEN_GENERE_A_LA_VOLEE_S1Cr1t"
# Uvicorn lance le fichier server.py (module 'agent.server' si exécuté depuis /root)
ExecStart=$VENV_DIR/bin/uvicorn agent.server:app --host 0.0.0.0 --port 8432
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# 6. Rechargement et Activation Globale
echo "🔄 [6/6] Rechargement de Systemd et démarrage de l'agent..."
systemctl daemon-reload
systemctl enable pgagent.service
systemctl restart pgagent.service

echo "==========================================================================="
echo "✅ DEPLOYMENT SUCCESSFUL!"
echo "   -> Statut :     systemctl status pgagent.service"
echo "   -> Whitelist :  vi $SECURITY_DIR/allowed_tools.json"
echo "==========================================================================="
