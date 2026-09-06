#!/usr/bin/env bash
# UNLOOP preflight — run before recording the demo or submitting.
#
# Checks, in order of how badly you would regret skipping them:
#   1. no secrets are committed or committable
#   2. the Rime configuration is one the installed plugin will actually accept
#   3. the configured voice exists in Rime's LIVE catalog right now
#   4. the deterministic test suite passes
#   5. lint and formatting are clean
#   6. the evidence artifacts exist and were generated from this commit
#
# Usage:  bash scripts/preflight.sh
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [ -x "agent/.venv/Scripts/python.exe" ]; then
  PY="agent/.venv/Scripts/python.exe"       # Windows
elif [ -x "agent/.venv/bin/python" ]; then
  PY="agent/.venv/bin/python"               # macOS / Linux
else
  PY="python"
fi

PASS=0
FAIL=0
WARN=0

ok()   { echo "  PASS  $1"; PASS=$((PASS+1)); }
bad()  { echo "  FAIL  $1"; FAIL=$((FAIL+1)); }
warn() { echo "  WARN  $1"; WARN=$((WARN+1)); }

echo "UNLOOP preflight"
echo "repo: $REPO_ROOT"
echo "python: $PY"
echo

# ---------------------------------------------------------------------------
echo "[1/6] Secret scan"
# ---------------------------------------------------------------------------

# Any .env that is not the template must be untracked.
TRACKED_ENV="$(git ls-files | grep -E '(^|/)\.env($|\.)' | grep -v '\.env\.example$' || true)"
if [ -n "$TRACKED_ENV" ]; then
  bad "environment files are tracked by git:"; echo "$TRACKED_ENV" | sed 's/^/          /'
else
  ok "no .env files tracked (only .env.example)"
fi

# The template must contain placeholders, never values.
if git ls-files | grep -q '^\.env\.example$'; then
  FILLED="$(grep -nE '^(RIME_API_KEY|LIVEKIT_API_KEY|LIVEKIT_API_SECRET|OPENAI_API_KEY|ANTHROPIC_API_KEY)=.+' .env.example || true)"
  if [ -n "$FILLED" ]; then
    bad ".env.example has a filled-in credential:"; echo "$FILLED" | sed 's/^/          /'
  else
    ok ".env.example contains placeholders only"
  fi
else
  bad ".env.example is missing"
fi

# Credential-shaped strings anywhere in tracked content.
LEAKS="$(git grep -nIE '(sk-[A-Za-z0-9]{16,}|APIA[A-Za-z0-9]{10,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)' \
          -- . ':(exclude)scripts/preflight.sh' 2>/dev/null || true)"
if [ -n "$LEAKS" ]; then
  bad "credential-shaped strings found in tracked files:"; echo "$LEAKS" | sed 's/^/          /'
else
  ok "no credential-shaped strings in tracked files"
fi

# The Rime key must never be reachable from the browser bundle.
if [ -d apps/web ]; then
  CLIENT_LEAK="$(git grep -nI 'RIME_API_KEY' -- apps/web 2>/dev/null | grep -v 'NEXT_PUBLIC.*#' || true)"
  if [ -n "$CLIENT_LEAK" ]; then
    bad "RIME_API_KEY is referenced in the web app; it must stay server-side:"
    echo "$CLIENT_LEAK" | sed 's/^/          /'
  else
    ok "RIME_API_KEY is not referenced in the web app"
  fi
fi

# ---------------------------------------------------------------------------
echo
echo "[2/6] Rime configuration"
# ---------------------------------------------------------------------------
CONFIG_OUT="$("$PY" - <<'PY' 2>&1
import sys
sys.path.insert(0, "agent/src")
from unloop.config import AppConfig
c = AppConfig.from_env()
problems = c.rime.validate()
print("MODEL", c.rime.model)
print("SPEAKER", c.rime.speaker)
print("ENDPOINT", c.rime.resolved_endpoint())
print("TRANSPORT", c.rime.transport)
print("MISSING", ",".join(c.missing_credentials()) or "none")
for p in problems:
    print("PROBLEM", p)
PY
)"
echo "$CONFIG_OUT" | grep -E '^(MODEL|SPEAKER|ENDPOINT|TRANSPORT)' | sed 's/^/          /'
if echo "$CONFIG_OUT" | grep -q '^PROBLEM'; then
  bad "Rime configuration problems:"; echo "$CONFIG_OUT" | grep '^PROBLEM' | sed 's/^/          /'
