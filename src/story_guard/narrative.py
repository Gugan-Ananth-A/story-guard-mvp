"""One Ollama narrative call over a score object. No tools and no rewrite."""

import json
import os
import re
import time
import urllib.error
import urllib.request

from story_guard.prefix import load_prefix

# Callers cannot override this. A rewrite call is not part of this function.
TEMPERATURE = 0.1
NUM_CTX = 8192
MAX_TOKENS = 8192
GENERATION_TIMEOUT_S = 180
# Cold start and thinking sit outside the generation cap, so the socket wait is longer.
HTTP_TIMEOUT_S = 600
DEFAULT_MODEL = "qwen3.5:9b"
DEFAULT_HOST = "http://127.0.0.1:11434"
_NS = 1_000_000_000
_OWNERS = {"qa", "dev", "po"}


class NarrativeError(Exception):
    """The narrative call failed. The caller writes no report."""

    def __init__(self, message: str, retry_hint: bool = False):
        super().__init__(message)
        self.retry_hint = retry_hint


# A rule miss is sent back so the model can correct it. The budget is four calls.
ATTEMPTS = 4


def write_narrative(score: dict) -> dict:
    """Call Ollama. A rejected body is tried again until the attempt budget is spent."""
    if not isinstance(score, dict):
        raise NarrativeError("score is not an object")
    last_error: NarrativeError | None = None
    correction: str | None = None
    latency_ms = 0
    for _attempt in range(ATTEMPTS):
        payload = _payload(score, correction)
        started = time.perf_counter()
        try:
            response = _post(payload)
            _check_cap(response)
            narrative = _parse_narrative(response, score)
        except NarrativeError as exc:
            latency_ms += _elapsed_ms(started)
            last_error = exc
            correction = str(exc) if exc.retry_hint else None
            continue
        latency_ms += _elapsed_ms(started)
        return {
            "score": score,
            "narrative": narrative,
            "token_count": _token_count(response),
            "narrative_latency_ms": latency_ms,
        }
    raise NarrativeError(f"narrative failed after {ATTEMPTS} attempts: {last_error}")


def _payload(score: dict, correction: str | None = None) -> dict:
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
        # qwen3.5 thinks before the JSON. The generation cap covers that time.
        "think": True,
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
    if correction:
        payload["messages"].append(
            {
                "role": "user",
                "content": (
                    "The previous JSON was rejected: "
                    + correction
                    + " Return one JSON object that satisfies every rule in the system message. "
                    "Use only facts from the score. Do not add a percent sign."
                ),
            }
        )
    if "tools" in payload or any("tools" in message for message in payload["messages"]):
        raise NarrativeError("narrative request must not include tools")
    return payload


def ollama_chat(messages: list[dict], num_predict: int = MAX_TOKENS) -> dict:
    """One local JSON chat. Callers pass the messages. The model and context stay fixed."""
    if any("tools" in message for message in messages):
        raise NarrativeError("narrative request must not include tools")
    if isinstance(num_predict, bool) or not isinstance(num_predict, int):
        num_predict = MAX_TOKENS
    if num_predict < 1 or num_predict > MAX_TOKENS:
        num_predict = MAX_TOKENS
    payload = {
        "model": _model(),
        "stream": False,
        "format": "json",
        "think": True,
        "messages": messages,
        "options": {
            "num_ctx": NUM_CTX,
            "temperature": TEMPERATURE,
            "num_predict": num_predict,
        },
    }
    return _post(payload)


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
        raise NarrativeError(
            f"narrative exceeded {GENERATION_TIMEOUT_S} seconds of generation"
        )


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


def _parse_narrative(response: dict, score: dict) -> dict:
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
        raise NarrativeError("narrative JSON misses headline", retry_hint=True)
    if not isinstance(sections, list):
        raise NarrativeError("narrative JSON misses sections", retry_hint=True)
    if not _valid_actions(actions):
        raise NarrativeError("narrative JSON misses actions", retry_hint=True)
    _require_observations(body.get("observations"), score)
    try:
        enforce_narrative_rules(score, body)
    except NarrativeError as exc:
        raise NarrativeError(str(exc), retry_hint=True) from exc
    return body


