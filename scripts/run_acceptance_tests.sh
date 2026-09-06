#!/usr/bin/env bash
# Run the full acceptance suite and regenerate the evidence artifacts.
#
# This is the single command referenced by RIME_EVIDENCE.md's Reproduction section.
# It runs the deterministic tests, then the evidence generator, then verifies the
# Rime configuration against the live catalog.
#
# Usage:
#   bash scripts/run_acceptance_tests.sh            # 20 runs per scenario
#   RUNS=5 bash scripts/run_acceptance_tests.sh     # quicker
#   DELAY_MS=3000 bash scripts/run_acceptance_tests.sh   # full demo timing
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

RUNS="${RUNS:-20}"
DELAY_MS="${DELAY_MS:-300}"

if [ -x "agent/.venv/Scripts/python.exe" ]; then
  PY="agent/.venv/Scripts/python.exe"
elif [ -x "agent/.venv/bin/python" ]; then
  PY="agent/.venv/bin/python"
else
  PY="python"
fi

echo "=============================================="
echo " UNLOOP acceptance suite"
echo " runs per scenario: $RUNS   injected delay: ${DELAY_MS}ms"
echo "=============================================="
echo

echo "--- 1. Deterministic unit and invariant tests ---"
(cd agent && "../$PY" -m pytest tests/ -v --tb=short)
echo

echo "--- 2. Acceptance scenarios + evidence generation ---"
"$PY" scripts/generate_evidence.py --runs "$RUNS" --delay-ms "$DELAY_MS"
echo

echo "--- 3. Live Rime catalog verification ---"
"$PY" scripts/verify_rime_catalog.py --write-artifact
echo

echo "=============================================="
echo " Artifacts written:"
echo "   artifacts/results.json"
echo "   artifacts/rime_config.json"
echo "   artifacts/rime_catalog_check.json"
echo "   artifacts/events/*.jsonl  ($(find artifacts/events -name '*.jsonl' | wc -l | tr -d ' ') files)"
echo "=============================================="
