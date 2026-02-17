#!/bin/bash

echo "=============================================="
echo "     PostgreSQL AI Agent - Installateur"
echo "=============================================="
echo ""

# ------------------------------------------------------------
# Vérification des privilèges root
# ------------------------------------------------------------
if [ "$EUID" -ne 0 ]; then
  echo "Erreur : ce script doit être exécuté en root."
  exit 1
fi

# ------------------------------------------------------------
# Demander le port
# ------------------------------------------------------------
read -p "Port d'écoute de l'agent (5050 par défaut) : " AGENT_PORT
AGENT_PORT=${AGENT_PORT:-5050}

# ------------------------------------------------------------
# Demander le token
# ------------------------------------------------------------
read -p "Token d'authentification (obligatoire) : " AGENT_TOKEN
if [ -z "$AGENT_TOKEN" ]; then
  echo "Erreur : un token est obligatoire."
  exit 1
fi

# ------------------------------------------------------------
# Demander l'IP autorisée (celle de la VM-agency)
# ------------------------------------------------------------
read -p "IP autorisée à appeler l'agent (ex: 10.214.0.11) : " ALLOWED_IP
if [ -z "$ALLOWED_IP" ]; then
  echo "Erreur : une IP autorisée est obligatoire."
  exit 1
fi

echo ""
echo "Configuration choisie :"
echo " - Port : $AGENT_PORT"
echo " - Token : $AGENT_TOKEN"
echo " - IP autorisée : $ALLOWED_IP"
echo ""

# ------------------------------------------------------------
# Installation des dépendances Python
# ------------------------------------------------------------
echo "[1/6] Installation des dépendances Python..."
apt update -y
apt install -y python3 python3-pip ufw

pip3 install -r agent/requirements.txt

# ------------------------------------------------------------
# Déploiement dans /opt/pgagent
# ------------------------------------------------------------
echo "[2/6] Déploiement de l'agent dans /opt/pgagent..."

rm -rf /opt/pgagent
mkdir -p /opt/pgagent
cp agent/*.py /opt/pgagent/
cp agent/requirements.txt /opt/pgagent/

# ------------------------------------------------------------
# Génération du fichier config.json
# ------------------------------------------------------------
echo "[3/6] Génération de config.json..."

cat agent/config.json.template \
  | sed "s/__PORT__/$AGENT_PORT/g" \
  > /opt/pgagent/config.json

# ------------------------------------------------------------
# Génération du service systemd
# ------------------------------------------------------------
echo "[4/6] Installation du service systemd..."

SERVICE_FILE="/etc/systemd/system/pgagent.service"

cat agent/pgagent.service.template \
  | sed "s/__TOKEN__/$AGENT_TOKEN/g" \
  > $SERVICE_FILE

chmod 644 $SERVICE_FILE

systemctl daemon-reload
systemctl enable pgagent
systemctl restart pgagent

# ------------------------------------------------------------
# Configuration du firewall
# ------------------------------------------------------------
echo "[5/6] Configuration du firewall UFW..."

ufw allow ssh
ufw allow from $ALLOWED_IP to any port $AGENT_PORT
ufw deny $AGENT_PORT
ufw --force enable

# ------------------------------------------------------------
# Vérification finale
# ------------------------------------------------------------
echo "[6/6] Vérification du statut du service..."
systemctl status pgagent --no-pager

echo ""
echo "=============================================="
echo " Installation terminée avec succès !"
echo " L'agent écoute sur le port $AGENT_PORT"
echo " Accessible uniquement depuis : $ALLOWED_IP"
echo "=============================================="

