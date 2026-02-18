#!/bin/bash

echo "=== PostgreSQL AI Agent - Mise à jour ==="

if [ "$EUID" -ne 0 ]; then
  echo "Erreur : ce script doit être exécuté en root."
  exit 1
fi

GITHUB_REPO="https://github.com/cheickna/pg-ai-agency"
VERSION="$1"

if [ -z "$VERSION" ]; then
  echo "Usage : ./update.sh <version>"
  echo "Exemple : ./update.sh 1.1.0"
  exit 1
fi

ZIP="pgagent-$VERSION.zip"
URL="$GITHUB_REPO/releases/download/v$VERSION/$ZIP"

echo "[1/5] Téléchargement de la release $VERSION..."
wget -q "$URL" -O "/tmp/$ZIP"

if [ $? -ne 0 ]; then
  echo "Erreur : impossible de télécharger $URL"
  exit 1
fi

echo "[2/5] Extraction..."
rm -rf /tmp/pgagent-update
mkdir /tmp/pgagent-update
unzip -q "/tmp/$ZIP" -d /tmp/pgagent-update

echo "[3/5] Mise à jour des fichiers..."
rm -rf /opt/pgagent
cp -r /tmp/pgagent-update/agent /opt/pgagent

echo "[4/5] Redémarrage du service..."
systemctl restart pgagent

echo "[5/5] Nettoyage..."
rm -rf /tmp/pgagent-update
rm -f "/tmp/$ZIP"

echo ""
echo "Mise à jour vers la version $VERSION terminée."

