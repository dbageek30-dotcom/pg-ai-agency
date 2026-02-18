#!/bin/bash
echo "=== PostgreSQL AI Agent - Mise à jour ==="

if [ "$EUID" -ne 0 ]; then echo "Erreur : Root requis."; exit 1; fi

VERSION="$1"
[ -z "$VERSION" ] && echo "Usage : ./update.sh <version>" && exit 1

GITHUB_REPO="https://github.com/cheickna/pg-ai-agency"
ZIP="pgagent-$VERSION.zip"
URL="$GITHUB_REPO/releases/download/v$VERSION/$ZIP"

echo "[1/4] Téléchargement de la version $VERSION..."
wget -q "$URL" -O "/tmp/$ZIP" || { echo "Erreur de téléchargement"; exit 1; }

echo "[2/4] Extraction et mise à jour du code..."
mkdir -p /tmp/pgagent-update
unzip -q "/tmp/$ZIP" -d /tmp/pgagent-update

# Mise à jour du dossier bin uniquement
rm -rf /opt/pgagent/bin
cp -r /tmp/pgagent-update/agent /opt/pgagent/bin
chown -R root:root /opt/pgagent/bin

# Mise à jour des dépendances si nécessaire
/opt/pgagent/venv/bin/pip install -r /opt/pgagent/bin/requirements.txt

echo "[3/4] Refresh du Registry..."
export PYTHONPATH=$PYTHONPATH:/opt/pgagent/bin
/opt/pgagent/venv/bin/python3 -m runtime.discovery

echo "[4/4] Redémarrage du service..."
systemctl restart pgagent

rm -rf /tmp/pgagent-update "/tmp/$ZIP"
echo "✅ Mise à jour vers $VERSION terminée."