def _require_observations(observations: object, score: dict) -> None:
    """Key observations are the sentences printed beside the portfolio summary."""
    if not isinstance(observations, list) or not 4 <= len(observations) <= 5:
        raise NarrativeError("narrative JSON misses observations", retry_hint=True)
    health = score.get("health")
    cited_health = False
    for item in observations:
        if not isinstance(item, str) or not item.strip():
            raise NarrativeError("narrative JSON misses observations", retry_hint=True)
        if len(item) > 400:
            raise NarrativeError("narrative rule: an observation is too long", retry_hint=True)
        if isinstance(health, str) and health.casefold() in item.casefold():
            cited_health = True
    if isinstance(health, str) and health.strip() and not cited_health:
        raise NarrativeError(
            f"narrative rule: observations must cite the story health {health}",
            retry_hint=True,
        )


def enforce_narrative_rules(score: dict, narrative: dict) -> None:
    """Reject counts, health labels, and coverage claims that contradict the score."""
    if not isinstance(narrative, dict):
        raise NarrativeError("narrative is not an object")
    strings = [narrative.get("headline", "")]
    observations = narrative.get("observations")
    if isinstance(observations, list):
        strings.extend(item for item in observations if isinstance(item, str))
    sections = narrative.get("sections", [])
    if isinstance(sections, list):
        for section in sections:
            if isinstance(section, str):
                strings.append(section)
            elif isinstance(section, dict):
                strings.extend((section.get("name", ""), section.get("prose", section.get("text", ""))))
    actions = narrative.get("actions", [])
    if isinstance(actions, list):
        strings.extend(
            action.get("text", action.get("action", ""))
            for action in actions
            if isinstance(action, dict)
        )
    text = "\n".join(value for value in strings if isinstance(value, str))
    if "%" in text:
        raise NarrativeError("narrative rule: a percent sign is not allowed")
    if "partially covered" in text.casefold():
        raise NarrativeError("narrative rule: partially covered is not allowed")
    checks = (
        ("scenario_count", r"\b(\d+)\s+(?:scenarios?|acceptance criteria)\b"),
        ("test_count", r"\b(\d+)\s+(?:tests?|test cases?)\b"),
        ("mapped_count", r"\b(\d+)\s+mapped(?:\s+(?:ACs?|tests?))?\b"),
        ("bug_count", r"\b(\d+)\s+bugs?\b"),
    )
    for key, pattern in checks:
        expected = score.get(key)
        if isinstance(expected, int):
            for match in re.finditer(pattern, text, flags=re.IGNORECASE):
                if int(match.group(1)) != expected:
                    raise NarrativeError(
                        f"narrative {key} {match.group(1)} does not match score {expected}"
                    )
    mapped_count = score.get("mapped_count")
    if isinstance(mapped_count, int):
        for match in re.finditer(
            r"\bmapped(?:\s+ACs?|\s+tests?)?\s*(?:count)?\s*[:=]\s*(\d+)\b",
            text,
            flags=re.IGNORECASE,
        ):
            if int(match.group(1)) != mapped_count:
                raise NarrativeError(
                    f"narrative mapped_count {match.group(1)} does not match score {mapped_count}"
                )
    health = score.get("health")
    if isinstance(health, str) and re.search(
        r"\bstory health\s*(?:is|:|-)\s*([^.!\n]+)", text, re.IGNORECASE
    ):
        match = re.search(r"\bstory health\s*(?:is|:|-)\s*([^.!\n]+)", text, re.IGNORECASE)
        assert match is not None
        if match.group(1).strip().casefold() != health.casefold():
            raise NarrativeError("narrative story health does not match the score")
    if score.get("mapped_count") == 0 and re.search(
        r"\b(?:AC[-\w]*|acceptance criteria)\s+(?:is|are)\s+covered\b",
        text,
        re.IGNORECASE,
    ):
        raise NarrativeError("narrative claims coverage absent from the score")
    if isinstance(health, str) and health.casefold() == "no open bugs" and re.search(
        r"\bhealth(?:\s+band)?\b[^.]{0,40}\b(?:red|amber|green)\b",
        text,
        re.IGNORECASE,
    ):
        raise NarrativeError(
            "narrative rule: story health is No open bugs and is not a RAG colour"
        )
    if (
        isinstance(score.get("scenario_count"), int)
        and score.get("none_count") == score.get("scenario_count")
        and score.get("scenario_count")
        and re.search(r"\b(?:are|is) covered\b", text, re.IGNORECASE)
    ):
        raise NarrativeError("narrative claims coverage absent from the score")
    rag = score.get("rag")
    if isinstance(rag, str):
        match = re.search(
            r"\b(?:RAG|coverage)\s*(?:is|:)\s*(Red|Amber|Green)\b",
            text,
            re.IGNORECASE,
        )
        if match and match.group(1).casefold() != rag.casefold():
            raise NarrativeError("narrative RAG does not match the score")


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
