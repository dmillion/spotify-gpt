#!/usr/bin/env python3
"""Verify Ollama Cloud credentials and the configured model."""

from __future__ import annotations

import json
import os
import sys

import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.environ.get("OLLAMA_API_KEY", "").strip()
API_URL = os.environ.get("OLLAMA_API_URL", "https://ollama.com/api/chat").strip()
MODEL = os.environ.get("OLLAMA_MODEL", "gpt-oss:20b").strip()

if not API_KEY:
    raise SystemExit("OLLAMA_API_KEY is missing from .env")
if not MODEL:
    raise SystemExit("OLLAMA_MODEL is empty")

print(f"Ollama endpoint: {API_URL}")
print(f"Ollama model: {MODEL}")
print("API key: found")

response = requests.post(
    API_URL,
    headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
    json={
        "model": MODEL,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0},
        "messages": [
            {"role": "system", "content": "Return JSON only."},
            {"role": "user", "content": 'Return exactly this JSON object: {"ok":true,"purpose":"playlist-curation"}'},
        ],
    },
    timeout=120,
)

if not response.ok:
    print(f"HTTP {response.status_code}")
    try:
        print(json.dumps(response.json(), indent=2))
    except ValueError:
        print(response.text[:1000])
    sys.exit(1)

payload = response.json()
content = (payload.get("message") or {}).get("content")
print(f"prompt tokens: {payload.get('prompt_eval_count', 'not reported')}")
print(f"output tokens: {payload.get('eval_count', 'not reported')}")
print("response:")
print(content)

try:
    parsed = json.loads(content)
except (TypeError, json.JSONDecodeError):
    raise SystemExit("FAIL: configured model did not return valid JSON")

if parsed.get("ok") is not True:
    raise SystemExit("FAIL: model response did not match the expected JSON shape")

print("OK: Ollama Cloud credentials and structured JSON generation are working.")