else
  ok "Rime configuration is valid for the installed plugin"
fi
if echo "$CONFIG_OUT" | grep -q '/ws3/ws3'; then
  bad "resolved endpoint contains /ws3/ws3 — RIME_BASE_URL must be the origin only"
else
  ok "resolved endpoint has exactly one /ws3"
fi
MISSING="$(echo "$CONFIG_OUT" | sed -n 's/^MISSING //p')"
if [ "$MISSING" != "none" ]; then
  warn "credentials not set: $MISSING (live voice, telephony and the voice benchmark are blocked)"
else
  ok "all credentials present"
fi

# ---------------------------------------------------------------------------
echo
echo "[3/6] Live Rime catalog"
# ---------------------------------------------------------------------------
if "$PY" scripts/verify_rime_catalog.py --write-artifact >/tmp/unloop_catalog.log 2>&1; then
  ok "configured model/voice/language exists in the live Rime catalog"
  grep -E '^(OK|    )' /tmp/unloop_catalog.log | sed 's/^/          /'
else
  bad "catalog verification failed:"; sed 's/^/          /' /tmp/unloop_catalog.log
fi

# ---------------------------------------------------------------------------
echo
echo "[4/6] Deterministic test suite"
# ---------------------------------------------------------------------------
if (cd agent && "../$PY" -m pytest tests/ -q >/tmp/unloop_pytest.log 2>&1); then
  ok "$(tail -1 /tmp/unloop_pytest.log)"
else
  bad "tests failed:"; tail -20 /tmp/unloop_pytest.log | sed 's/^/          /'
fi

# ---------------------------------------------------------------------------
echo
echo "[5/6] Lint and format"
# ---------------------------------------------------------------------------
if (cd agent && "../$PY" -m ruff check src/ tests/ >/tmp/unloop_ruff.log 2>&1); then
  ok "ruff check clean"
else
  bad "ruff check:"; tail -10 /tmp/unloop_ruff.log | sed 's/^/          /'
fi
if (cd agent && "../$PY" -m ruff format --check src/ tests/ >/dev/null 2>&1); then
  ok "ruff format clean"
else
  warn "ruff format would change files (run: ruff format src/ tests/)"
fi

# ---------------------------------------------------------------------------
echo
echo "[6/6] Evidence artifacts"
# ---------------------------------------------------------------------------
for artifact in artifacts/results.json artifacts/rime_config.json; do
  if [ -f "$artifact" ]; then ok "$artifact present"; else bad "$artifact missing (run: make evidence)"; fi
done

EVENT_COUNT="$(find artifacts/events -name '*.jsonl' 2>/dev/null | wc -l | tr -d ' ')"
if [ "$EVENT_COUNT" -gt 0 ]; then
  ok "$EVENT_COUNT raw event logs in artifacts/events/"
else
  bad "no event logs (run: make evidence)"
fi

if [ -f artifacts/results.json ]; then
  EVIDENCE_STATE="$("$PY" - <<'PY'
import json, subprocess
try:
    d = json.load(open("artifacts/results.json"))
except Exception as exc:
    print("ERROR", exc); raise SystemExit
head = subprocess.run(["git","rev-parse","HEAD"], capture_output=True, text=True).stdout.strip()
print("COMMIT_MATCH", "yes" if d.get("git_commit") == head else "no")
print("DIRTY", d.get("source_tree_dirty"))
t = d.get("totals", {})
print("TOTALS", t.get("passes"), "/", t.get("runs"))
PY
)"
  echo "$EVIDENCE_STATE" | grep -E '^TOTALS' | sed 's/^/          /'
  if echo "$EVIDENCE_STATE" | grep -q 'COMMIT_MATCH yes'; then
    ok "results.json was generated from the current commit"
  else
    warn "results.json was generated from a different commit (regenerate before submitting)"
  fi
  if echo "$EVIDENCE_STATE" | grep -q 'DIRTY True'; then
    warn "results.json was generated from a dirty SOURCE tree (artifacts/ excluded)"
  fi
fi

# ---------------------------------------------------------------------------
echo
echo "-----------------------------------------------------"
echo "  passed: $PASS   failed: $FAIL   warnings: $WARN"
echo "-----------------------------------------------------"
[ "$FAIL" -eq 0 ] || exit 1
exit 0
