#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PYTHON="$ROOT/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON="$(command -v python3)"
else
  PYTHON="$(command -v python)"
fi

echo "Stopping existing Tune Raider app processes..."

# Kill only Tune Raider Flask processes whose working directory is this repository.
# Match both the legacy app.py entrypoint and the current run_app.py entrypoint.
while read -r pid; do
  [[ -z "$pid" ]] && continue
  [[ "$pid" == "$$" ]] && continue

  cwd="$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -n 1 || true)"
  command="$(ps -p "$pid" -o command= 2>/dev/null || true)"

  if [[ "$cwd" == "$ROOT" && ( "$command" == *"app.py"* || "$command" == *"run_app.py"* ) ]]; then
    echo "Stopping PID $pid: $command"
    kill "$pid" 2>/dev/null || true
  fi
done < <(pgrep -f '(app|run_app)\.py' || true)

# Give Flask's debug parent/child processes a moment to exit cleanly.
sleep 0.5

# Force-stop any matching process that survived SIGTERM.
while read -r pid; do
  [[ -z "$pid" ]] && continue
  [[ "$pid" == "$$" ]] && continue

  cwd="$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -n 1 || true)"
  command="$(ps -p "$pid" -o command= 2>/dev/null || true)"

  if [[ "$cwd" == "$ROOT" && ( "$command" == *"app.py"* || "$command" == *"run_app.py"* ) ]]; then
    echo "Force-stopping PID $pid"
    kill -9 "$pid" 2>/dev/null || true
  fi
done < <(pgrep -f '(app|run_app)\.py' || true)

# Load the requested port from .env without sourcing arbitrary shell contents.
REQUESTED_PORT="$($PYTHON - <<'PY'
import os
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(dotenv_path=Path.cwd() / '.env')
print(os.environ.get('PORT', '5000').strip() or '5000')
PY
)"

PORT_TO_USE="$REQUESTED_PORT"
if lsof -nP -iTCP:"$PORT_TO_USE" -sTCP:LISTEN >/dev/null 2>&1; then
  OWNER="$(lsof -nP -iTCP:"$PORT_TO_USE" -sTCP:LISTEN 2>/dev/null | awk 'NR==2 {print $1 " (PID " $2 ")"}' || true)"
  echo "Port $PORT_TO_USE is already in use${OWNER:+ by $OWNER}."
  for candidate in 5001 5002 5003 5050; do
    if ! lsof -nP -iTCP:"$candidate" -sTCP:LISTEN >/dev/null 2>&1; then
      PORT_TO_USE="$candidate"
      echo "Using available fallback port $PORT_TO_USE for this run."
      break
    fi
  done
fi

if lsof -nP -iTCP:"$PORT_TO_USE" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "ERROR: Could not find an available Tune Raider port."
  exit 1
fi

export PORT="$PORT_TO_USE"

echo
echo "Tune Raider configuration:"
"$PYTHON" - <<'PY'
import os
from pathlib import Path
from dotenv import load_dotenv

# stdin execution gives python-dotenv no caller filename to inspect, so point
# it at this repo's .env explicitly instead of relying on find_dotenv().
load_dotenv(dotenv_path=Path.cwd() / ".env", override=False)
model = os.environ.get("OLLAMA_MODEL", "gpt-oss:20b").strip()
api_url = os.environ.get("OLLAMA_API_URL", "https://ollama.com/api/chat").strip()
timeout = os.environ.get("OLLAMA_TIMEOUT", "300").strip()
think = os.environ.get("OLLAMA_THINK", "false").strip() or "false"
port = os.environ.get("PORT", "5000").strip()
api_key = os.environ.get("OLLAMA_API_KEY", "").strip()

print(f"  Ollama model   : {model or '(not set)'}")
print(f"  Ollama API     : {api_url}")
print(f"  Ollama think   : {think}")
print(f"  Ollama timeout : {timeout} seconds")
print(f"  App port       : {port}")
print(f"  API key        : {'configured' if api_key else 'NOT SET'}")
PY
echo
echo "Open Tune Raider at: http://127.0.0.1:$PORT_TO_USE"
echo

exec "$PYTHON" run_app.py
