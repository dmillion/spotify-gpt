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

echo "Stopping existing Tone Raider app processes..."

# Kill only app.py processes whose working directory is this repository.
# This avoids touching unrelated Python apps elsewhere on the machine.
while read -r pid; do
  [[ -z "$pid" ]] && continue
  [[ "$pid" == "$$" ]] && continue

  cwd="$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -n 1 || true)"
  command="$(ps -p "$pid" -o command= 2>/dev/null || true)"

  if [[ "$cwd" == "$ROOT" && "$command" == *"app.py"* ]]; then
    echo "Stopping PID $pid: $command"
    kill "$pid" 2>/dev/null || true
  fi
done < <(pgrep -f 'app\.py' || true)

# Give Flask's debug parent/child processes a moment to exit cleanly.
sleep 0.5

# Force-stop any matching process that survived SIGTERM.
while read -r pid; do
  [[ -z "$pid" ]] && continue
  [[ "$pid" == "$$" ]] && continue

  cwd="$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -n 1 || true)"
  command="$(ps -p "$pid" -o command= 2>/dev/null || true)"

  if [[ "$cwd" == "$ROOT" && "$command" == *"app.py"* ]]; then
    echo "Force-stopping PID $pid"
    kill -9 "$pid" 2>/dev/null || true
  fi
done < <(pgrep -f 'app\.py' || true)

echo
echo "Tone Raider configuration:"
"$PYTHON" - <<'PY'
import os
from dotenv import load_dotenv

load_dotenv()
model = os.environ.get("OLLAMA_MODEL", "gpt-oss:20b").strip()
api_url = os.environ.get("OLLAMA_API_URL", "https://ollama.com/api/chat").strip()
port = os.environ.get("PORT", "5000").strip()
api_key = os.environ.get("OLLAMA_API_KEY", "").strip()

print(f"  Ollama model : {model or '(not set)'}")
print(f"  Ollama API   : {api_url}")
print(f"  App port     : {port}")
print(f"  API key      : {'configured' if api_key else 'NOT SET'}")
PY
echo

exec "$PYTHON" app.py
