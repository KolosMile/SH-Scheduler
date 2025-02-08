#!/bin/bash

echo "Pushing JSON file to GitHub..."
git add missed_streak.json
git commit -m "Auto-update missed_streak.json from server"
git push origin main

echo "Pulling latest code from GitHub..."
git pull origin main

echo "Sync completed successfully!"
