"""Standalone check that a Novita API key works — does not import this project.

Run:
    # PowerShell
    $env:NOVITA_API_KEY = "sk-..."; python scripts/check_novita.py

    # bash
    NOVITA_API_KEY=sk-... python scripts/check_novita.py

Optionally pass a model id to exercise instead of the default:
    python scripts/check_novita.py openai/gpt-oss-120b

What it proves, in order:
1. ``GET /models``  — the key authenticates at all, and which models it can reach.
2. ``POST /chat/completions`` — a real (tiny) completion goes through, non-streamed.
3. ``POST /chat/completions`` with ``stream=True`` — the streaming path this project
   actually uses for proposal drafting (llm/chat_client.py::stream_complete).

Novita is OpenAI-compatible, so a working key here means `llm/chat_client.py`
would work against it by changing only `groq.base_url` and `groq.llm_model`.
"""

import json
import os
import sys

import httpx

BASE_URL = os.environ.get("NOVITA_BASE_URL", "https://api.novita.ai/v3/openai")
DEFAULT_MODEL = "meta-llama/llama-3.1-8b-instruct"
TIMEOUT = 60.0

# Novita's OpenAI-compatible surface returns these the same way Groq does, so the
# meanings below are what you'd also see from llm/chat_client.py.
STATUS_MEANING = {
    401: "key is invalid, revoked, or malformed",
    403: "key is valid but not permitted for this model/endpoint",
    404: "endpoint or model id does not exist at this base URL",
    429: "key works — you are rate limited (this is NOT an auth failure)",
    402: "key works — account is out of credit",
}


def _explain(response: httpx.Response) -> str:
    meaning = STATUS_MEANING.get(response.status_code, "unexpected status")
    return f"HTTP {response.status_code} — {meaning}\n{response.text[:800]}"


def check_models(client: httpx.Client) -> list[str]:
    print(f"[1/3] GET {BASE_URL}/models")
    response = client.get(f"{BASE_URL}/models")
    if response.status_code != 200:
        print("      FAILED:", _explain(response))
        return []

    ids = [entry.get("id", "?") for entry in response.json().get("data", [])]
    print(f"      OK — key authenticates. {len(ids)} models reachable.")
    for model_id in ids[:10]:
        print(f"        - {model_id}")
    if len(ids) > 10:
        print(f"        ... and {len(ids) - 10} more")
    return ids


def check_completion(client: httpx.Client, model: str) -> bool:
    print(f"[2/3] POST {BASE_URL}/chat/completions  model={model}")
    response = client.post(
        f"{BASE_URL}/chat/completions",
        json={
            "model": model,
            "messages": [{"role": "user", "content": "Reply with the single word: pong"}],
            "max_tokens": 16,
            "temperature": 0,
        },
    )
    if response.status_code != 200:
        print("      FAILED:", _explain(response))
        return False

    body = response.json()
    reply = body["choices"][0]["message"]["content"].strip()
    usage = body.get("usage", {})
    print(f"      OK — model replied {reply!r}")
    print(
        f"      tokens: prompt={usage.get('prompt_tokens')} "
        f"completion={usage.get('completion_tokens')} total={usage.get('total_tokens')}"
    )
    return True


def check_stream(client: httpx.Client, model: str) -> bool:
    print(f"[3/3] POST {BASE_URL}/chat/completions (stream=True)  model={model}")
    deltas = 0
    text: list[str] = []
    with client.stream(
        "POST",
        f"{BASE_URL}/chat/completions",
        json={
            "model": model,
            "messages": [{"role": "user", "content": "Count from 1 to 5, comma separated."}],
            "max_tokens": 32,
            "temperature": 0,
            "stream": True,
        },
    ) as response:
        if response.status_code != 200:
            response.read()
            print("      FAILED:", _explain(response))
            return False

        for line in response.iter_lines():
            if not line.startswith("data: "):
                continue
            payload = line[len("data: "):].strip()
            if payload == "[DONE]":
                break
            delta = json.loads(payload)["choices"][0].get("delta", {}).get("content")
            if delta:
                deltas += 1
                text.append(delta)

    print(f"      OK — {deltas} streamed deltas: {''.join(text).strip()!r}")
    return True


def main() -> int:
    api_key = os.environ.get("NOVITA_API_KEY")
    if not api_key:
        print("NOVITA_API_KEY is not set. See the docstring at the top of this file.")
        return 2

    model = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_MODEL
    print(f"base_url = {BASE_URL}")
    print(f"key      = {api_key[:6]}...{api_key[-4:]} ({len(api_key)} chars)\n")

    with httpx.Client(
        timeout=TIMEOUT, headers={"Authorization": f"Bearer {api_key}"}
    ) as client:
        available = check_models(client)
        if not available:
            print("\nRESULT: key did NOT authenticate — nothing else worth trying.")
            return 1

        if model not in available:
            print(
                f"\nNote: {model!r} is not in the reachable list; trying it anyway "
                f"(the list can be paginated or filtered)."
            )

        print()
        if not check_completion(client, model):
            print("\nRESULT: key authenticates, but this model could not complete. "
                  "Try another id from the list above.")
            return 1

        print()
        streamed = check_stream(client, model)

    print(f"\nRESULT: key WORKS. streaming={'yes' if streamed else 'no'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
