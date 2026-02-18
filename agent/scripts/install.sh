#!/bin/bash
echo "=============================================="
echo "      PostgreSQL AI Agent - Installateur"
echo "=============================================="

if [ "$EUID" -ne 0 ]; then
  echo "Erreur : ce script doit être exécuté en root."
  exit 1
fi

# --- Questionnaire ---
read -p "Port d'écoute de l'agent (5050 par défaut) : " AGENT_PORT
AGENT_PORT=${AGENT_PORT:-5050}
read -p "Token d'authentification (obligatoire) : " AGENT_TOKEN
[ -z "$AGENT_TOKEN" ] && echo "Erreur : Token obligatoire." && exit 1
read -p "IP autorisée (Agency) : " ALLOWED_IP
[ -z "$ALLOWED_IP" ] && echo "Erreur : IP obligatoire." && exit 1

# [1/6] Préparation Système & Utilisateur
echo "[1/6] Configuration de l'utilisateur pgagent..."
apt update -y && apt install -y python3 python3-pip python3-venv ufw bubblewrap unzip

if ! id "pgagent" &>/dev/null; then
    useradd --system --home-dir /opt/pgagent --shell /bin/false pgagent
    usermod -aG postgres pgagent
fi

# [2/6] Structure et Déploiement
echo "[2/6] Déploiement dans /opt/pgagent..."
mkdir -p /opt/pgagent/{bin,runtime,logs,config}

# Copie du code source vers le dossier bin
cp -r agent/* /opt/pgagent/bin/

# [3/6] Environnement Virtuel
echo "[3/6] Création du venv et installation des dépendances..."
python3 -m venv /opt/pgagent/venv
/opt/pgagent/venv/bin/pip install --upgrade pip
/opt/pgagent/venv/bin/pip install -r /opt/pgagent/bin/requirements.txt

# [4/6] Configuration et Registry
echo "[4/6] Initialisation de la configuration..."
cat /opt/pgagent/bin/config.json.template | sed "s/__PORT__/$AGENT_PORT/g" > /opt/pgagent/config/config.json

# Lancer le discovery pour peupler le registry avant le premier démarrage
export PYTHONPATH=$PYTHONPATH:/opt/pgagent/bin
/opt/pgagent/venv/bin/python3 -m runtime.discovery

# [5/6] Sécurité et Service Systemd
echo "[5/6] Configuration du service et des permissions..."
# Permissions : Le code appartient à root, seul l'utilisateur pgagent peut écrire dans runtime/logs
chown -R root:root /opt/pgagent/bin /opt/pgagent/venv
chown -R pgagent:pgagent /opt/pgagent/runtime /opt/pgagent/logs /opt/pgagent/config
chmod -R 770 /opt/pgagent/runtime /opt/pgagent/logs

# Création du service à partir du template
cat /opt/pgagent/bin/pgagent.service.template \
  | sed "s/__TOKEN__/$AGENT_TOKEN/g" \
  | sed "s/__PORT__/$AGENT_PORT/g" \
  > /etc/systemd/system/pgagent.service

systemctl daemon-reload
systemctl enable pgagent
systemctl restart pgagent

# [6/6] Firewall
echo "[6/6] Configuration UFW..."
ufw allow from $ALLOWED_IP to any port $AGENT_PORT comment 'Agent AI PG'
ufw --force enable

echo "=============================================="
echo " Installation terminée avec succès !"
echo " Utilisateur : pgagent (shell: /bin/false)"
echo " Service : systemctl status pgagent"
echo "=============================================="
