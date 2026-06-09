#!/usr/bin/env bash

# ==============================================================================
# SCRIPT D'INSTALLATION AUTOMATIQUE DU SERVICE PGAGENT (TRIPARTIE & FASTAPI)
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
trap 'failure_handler $LINENO' ERR

# Configuration des variables locales
TARGET_DIR="/opt/pgagent"
LOG_DIR="/var/log/pgagent"
DB_USER="pgagent"
DB_PASS="ChAnGeMe_PlEaSe_DeV_2026"  
SECRET_TOKEN="123" # Ton Token d'authentification validé

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
PG_DATA=$(sudo -u postgres psql -t -A -c "SHOW data_directory;")
PG_HBA=$(sudo -u postgres psql -t -A -c "SHOW hba_file;")

echo "   -> Dossier Data détecté : ${PG_DATA}"
echo "   -> Fichier pg_hba.conf trouvé : ${PG_HBA}"

# 3. Création de l'arborescence /opt/pgagent et des LOGS
echo "📁 Création des répertoires système..."
mkdir -p "${TARGET_DIR}/bin"
mkdir -p "${LOG_DIR}"

# 4. Copie des fichiers applicatifs
echo "🚀 Déploiement du code source..."
cp server.py "${TARGET_DIR}/bin/"
cp discovery.py "${TARGET_DIR}/bin/"
cp allowed_tools.json "${TARGET_DIR}/bin/"  # <-- AJOUTE CETTE LIGNE

# Droits initiaux sur les fichiers
chown -R postgres:postgres "${TARGET_DIR}"
chown -R postgres:postgres "${LOG_DIR}"
chmod 750 "${LOG_DIR}"

# 5. Initialisation de l'environnement virtuel Python & Dépendances FastAPI
echo "🐍 Configuration de l'environnement virtuel Python..."
python3 -m venv "${TARGET_DIR}/.venv"
"${TARGET_DIR}/.venv/bin/pip" install --upgrade pip
"${TARGET_DIR}/.venv/bin/pip" install fastapi uvicorn psycopg2-binary

# 6. Exécution du premier scan de découverte (génère discovery.json)
echo "🔍 Exécution du scan initial de découverte du système..."
sudo -u postgres "${TARGET_DIR}/.venv/bin/python" "${TARGET_DIR}/bin/discovery.py"

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

# 9. Configuration des privilèges Sudoers pour l'administration totale
echo "🔑 Injection des règles Sudoers pour l'utilisateur postgres..."

# Extraction robuste des chemins absolus directement depuis le discovery.json généré
DISCO_FILE="${TARGET_DIR}/bin/discovery.json"

TEE_PATH=$(grep -o '"tee": "[^"]*"' "$DISCO_FILE" | cut -d'"' -f4)
SED_PATH=$(grep -o '"sed": "[^"]*"' "$DISCO_FILE" | cut -d'"' -f4)
PG_CTL_PATH=$(grep -o '"pg_ctl": "[^"]*"' "$DISCO_FILE" | cut -d'"' -f4)

# Sécurité : Si un chemin n'est pas trouvé, on applique un fallback standard
[ -z "$TEE_PATH" ] && TEE_PATH="/usr/bin/tee"
[ -z "$SED_PATH" ] && SED_PATH="/usr/bin/sed"
[ -z "$PG_CTL_PATH" ] && PG_CTL_PATH="/usr/bin/pg_ctl"

echo "   -> Autorisation Sudo pour tee    : ${TEE_PATH}"
echo "   -> Autorisation Sudo pour sed    : ${SED_PATH}"
echo "   -> Autorisation Sudo pour pg_ctl : ${PG_CTL_PATH}"

# Écriture propre du fichier sudoers dédié
cat <<EOF > /etc/sudoers.d/pgagent
postgres ALL=(ALL) NOPASSWD: ${TEE_PATH}, ${SED_PATH}, ${PG_CTL_PATH}
EOF
chmod 440 /etc/sudoers.d/pgagent

# 10. Création et activation du service Systemd avec injection d'environnement
echo "🛠️ Configuration du service système systemd (pgagent)..."
cat <<EOF > /etc/systemd/system/pgagent.service
[Unit]
Description=PG Agent System & SQL Daemon for AI Agency
After=network.target postgresql.service

[Service]
Type=simple
User=postgres
WorkingDirectory=${TARGET_DIR}
Environment="REMOTE_AGENT_TOKEN=${SECRET_TOKEN}"
Environment="PG_DB=postgres"
Environment="PG_USER=${DB_USER}"
Environment="PG_PASS=${DB_PASS}"
Environment="PG_HOST=localhost"
ExecStart=${TARGET_DIR}/.venv/bin/python -m uvicorn bin.server:app --host 0.0.0.0 --port 8432
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

# 11. Vérification finale du statut en fin de script
echo -e "\n================================================================="
echo "🟢 VÉRIFICATION DU STATUT DU SERVICE :"
echo "================================================================="
sleep 2 # Temps d'initialisation de uvicorn

if systemctl is-active --quiet pgagent; then
  echo -e "Statut : RUNNING 🟢"
  echo -e "\nDernières lignes de ton fichier de log (${LOG_DIR}/pgagent.log) :"
  echo "-----------------------------------------------------------------"
  tail -n 10 "${LOG_DIR}/pgagent.log"
  echo "-----------------------------------------------------------------"
  echo -e "\n✅ TOUT EST PARFAITEMENT CONFIGURÉ ET SAUVEGARDÉ !"
else
  echo -e "Statut : FAILED ❌ (Vérifie les logs système avec journalctl -u pgagent)"
  exit 1
fi
echo "================================================================="
