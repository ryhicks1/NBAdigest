#!/bin/bash
# Run the NBA anomalies pipeline and push results
# Designed to be triggered by a scheduled task (cron/launchd/Claude Code)

set -e
cd "$(dirname "$0")"

# Activate venv
source .venv/bin/activate

# Export API key
export THE_ODDS_API_KEY="8c6f102e5a0cbe7d6862bc389f0accac"

# Run pipeline
python src/main.py

# Commit and push if data changed
git add data/anomalies.json
if ! git diff --staged --quiet; then
  git commit -m "Update anomalies digest $(date +%Y-%m-%d-%H%M)"
  git push
  echo "Data updated and pushed. Vercel will auto-deploy."
else
  echo "No data changes."
fi
