#!/bin/bash

# On s'assure qu'on est bien dans un dépôt Git
if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "❌ Erreur : Ce dossier n'est pas un dépôt Git."
    exit 1
fi

# Étape 1 : Ajouter toutes les modifications
echo "🔍 Analyse des modifications..."
git add .

# Vérifier s'il y a vraiment quelque chose à commit
if git diff-index --quiet HEAD --; then
    echo "⚪ Aucun changement détecté. Tout est déjà à jour !"
    exit 0
fi

# Étape 2 : Demander un message de commit à l'utilisateur
echo -n "📝 Entrez le message de commit [ou Entrée pour 'wip: update']: "
read commit_msg

# Si le message est vide, on met un message par défaut avec l'heure
if [ -z "$commit_msg" ]; then
    commit_msg="wip: update $(date '+%Y-%m-%d %H:%M')"
fi

# Étape 3 : Créer le commit
git commit -m "$commit_msg"

# Étape 4 : Pousser vers GitHub sur la branche actuelle
echo "🚀 Envoi des données vers GitHub..."
current_branch=$(git branch --show-current)
git push origin "$current_branch"

if [ $? -eq 0 ]; then
    echo "✅ Sauvegarde réussie sur GitHub (branche: $current_branch) !"
else
    echo "❌ Échec de l'envoi vers GitHub."
fi
