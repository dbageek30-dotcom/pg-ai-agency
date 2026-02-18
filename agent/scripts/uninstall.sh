#!/bin/bash
echo "=== PostgreSQL AI Agent - Désinstallation ==="

if [ "$EUID" -ne 0 ]; then echo "Erreur : Root requis."; exit 1; fi

echo "[1/3] Arrêt et suppression du service..."
systemctl stop pgagent 2>/dev/null
systemctl disable pgagent 2>/dev/null
rm -f /etc/systemd/system/pgagent.service
systemctl daemon-reload

echo "[2/3] Gestion des fichiers et de l'utilisateur..."
read -p "Voulez-vous supprimer TOUTES les données (audit, logs, config) ? (y/N) " DEL_ALL

if [[ "$DEL_ALL" =~ ^[Yy]$ ]]; then
    rm -rf /opt/pgagent
    userdel pgagent 2>/dev/null
    echo "Fichiers et utilisateur pgagent supprimés."
else
    # On ne supprime que l'exécutable et le venv
    rm -rf /opt/pgagent/bin /opt/pgagent/venv
    echo "Code supprimé. Données conservées dans /opt/pgagent/{runtime,logs,config}."
fi

echo "[3/3] Nettoyage Firewall (optionnel)..."
# On ne désactive pas UFW, on retire juste la règle si possible
# ufw delete allow from ... (nécessite l'IP exacte, plus simple manuellement)

echo "Désinstallation terminée."
