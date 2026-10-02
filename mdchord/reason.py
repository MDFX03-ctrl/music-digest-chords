"""Call any OpenAI-compatible chat endpoint with the chord-naming prompt."""

import json
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTS = ROOT / "prompts" / "chord-naming.md"


def load_agents():
    return AGENTS.read_text(encoding="utf-8")


def endpoint(base_url):
    base = base_url.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return base + "/chat/completions"


def messages(agents, measurement, errors=None):
    if errors:
        payload = {"measurement": measurement, "validation_errors": errors}
    else:
        payload = measurement
    return [
        {"role": "system", "content": agents},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


def message_text(message):
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(item.get("text") or "")
        return "".join(parts)
    return ""


def complete(measurement, config, errors=None, agents=None, opener=None):
    body = {
        "model": config.model,
        "max_tokens": config.max_tokens,
        "messages": messages(agents if agents is not None else load_agents(), measurement, errors),
        "response_format": {"type": "json_object"},
    }
    text, status, raw = _post(config, body, opener)
    if status >= 400 and "response_format" in raw:
        body.pop("response_format")
        text, status, raw = _post(config, body, opener)
    if status >= 400:
        raise RuntimeError(f"model API returned {status}: {raw[:500]}")
    return text


def _post(config, body, opener):
    req = urllib.request.Request(
        endpoint(config.base_url),
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + config.api_key,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    open_url = opener or urllib.request.urlopen
    try:
        with open_url(req, timeout=180) as res:
            raw = res.read().decode("utf-8")
            status = getattr(res, "status", 200)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        return "", exc.code, raw
    data = json.loads(raw)
    return message_text(data["choices"][0]["message"]), status, raw
