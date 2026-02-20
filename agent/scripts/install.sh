#!/bin/bash
# ==============================================================
#      PostgreSQL AI Agent - Installateur Officiel v1.2.1
# ==============================================================

if [ "$EUID" -ne 0 ]; then
  echo "❌ Erreur : ce script doit être exécuté en root (sudo)."
  exit 1
fi

# 1. Détection des chemins
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
AGENT_SRC_DIR="$(dirname "$SCRIPT_DIR")"

echo "📂 Source détectée : $AGENT_SRC_DIR"

# 2. Questionnaire
echo "--- Configuration ---"
read -p "Port d'écoute [5050] : " AGENT_PORT
AGENT_PORT=${AGENT_PORT:-5050}

read -p "Token d'authentification (obligatoire) : " AGENT_TOKEN
if [ -z "$AGENT_TOKEN" ]; then
    echo "❌ Erreur : Le token est obligatoire."
    exit 1
fi

read -p "IP autorisée (Agency) : " ALLOWED_IP
if [ -z "$ALLOWED_IP" ]; then
    echo "❌ Erreur : L'IP de l'agence est requise."
    exit 1
fi

# [1/6] Dépendances
echo "📦 [1/6] Installation des paquets système..."
apt update -q && apt install -y python3 python3-pip python3-venv ufw bubblewrap unzip jq

if ! id "pgagent" &>/dev/null; then
    echo "👤 Création de l'utilisateur système pgagent..."
    useradd --system --home-dir /opt/pgagent --shell /bin/false pgagent
    usermod -aG postgres pgagent
fi

# [2/6] Structure
echo "📂 [2/6] Préparation de /opt/pgagent..."
mkdir -p /opt/pgagent/{bin,runtime,logs,config}
rm -rf /opt/pgagent/bin/*

cp -r "$AGENT_SRC_DIR"/* /opt/pgagent/bin/

# [3/6] Virtualenv
echo "🐍 [3/6] Configuration du Virtualenv..."
python3 -m venv /opt/pgagent/venv
/opt/pgagent/venv/bin/pip install --upgrade pip -q
if [ -f "/opt/pgagent/bin/requirements.txt" ]; then
    /opt/pgagent/venv/bin/pip install -r /opt/pgagent/bin/requirements.txt -q
fi

# [4/6] Config + LLM
echo "⚙️ [4/6] Initialisation de la configuration..."

sed "s/__PORT__/$AGENT_PORT/g" /opt/pgagent/bin/config.json.template \
  | sed "s/__TOKEN__/$AGENT_TOKEN/g" \
  > /opt/pgagent/config/config.json

echo ""
echo "=== Choix du LLM ==="
echo "1) Ollama (local)"
echo "2) OpenAI"
echo "3) Azure OpenAI"
echo "4) LM Studio"
echo "5) Mock (tests)"
read -p "Votre choix [1] : " LLM_CHOICE
LLM_CHOICE=${LLM_CHOICE:-1}

case $LLM_CHOICE in
  1)
    echo "→ Configuration Ollama"
    jq '.llm.provider="ollama" | .llm.model="llama3.1" | .llm.url="http://localhost:11434"' \
      /opt/pgagent/config/config.json > /tmp/config.json
    ;;
  2)
    echo "→ Configuration OpenAI"
    read -p "Clé API OpenAI : " OPENAI_KEY
    jq --arg key "$OPENAI_KEY" '.llm.provider="openai" | .llm.model="gpt-4o-mini" | .llm.api_key=$key' \
      /opt/pgagent/config/config.json > /tmp/config.json
    ;;
  3)
    echo "→ Configuration Azure OpenAI"
    read -p "Endpoint Azure : " AZ_ENDPOINT
    read -p "Deployment : " AZ_DEPLOY
    read -p "Clé API Azure : " AZ_KEY
    jq --arg ep "$AZ_ENDPOINT" --arg dep "$AZ_DEPLOY" --arg key "$AZ_KEY" \
      '.llm.provider="azure" | .llm.endpoint=$ep | .llm.deployment=$dep | .llm.api_key=$key' \
      /opt/pgagent/config/config.json > /tmp/config.json
    ;;
  4)
    echo "→ Configuration LM Studio"
    jq '.llm.provider="lmstudio" | .llm.url="http://localhost:1234" | .llm.model="llama3.1"' \
      /opt/pgagent/config/config.json > /tmp/config.json
    ;;
  5)
    echo "→ Mode Mock (tests)"
    jq '.llm.provider="mock"' /opt/pgagent/config/config.json > /tmp/config.json
    ;;
  *)
    echo "→ Choix invalide, Ollama par défaut"
    jq '.llm.provider="ollama" | .llm.model="llama3.1" | .llm.url="http://localhost:11434"' \
      /opt/pgagent/config/config.json > /tmp/config.json
    ;;
esac

mv /tmp/config.json /opt/pgagent/config/config.json

# [5/6] Permissions
echo "🔐 [5/6] Permissions..."
chmod u+s /usr/bin/bwrap

chown -R root:root /opt/pgagent/bin /opt/pgagent/venv
chown -R pgagent:pgagent /opt/pgagent/runtime /opt/pgagent/logs /opt/pgagent/config
chmod -R 770 /opt/pgagent/runtime /opt/pgagent/logs

# [6/6] Service + Firewall
echo "🚀 [6/6] Activation du service..."
cat /opt/pgagent/bin/pgagent.service.template \
  | sed "s/__TOKEN__/$AGENT_TOKEN/g" \
  | sed "s/__PORT__/$AGENT_PORT/g" \
  > /etc/systemd/system/pgagent.service

systemctl daemon-reload
systemctl enable pgagent --now

ufw allow from "$ALLOWED_IP" to any port "$AGENT_PORT" comment 'PG-AI-AGENT'

echo "=============================================="
echo " ✅ Installation v1.2.1 terminée avec succès !"
echo "=============================================="
systemctl status pgagent --no-pager

