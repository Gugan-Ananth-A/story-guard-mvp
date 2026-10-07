"""One Ollama narrative call over a score object. No tools and no rewrite."""

import json
import os
import time
import urllib.error
import urllib.request

from story_guard.prefix import load_prefix

# Callers cannot override this. A rewrite call is not part of this function.
TEMPERATURE = 0.1
NUM_CTX = 8192
MAX_TOKENS = 8192
GENERATION_TIMEOUT_S = 60
# Cold start sits outside the 60s generation cap, so the socket wait is longer.
HTTP_TIMEOUT_S = 300
DEFAULT_MODEL = "qwen3.5:4b"
DEFAULT_HOST = "http://127.0.0.1:11434"
_NS = 1_000_000_000
_OWNERS = {"qa", "dev", "po"}


class NarrativeError(Exception):
    """The narrative call failed. The caller writes no report."""


def write_narrative(score: dict) -> dict:
    """Call Ollama once. Invalid JSON or a missed schema retries that same request once."""
    if not isinstance(score, dict):
        raise NarrativeError("score is not an object")
    payload = _payload(score)
    last_error: NarrativeError | None = None
    latency_ms = 0
    for _attempt in range(2):
        started = time.perf_counter()
        try:
            response = _post(payload)
            _check_cap(response)
            narrative = _parse_narrative(response)
        except NarrativeError as exc:
            latency_ms += _elapsed_ms(started)
            last_error = exc
            continue
        latency_ms += _elapsed_ms(started)
        return {
            "score": score,
            "narrative": narrative,
            "token_count": _token_count(response),
            "narrative_latency_ms": latency_ms,
        }
    raise NarrativeError(f"narrative failed after 2 attempts: {last_error}")


def _payload(score: dict) -> dict:
    try:
        prefix = load_prefix()
    except OSError as exc:
        raise NarrativeError("narrative prefix is missing") from exc
    try:
        score_json = json.dumps(score, ensure_ascii=False, separators=(",", ":"))
    except TypeError as exc:
        raise NarrativeError("score is not JSON") from exc
    payload = {
        "model": _model(),
        "stream": False,
        "format": "json",
        # qwen3.5 spends the token budget on thinking unless this is off.
        "think": False,
        "messages": [
            {"role": "system", "content": prefix},
            {"role": "user", "content": score_json},
        ],
        "options": {
            "num_ctx": NUM_CTX,
            "temperature": TEMPERATURE,
            "num_predict": MAX_TOKENS,
        },
    }
    if "tools" in payload or any("tools" in message for message in payload["messages"]):
        raise NarrativeError("narrative request must not include tools")
    return payload


def _model() -> str:
    raw = os.environ.get("OLLAMA_MODEL")
    if raw is None or raw.strip() == "":
        return DEFAULT_MODEL
    return raw.strip()


def _host() -> str:
    raw = os.environ.get("OLLAMA_HOST")
    if raw is None or raw.strip() == "":
        return DEFAULT_HOST
    return raw.strip().rstrip("/")


def _post(payload: dict) -> dict:
    # Native /api/chat so num_ctx is on this request.
    request = urllib.request.Request(
        f"{_host()}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_S) as response:
            body = json.load(response)
    except (urllib.error.URLError, TimeoutError) as exc:
        raise NarrativeError(f"ollama request failed: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise NarrativeError("ollama response was not valid JSON") from exc
    if not isinstance(body, dict):
        raise NarrativeError("ollama response was not an object")
    return body


def _elapsed_ms(started: float) -> int:
    return int(round((time.perf_counter() - started) * 1000))


def _token_count(response: dict) -> int:
    """Prompt tokens plus generated tokens from the narrative response."""
    total = 0
    saw = False
    for key in ("prompt_eval_count", "eval_count"):
        value = response.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        total += int(value)
        saw = True
    return total if saw else 0


def _check_cap(response: dict) -> None:
    eval_count = response.get("eval_count")
    if isinstance(eval_count, (int, float)) and not isinstance(eval_count, bool):
        if int(eval_count) >= MAX_TOKENS:
            raise NarrativeError("narrative exceeded 8192 tokens")
    generated_ns = _generation_ns(response)
    if generated_ns is not None and generated_ns > GENERATION_TIMEOUT_S * _NS:
        raise NarrativeError("narrative exceeded 60 seconds of generation")


def _generation_ns(response: dict) -> int | None:
    """Time after the weights are loaded. A missing clock is not a cap failure."""
    total = _ns(response.get("total_duration"))
    load = _ns(response.get("load_duration"))
    if total is not None and load is not None:
        return max(0, total - load)
    generated = _ns(response.get("eval_duration"))
    if generated is None:
        return None
    prompt = _ns(response.get("prompt_eval_duration")) or 0
    return prompt + generated


def _ns(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def _parse_narrative(response: dict) -> dict:
    message = response.get("message")
    if not isinstance(message, dict):
        raise NarrativeError("ollama response has no message")
    content = message.get("content")
    if not isinstance(content, str):
        raise NarrativeError("ollama message content is not text")
    body = _load_json_object(content)
    headline = body.get("headline")
    sections = body.get("sections")
    actions = body.get("actions")
    if not isinstance(headline, str) or headline.strip() == "":
        raise NarrativeError("narrative JSON misses headline")
    if not isinstance(sections, list):
        raise NarrativeError("narrative JSON misses sections")
    if not _valid_actions(actions):
        raise NarrativeError("narrative JSON misses actions")
    return body


def _load_json_object(content: str) -> dict:
    text = content.strip()
    try:
        body = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end <= start:
            raise NarrativeError(_bad_json(text))
        try:
            body = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise NarrativeError(_bad_json(text)) from exc
    if not isinstance(body, dict):
        raise NarrativeError("narrative response was not a JSON object")
    return body


def _bad_json(text: str) -> str:
    snippet = text.replace("\n", " ")[:160]
    return f"narrative response was not valid JSON: {snippet}"


def _valid_actions(actions: object) -> bool:
    if not isinstance(actions, list) or not 3 <= len(actions) <= 7:
        return False
    for action in actions:
        if not isinstance(action, dict):
            return False
        owner = action.get("owner", action.get("owner_role"))
        if not isinstance(owner, str) or owner.strip().lower() not in _OWNERS:
            return False
        text = action.get("text", action.get("action"))
        if not isinstance(text, str) or text.strip() == "":
            return False
    return True
