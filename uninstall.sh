#!/bin/bash

echo "=== PostgreSQL AI Agent - Désinstallation ==="

if [ "$EUID" -ne 0 ]; then
  echo "Erreur : ce script doit être exécuté en root."
  exit 1
fi

echo "[1/4] Arrêt du service..."
systemctl stop pgagent 2>/dev/null

echo "[2/4] Suppression du service systemd..."
systemctl disable pgagent 2>/dev/null
rm -f /etc/systemd/system/pgagent.service
systemctl daemon-reload

echo "[3/4] Suppression des fichiers de l'agent..."
rm -rf /opt/pgagent

echo "[4/4] (Optionnel) Suppression des règles UFW..."
ufw delete allow pgagent 2>/dev/null

echo ""
echo "Désinstallation terminée."

