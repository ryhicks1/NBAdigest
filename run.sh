#!/bin/bash
# Run the NBA anomalies pipeline and push results
# Usage:
#   ./run.sh              Full run (ESPN stats + odds)
#   ./run.sh --odds-only  Odds-only refresh (reuse cached stats)

set -e
cd "$(dirname "$0")"

# Activate venv if it exists
if [ -d ".venv" ]; then
  source .venv/bin/activate
fi

# Run pipeline (pass through any flags like --odds-only)
python3 src/main.py "$@"

# Commit and push if data changed
git add data/anomalies.json
if ! git diff --staged --quiet; then
  git commit -m "Update anomalies digest $(date +%Y-%m-%d-%H%M)"
  git push
  echo "Data updated and pushed. Vercel will auto-deploy."
else
  echo "No data changes."
fi
