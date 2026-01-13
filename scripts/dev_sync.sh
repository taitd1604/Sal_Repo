#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo ">>> Syncing data/shifts.csv from GitHub..."
python "$REPO_ROOT/scripts/sync_data.py"

echo ">>> Generating data/shifts_public.csv..."
python "$REPO_ROOT/scripts/export_public_csv.py"

echo "✅ Done. You can now refresh index.html or public.html via your local server."
