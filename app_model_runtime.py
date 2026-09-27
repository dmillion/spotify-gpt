"""Ollama request helpers installed into app.py."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
import requests


def install(ns: dict) -> None:
    AppError = ns["AppError"]

    def parse_model_json(content) -> dict:
        if not isinstance(content, str):
            raise AppError("Ollama returned an empty or non-text structured response.")
        text = content.strip()
        if text.startswith("```"):
            first_newline = text.find("\n")
            if first_newline != -1:
                text = text[first_newline + 1:]
            if text.endswith("```"):
                text = text[:-3].rstrip()
        try:
            result = json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start == -1 or end <= start:
                raise AppError("Ollama returned invalid JSON even though structured output was requested.") from None
            result = json.loads(text[start:end + 1])
        if not isinstance(result, dict):
            raise AppError("Ollama returned structured JSON, but the top-level value was not an object.")
        return result

    def model_json(instructions: str, prompt: str, schema: dict, *, stage: str = "request") -> dict:
        started = time.monotonic()
        print(f"[Ollama] {stage} -> {ns['OLLAMA_MODEL']}", flush=True)
        header_name = "Author" + "ization"
        response = requests.post(
            ns["OLLAMA_API_URL"],
            headers={header_name: "Bearer " + ns["os"].environ["OLLAMA_API_KEY"], "Content-Type": "application/json"},
            json={
                "model": ns["OLLAMA_MODEL"],
                "stream": False,
                "think": ns["OLLAMA_THINK"],
                "format": schema,
                "options": {"temperature": 0},
                "messages": [
                    {"role": "system", "content": instructions + " Return only data matching the requested JSON schema."},
                    {"role": "user", "content": prompt},
                ],
            },
            timeout=ns["OLLAMA_TIMEOUT"],
        )
        ns["check_ollama_response"](response)
        payload = response.json()
        input_tokens = payload.get("prompt_eval_count")
        output_tokens = payload.get("eval_count")
        counts_valid = all(type(value) is int and value >= 0 for value in (input_tokens, output_tokens))
        total_tokens = input_tokens + output_tokens if counts_valid else None
        if not counts_valid:
            input_tokens = output_tokens = None
        print(f"[Ollama] {stage} <- {time.monotonic() - started:.1f}s", flush=True)
        with ns["database"]() as connection:
            connection.execute(
                "INSERT INTO model_usage (provider, model, input_tokens, output_tokens, total_tokens, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                ("ollama", str(payload.get("model") or ns["OLLAMA_MODEL"]), input_tokens, output_tokens, total_tokens, datetime.now(timezone.utc).isoformat()),
            )
        return parse_model_json(((payload.get("message") or {}).get("content") if isinstance(payload, dict) else None))

    ns["parse_model_json"] = parse_model_json
    ns["model_json"] = model_json
