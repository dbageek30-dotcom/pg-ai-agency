#!/usr/bin/env bash

# ==============================================================================
# SCRIPT D'INSTALLATION AUTOMATIQUE DU SERVICE PGAGENT (VERSION SÉCURISÉE & LOGS)
# ==============================================================================

set -e # Arrête le script en cas d'erreur

# --- GESTION DES ERREURS AMÉLIORÉE ---
failure_handler() {
  local exit_code=$?
  local line_number=$1
  echo -e "\n================================================================="
  echo "❌ [ERREUR] L'installation a échoué à la ligne ${line_number} !"
  echo "   -> Code de retour de la dernière commande : ${exit_code}"
  echo "================================================================="
  exit "${exit_code}"
}
# Déclenche la fonction failure_handler en lui passant le numéro de ligne ($LINENO)
trap 'failure_handler $LINENO' ERR

# Configuration des variables locales
TARGET_DIR="/opt/pgagent"
LOG_DIR="/var/log/pgagent"
DB_USER="pgagent"
DB_PASS="ChAnGeMe_PlEaSe_DeV_2026"  
SECRET_TOKEN="TOKEN_GENERE_A_LA_VOLEE_S1Cr1t" 

echo "================================================================="
echo "🐘 Installation et configuration du service pgagent"
echo "================================================================="

# 1. Vérification des privilèges
if [ "$EUID" -ne 0 ]; then
  echo "❌ Ce script doit être exécuté en tant que root (sudo ./install.sh)"
  exit 1
fi

# 2. Détection dynamique de l'environnement PostgreSQL local
echo "🔍 Détection de la configuration PostgreSQL..."
if ! command -v pg_config &> /dev/null; then
  echo "❌ PostgreSQL ne semble pas installé (pg_config introuvable)."
  exit 1
fi

PG_DATA=$(sudo -u postgres psql -t -A -c "SHOW data_directory;")
PG_HBA="${PG_DATA}/pg_hba.conf"

echo "   -> Dossier Data détecté : ${PG_DATA}"
echo "   -> Fichier pg_hba.conf trouvé : ${PG_HBA}"

# 3. Création de l'arborescence /opt/pgagent et des LOGS
echo "📁 Création des répertoires système..."
mkdir -p "${TARGET_DIR}/bin"
mkdir -p "${TARGET_DIR}/config"
mkdir -p "${LOG_DIR}"

# 4. Copie des fichiers applicatifs
echo "🚀 Déploiement du code source..."
cp server.py "${TARGET_DIR}/bin/"

# 5. Génération dynamique du fichier config.json
echo "⚙️ Génération du fichier de configuration sécurisé..."
cat <<EOF > "${TARGET_DIR}/config/config.json"
{
  "secret_token": "${SECRET_TOKEN}",
  "db_dsn": "dbname=postgres user=${DB_USER} password=${DB_PASS} host=localhost port=5432"
}
EOF

# Configuration stricte des droits
chmod 600 "${TARGET_DIR}/config/config.json"
chown -R postgres:postgres "${TARGET_DIR}"
chown -R postgres:postgres "${LOG_DIR}"
chmod 750 "${LOG_DIR}"

# 6. Initialisation de l'environnement virtuel Python
echo "🐍 Configuration de l'environnement virtuel Python..."
python3 -m venv "${TARGET_DIR}/.venv"
"${TARGET_DIR}/.venv/bin/pip" install --upgrade pip
"${TARGET_DIR}/.venv/bin/pip" install flask psycopg2-binary

# 7. Création de l'utilisateur PostgreSQL 'pgagent' (Niveau 1 : Monitoring)
echo "🐘 Configuration de l'utilisateur PostgreSQL '${DB_USER}'..."
sudo -u postgres psql -c "CREATE ROLE ${DB_USER} WITH LOGIN PASSWORD '${DB_PASS}';" || echo "   (Le rôle existe déjà, poursuite...)"
sudo -u postgres psql -c "GRANT pg_monitor TO ${DB_USER};"

# 8. Ajout de la règle de sécurité dans le pg_hba.conf
echo "🔐 Configuration des accès réseau (pg_hba.conf)..."
HBA_LINE="host    postgres        ${DB_USER}        127.0.0.1/32            scram-sha-256"

if grep -Fxq "${HBA_LINE}" "${PG_HBA}"; then
  echo "   -> La règle d'accès existe déjà dans le pg_hba.conf."
else
  sed -i "1i ${HBA_LINE}" "${PG_HBA}"
  echo "   -> Ligne ajoutée avec succès au pg_hba.conf."
  echo "🔄 Rechargement de la configuration PostgreSQL..."
  sudo -u postgres psql -c "SELECT pg_reload_conf();"
fi

# 9. Création et activation du service Systemd avec redirection des LOGS
echo "🛠️ Configuration du service système systemd (pgagent)..."
cat <<EOF > /etc/systemd/system/pgagent.service
[Unit]
Description=PG Agent System & SQL Daemon for AI Agency
After=network.target postgresql.service

[Service]
Type=simple
User=postgres
WorkingDirectory=${TARGET_DIR}
ExecStart=${TARGET_DIR}/.venv/bin/python ${TARGET_DIR}/bin/server.py
Restart=always
RestartSec=5
StandardOutput=append:${LOG_DIR}/pgagent.log
StandardError=append:${LOG_DIR}/pgagent.log
SyslogIdentifier=pgagent

[Install]
WantedBy=multi-user.target
EOF

# Prise en compte et démarrage par systemd
systemctl daemon-reload
systemctl enable pgagent
systemctl restart pgagent

# 10. Vérification finale du statut en fin de script
echo -e "\n================================================================="
echo "🟢 VÉRIFICATION DU STATUT DU SERVICE :"
echo "================================================================="
sleep 1.5 # Petit délai pour laisser à Flask le temps de bind le port

if systemctl is-active --quiet pgagent; then
  echo -e "Statut : RUNNING 🟢"
  echo -e "\nDernières lignes de ton fichier de log (${LOG_DIR}/pgagent.log) :"
  echo "-----------------------------------------------------------------"
  tail -n 5 "${LOG_DIR}/pgagent.log"
  echo "-----------------------------------------------------------------"
  echo -e "\n✅ INSTALLATION TERMINÉE AVEC SUCCÈS !"
else
  echo -e "Statut : FAILED ❌ (Vérifie les logs système)"
  exit 1
fi
echo "================================================================="
