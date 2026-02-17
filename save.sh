#!/bin/bash

# Navigate to the project directory (optional but safer)
cd ~/pg-ai-agency

# Add all changes (except those in .gitignore)
git add .

# Create a commit message with the current date and time
timestamp=$(date "+%Y-%m-%d %H:%M:%S")
commit_message="Auto-save: $timestamp"

# Commit the changes
git commit -m "$commit_message"

# Push to GitHub
git push origin main

echo "---------------------------------------"
echo "Project successfully backed up to GitHub!"
echo "---------------------------------------"
