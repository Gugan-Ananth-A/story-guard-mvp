"""One Ollama narrative call over a score object. No tools and no rewrite."""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

from story_guard.prefix import load_prefix

# Callers cannot override this. A rewrite call is not part of this function.
TEMPERATURE = 0.1
NUM_CTX = 8192
MAX_TOKENS = 8192
PROMPT_TOKEN_TARGET = 4096
GENERATION_TIMEOUT_S = 180
# Cold start and thinking sit outside the generation cap, so the socket wait is longer.
HTTP_TIMEOUT_S = 600
DEFAULT_MODEL = "qwen3.5:4b"
DEFAULT_HOST = "http://127.0.0.1:11434"
DEFAULT_GROK_MODEL = "grok-4.7"
GROK_CHAT_URL = "https://api.x.ai/v1/chat/completions"
DEFAULT_DEEPSEEK_MODEL = "deepseek-flash"
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_OPENAI_MODEL = "gpt-5.6-luna"
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
_NS = 1_000_000_000
_OWNERS = {"qa", "dev", "po"}


class NarrativeError(Exception):
    """The narrative call failed. The caller writes no report."""

    def __init__(self, message: str, retry_hint: bool = False):
        super().__init__(message)
        self.retry_hint = retry_hint


# A rule miss is sent back so the model can correct it. The budget is four calls.
ATTEMPTS = 4


def story_failure(exc: BaseException) -> bool:
    """Provider outage and the generation cap stop the story. Bad JSON does not."""
    text = str(exc).casefold()
    if "request failed" in text:
        return True
    return f"exceeded {GENERATION_TIMEOUT_S} seconds of generation" in text


def name_story(story_id: str, exc: NarrativeError) -> NarrativeError:
    """Attach the story id when the failure text does not already name it."""
    text = str(exc).strip()
    if not story_id or story_id in text:
        return exc
    return NarrativeError(f"story {story_id}: {text}", retry_hint=exc.retry_hint)


def write_narrative(score: dict) -> dict:
    """Call the configured provider until the attempt budget is spent."""
    try:
        return _write_narrative(score)
    except NarrativeError as exc:
        story_id = str(score.get("story_id") or "") if isinstance(score, dict) else ""
        raise name_story(story_id, exc) from exc


def _write_narrative(score: dict) -> dict:
    if not isinstance(score, dict):
        raise NarrativeError("score is not an object")
    last_error: NarrativeError | None = None
    correction: str | None = None
    latency_ms = 0
    for _attempt in range(ATTEMPTS):
        payload, payload_score = _payload(score, correction)
        started = time.perf_counter()
        try:
            response = _post_provider(payload)
            _check_cap(response)
            narrative = _parse_narrative(response, score)
        except NarrativeError as exc:
            if story_failure(exc):
                raise
            latency_ms += _elapsed_ms(started)
            last_error = exc
            # A malformed response is itself useful feedback for the next
            # attempt. In particular, small local models often emit a blank
            # content field or wrap JSON in a short explanation.
            correction = str(exc) if exc.retry_hint else None
            continue
        latency_ms += _elapsed_ms(started)
        return {
            "score": payload_score,
            "narrative": narrative,
            "token_count": _token_count(response),
            "narrative_latency_ms": latency_ms,
        }
    raise NarrativeError(f"narrative failed after {ATTEMPTS} attempts: {last_error}")


def _payload(score: dict, correction: str | None = None) -> tuple[dict, dict]:
    try:
        prefix = load_prefix()
    except OSError as exc:
        raise NarrativeError("narrative prefix is missing") from exc
    try:
        payload_score = _bounded_score(score, prefix)
        score_json = json.dumps(
            payload_score, ensure_ascii=False, separators=(",", ":")
        )
    except TypeError as exc:
        raise NarrativeError("score is not JSON") from exc
    messages = [
        {"role": "system", "content": prefix},
        {"role": "user", "content": score_json},
    ]
    if correction:
        messages.append(
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
    provider = _llm_provider()
    if provider == "deepseek":
        payload = _deepseek_payload(messages, MAX_TOKENS)
    elif provider == "openai":
        payload = _openai_payload(messages, MAX_TOKENS)
    elif provider == "grok":
        payload = _grok_payload(messages, MAX_TOKENS)
    else:
        payload = {
            "model": _model(),
            "stream": False,
            "format": "json",
            # Structured output is more reliable when the model does not put
            # a separate reasoning trace beside the JSON response.
            "think": False,
            "messages": messages,
            "options": {
                "num_ctx": NUM_CTX,
                "temperature": TEMPERATURE,
                "num_predict": MAX_TOKENS,
            },
        }
    if "tools" in payload or any("tools" in message for message in payload["messages"]):
        raise NarrativeError("narrative request must not include tools")
    return payload, payload_score


def _bounded_score(score: dict, prefix: str) -> dict:
    """Trim whole test cases until the prompt is near its 4,096-token target."""
    test_cases = score.get("test_cases")
    if not isinstance(test_cases, list):
        return score

    bounded = dict(score)
    bounded["test_cases"] = list(test_cases)
    bounded["test_suite_truncated"] = bool(score.get("test_suite_truncated", False))
    if not test_cases:
        return bounded

    case_lengths = [
        len(json.dumps(case, ensure_ascii=False, separators=(",", ":")))
        for case in test_cases
    ]
    empty_suite = dict(bounded, test_cases=[])
    fixed_chars = len(prefix) + len(
        json.dumps(empty_suite, ensure_ascii=False, separators=(",", ":"))
    )
    total_chars = fixed_chars + sum(case_lengths) + max(0, len(test_cases) - 1)

    # A conservative character estimate keeps the rubric inside the target
    # without adding a tokenizer dependency.
    if (total_chars + 2) // 3 <= PROMPT_TOKEN_TARGET:
        return bounded

    bounded["test_suite_truncated"] = True
    if not score.get("test_suite_truncated", False):
        total_chars -= 1  # `true` serializes one character shorter than `false`.

    # Keep cases without step data unless the stepped cases alone cannot fit.
    removal_order = [
        index
        for index in range(len(test_cases) - 1, -1, -1)
        if isinstance(test_cases[index], dict) and test_cases[index].get("steps")
    ]
    removal_order.extend(
        index
        for index in range(len(test_cases) - 1, -1, -1)
        if not isinstance(test_cases[index], dict) or not test_cases[index].get("steps")
    )

    removed = set()
    remaining_count = len(test_cases)
    for index in removal_order:
        if (total_chars + 2) // 3 <= PROMPT_TOKEN_TARGET:
            break
        total_chars -= case_lengths[index]
        if remaining_count > 1:
            total_chars -= 1
        remaining_count -= 1
        removed.add(index)

    bounded["test_cases"] = [
        case for index, case in enumerate(test_cases) if index not in removed
    ]
    return bounded


def ollama_chat(messages: list[dict], num_predict: int = MAX_TOKENS) -> dict:
    """One JSON chat. Callers pass the messages. The model and context stay fixed."""
    if any("tools" in message for message in messages):
        raise NarrativeError("narrative request must not include tools")
    if isinstance(num_predict, bool) or not isinstance(num_predict, int):
        num_predict = MAX_TOKENS
    if num_predict < 1 or num_predict > MAX_TOKENS:
        num_predict = MAX_TOKENS
    if _llm_provider() == "deepseek":
        return _deepseek_chat(messages, num_predict)
    if _llm_provider() == "openai":
        return _openai_chat(messages, num_predict)
    if _llm_provider() == "grok":
        return _grok_chat(messages, num_predict)
    payload = {
        "model": _model(),
        "stream": False,
        "format": "json",
        # Keep the response channel dedicated to the JSON object. This is
        # especially important for small Qwen models, which may otherwise
        # leave message.content empty and put the answer in thinking.
        "think": False,
        "messages": messages,
        "options": {
            "num_ctx": NUM_CTX,
            "temperature": TEMPERATURE,
            "num_predict": num_predict,
        },
    }
    return _post(payload)


def _override_model() -> str:
    """STORY_GUARD_MODEL wins over the provider-specific model variable."""
    raw = os.environ.get("STORY_GUARD_MODEL")
    if raw is None:
        return ""
    return raw.strip()


def _named_model(env_name: str, default: str) -> str:
    override = _override_model()
    if override:
        return override
    raw = os.environ.get(env_name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip()


def _model() -> str:
    return _named_model("OLLAMA_MODEL", DEFAULT_MODEL)


def _deepseek_model() -> str:
    return _named_model("DEEPSEEK_MODEL", DEFAULT_DEEPSEEK_MODEL)


def configured_llm() -> tuple[str, str]:
    """Provider and model id selected from the environment."""
    provider = _llm_provider()
    if provider == "deepseek":
        return provider, _deepseek_model()
    if provider == "openai":
        return provider, _openai_model()
    if provider == "grok":
        return provider, _grok_model()
    return provider, _model()


def _deepseek_base_url() -> str:
    raw = os.environ.get("DEEPSEEK_BASE_URL")
    if raw is None or raw.strip() == "":
        return DEFAULT_DEEPSEEK_BASE_URL
    return raw.strip().rstrip("/")


def _deepseek_key() -> str:
    raw = os.environ.get("DEEPSEEK_API_KEY")
    if raw is None or raw.strip() == "":
        raise NarrativeError("DEEPSEEK_API_KEY is not set")
    return raw.strip()


def _host() -> str:
    raw = os.environ.get("OLLAMA_HOST")
    if raw is None or raw.strip() == "":
        return DEFAULT_HOST
    return raw.strip().rstrip("/")


def _llm_provider() -> str:
    """Select Ollama, OpenAI, DeepSeek, or Grok from the configured provider."""
    raw = os.environ.get("STORY_GUARD_LLM")
    provider = raw.strip().casefold() if raw is not None else ""
    if provider in {"grok", "xai"}:
        return "grok"
    if provider in {"openai", "chatgpt", "chat-gpt", "chat_gpt", "gpt"}:
        return "openai"
    if provider in {"deepseek", "deepseek-api", "deepseek_api"}:
        return "deepseek"
    if provider in {"", "ollama", "local"}:
        return "ollama"
    raise NarrativeError(f"unsupported STORY_GUARD_LLM provider: {raw}")


def _deepseek_payload(messages: list[dict], num_predict: int) -> dict:
    # Thinking is on by default and spends the token budget on a plan.
    # These calls need the JSON object in content, so thinking stays off.
    return {
        "model": _deepseek_model(),
        "messages": messages,
        "stream": False,
        "temperature": TEMPERATURE,
        "max_tokens": num_predict,
        "response_format": {"type": "json_object"},
        "thinking": {"type": "disabled"},
    }


def _deepseek_chat(messages: list[dict], num_predict: int) -> dict:
    return _timed_deepseek(_deepseek_payload(messages, num_predict))


def _timed_deepseek(payload: dict) -> dict:
    started = time.perf_counter()
    body = _deepseek_post(payload, _deepseek_key())
    elapsed_ns = int((time.perf_counter() - started) * _NS)
    return _stamp_duration(_deepseek_response(body), elapsed_ns)


def _stamp_duration(response: dict, elapsed_ns: int) -> dict:
    """Give a hosted reply the same generation clock the local cap already reads."""
    response["total_duration"] = elapsed_ns
    response["load_duration"] = 0
    response["eval_duration"] = elapsed_ns
    response["prompt_eval_duration"] = 0
    return response


def _deepseek_response(body: dict) -> dict:
    return _chat_choice(body, "deepseek")


_REASONING_PARTS = {"reasoning", "reasoning_text"}


def _assistant_text(content: object) -> str:
    """Visible answer text. Reasoning parts are not the JSON object."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
            continue
        if not isinstance(item, dict):
            continue
        if str(item.get("type") or "") in _REASONING_PARTS:
            continue
        text = item.get("text")
        if isinstance(text, str):
            parts.append(text)
    return "".join(parts)


def _completion_counts(usage: dict) -> tuple[int, int]:
    """Visible completion tokens, then reasoning tokens."""
    completion = _usage_count(usage.get("completion_tokens"))
    details = usage.get("completion_tokens_details")
    reasoning = 0
    if isinstance(details, dict):
        reasoning = _usage_count(details.get("reasoning_tokens"))
    if reasoning > completion:
        reasoning = completion
    return completion - reasoning, reasoning


def _chat_choice(body: dict, label: str) -> dict:
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise NarrativeError(f"{label} response has no choice")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise NarrativeError(f"{label} response has no message")
    content = _assistant_text(message.get("content"))
    usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
    visible, reasoning_tokens = _completion_counts(usage)
    finish = choices[0].get("finish_reason") or "stop"
    if label == "openai" and finish == "length" and content.strip() == "":
        raise NarrativeError("openai stopped before the JSON object", retry_hint=True)
    return {
        "message": {"role": "assistant", "content": content},
        "prompt_eval_count": _usage_count(usage.get("prompt_tokens")),
        "eval_count": visible,
        "reasoning_tokens": reasoning_tokens,
        "done_reason": finish,
    }


def _grok_model() -> str:
    return _named_model("XAI_MODEL", DEFAULT_GROK_MODEL)


def _grok_key() -> str:
    raw = os.environ.get("XAI_API_KEY")
    if raw is None or raw.strip() == "":
        raise NarrativeError("XAI_API_KEY is not set")
    return raw.strip()


def _grok_payload(messages: list[dict], num_predict: int) -> dict:
    return {
        "model": _grok_model(),
        "temperature": TEMPERATURE,
        "max_tokens": num_predict,
        "response_format": {"type": "json_object"},
        "messages": messages,
        "store": False,
    }


def _grok_chat(messages: list[dict], num_predict: int) -> dict:
    """One xAI chat completion, shaped like an Ollama /api/chat response."""
    payload = _grok_payload(messages, num_predict)
    if "tools" in payload or any("tools" in message for message in payload["messages"]):
        raise NarrativeError("narrative request must not include tools")
    return _timed_grok(payload)


def _timed_grok(payload: dict) -> dict:
    started = time.perf_counter()
    body = _grok_post(payload, _grok_key())
    elapsed_ns = int((time.perf_counter() - started) * _NS)
    usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
    return _stamp_duration(
        {
            "message": {"role": "assistant", "content": _grok_content(body)},
            "prompt_eval_count": _usage_count(usage.get("prompt_tokens")),
            "eval_count": _usage_count(usage.get("completion_tokens")),
        },
        elapsed_ns,
    )


def _usage_count(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return int(value)


def _grok_content(body: dict) -> str:
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise NarrativeError("grok response has no message")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise NarrativeError("grok response has no message")
    content = message.get("content")
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        content = "".join(parts)
    if not isinstance(content, str) or content.strip() == "":
        raise NarrativeError("grok message content is not text")
    return content


def _grok_post(payload: dict, key: str) -> dict:
    request = urllib.request.Request(
        GROK_CHAT_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_S) as response:
            body = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read(240).decode("utf-8", "replace").replace(key, "")
        raise NarrativeError(f"grok request failed: HTTP {exc.code} {detail}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise NarrativeError(f"grok request failed: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise NarrativeError("grok response was not valid JSON") from exc
    if not isinstance(body, dict):
        raise NarrativeError("grok response was not an object")
    return body


def _openai_model() -> str:
    return _named_model("OPENAI_MODEL", DEFAULT_OPENAI_MODEL)


def _openai_base_url() -> str:
    raw = os.environ.get("OPENAI_BASE_URL")
    if raw is None or raw.strip() == "":
        return DEFAULT_OPENAI_BASE_URL
    return raw.strip().rstrip("/")


def _openai_key() -> str:
    raw = os.environ.get("OPENAI_API_KEY")
    if raw is None or raw.strip() == "":
        raise NarrativeError("OPENAI_API_KEY is not set")
    return raw.strip()


# max_completion_tokens counts reasoning and the JSON answer. This reserve
# keeps a low-effort trace from ending the call before the object is written.
REASONING_TOKEN_RESERVE = 4096


def _reasoning_effort(model: str) -> str | None:
    """low is on for every GPT-5 and GPT-6 model. None omits the field."""
    if model.casefold().startswith(("gpt-5", "gpt-6")):
        return "low"
    return None


def _openai_payload(messages: list[dict], num_predict: int) -> dict:
    model = _openai_model()
    effort = _reasoning_effort(model)
    payload = {
        "model": model,
        "messages": messages,
        "max_completion_tokens": num_predict,
        "response_format": {"type": "json_object"},
    }
    # Reasoning models reject temperature unless effort is none.
    if effort is None:
        payload["temperature"] = TEMPERATURE
    else:
        payload["reasoning_effort"] = effort
        payload["max_completion_tokens"] = num_predict + REASONING_TOKEN_RESERVE
    return payload


def _openai_chat(messages: list[dict], num_predict: int) -> dict:
    return _timed_openai(_openai_payload(messages, num_predict))


def _timed_openai(payload: dict) -> dict:
    started = time.perf_counter()
    body = _openai_post(payload, _openai_key())
    elapsed_ns = int((time.perf_counter() - started) * _NS)
    return _stamp_duration(_chat_choice(body, "openai"), elapsed_ns)


def _openai_post(payload: dict, key: str) -> dict:
    request = urllib.request.Request(
        f"{_openai_base_url()}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_S) as response:
            body = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read(240).decode("utf-8", "replace").replace(key, "")
        raise NarrativeError(f"openai request failed: HTTP {exc.code} {detail}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise NarrativeError(f"openai request failed: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise NarrativeError("openai response was not valid JSON") from exc
    if not isinstance(body, dict):
        raise NarrativeError("openai response was not an object")
    return body


def _post_provider(payload: dict) -> dict:
    """Post a narrative request through the configured provider."""
    provider = _llm_provider()
    if provider == "deepseek":
        return _timed_deepseek(payload)
    if provider == "openai":
        return _timed_openai(payload)
    if provider == "grok":
        return _timed_grok(payload)
    return _post(payload)


def _deepseek_post(payload: dict, key: str) -> dict:
    request = urllib.request.Request(
        f"{_deepseek_base_url()}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_S) as response:
            body = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read(240).decode("utf-8", "replace").replace(key, "")
        raise NarrativeError(
            f"deepseek request failed: HTTP {exc.code} {detail}"
        ) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise NarrativeError(f"deepseek request failed: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise NarrativeError("deepseek response was not valid JSON") from exc
    if not isinstance(body, dict):
        raise NarrativeError("deepseek response was not an object")
    return body


def keep_only_model() -> None:
    """Unload every resident Ollama model other than the one this process calls.

    The default resident model is qwen3.5:4b. This does not pull a model.
    An unreachable Ollama host is ignored; the chat call reports that failure.
    """
    if _llm_provider() != "ollama":
        return
    resident = _model()
    try:
        loaded = _loaded_model_names()
    except OSError:
        return
    for name in loaded:
        if name == resident:
            continue
        try:
            _unload_model(name)
        except OSError:
            print(f"could not unload {name}", file=sys.stderr)


def _loaded_model_names() -> list[str]:
    body = _ollama_json(f"{_host()}/api/ps", None, 5)
    models = body.get("models")
    if not isinstance(models, list):
        return []
    names: list[str] = []
    for item in models:
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("model")
        if isinstance(name, str) and name.strip():
            names.append(name.strip())
    return names


def _unload_model(name: str) -> None:
    """Ask Ollama to drop one resident model. keep_alive 0 does not pull it."""
    _ollama_json(
        f"{_host()}/api/generate",
        {"model": name, "keep_alive": 0},
        10,
    )


def _ollama_json(url: str, payload: dict | None, timeout: float) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="GET" if data is None else "POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.load(response)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        raise OSError(str(exc)) from exc
    if not isinstance(body, dict):
        raise OSError("ollama response was not an object")
    return body


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
    except urllib.error.HTTPError as exc:
        detail = exc.read(240).decode("utf-8", "replace").strip()
        model = payload.get("model", "")
        raise NarrativeError(
            f"ollama request failed: HTTP {exc.code} for model {model} {detail}"
        ) from exc
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
    for key in ("prompt_eval_count", "eval_count", "reasoning_tokens"):
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
    body = _load_response_json(response, "narrative")
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


def _load_response_json(response: dict, label: str = "model") -> dict:
    """Load JSON from the assistant content, with a safe thinking fallback.

    Ollama models that support thinking can return the final answer in either
    ``message.content`` or ``message.thinking``. We prefer content, but try
    both so a valid structured answer is not discarded merely because the
    server used the alternate field. Every accepted candidate still goes
    through the same object parser and schema checks at the call site.
    """
    message = response.get("message")
    if not isinstance(message, dict):
        raise NarrativeError(f"{label} response has no message", retry_hint=True)
    candidates = []
    for key in ("content", "thinking"):
        value = message.get(key)
        if isinstance(value, str) and value.strip():
            candidates.append(value)
    if not candidates:
        raise NarrativeError(
            f"{label} response was not valid JSON: message content and thinking were empty",
            retry_hint=True,
        )
    errors = []
    for candidate in candidates:
        try:
            return _load_json_object(candidate, label)
        except NarrativeError as exc:
            errors.append(str(exc))
    detail = "; ".join(errors)
    raise NarrativeError(
        f"{label} response was not valid JSON: {detail}",
        retry_hint=True,
    )


def _load_json_object(content: str, label: str = "narrative") -> dict:
    text = content.strip()
    if not text:
        raise NarrativeError(
            f"{label} response was not valid JSON: empty response",
            retry_hint=True,
        )
    try:
        body = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        if start == -1:
            raise NarrativeError(_bad_json(text, label), retry_hint=True)
        try:
            body, _end = json.JSONDecoder().raw_decode(text[start:])
        except json.JSONDecodeError as exc:
            raise NarrativeError(_bad_json(text, label)) from exc
    if not isinstance(body, dict):
        raise NarrativeError(
            f"{label} response was not a JSON object",
            retry_hint=True,
        )
    return body


def _bad_json(text: str, label: str = "narrative") -> str:
    snippet = text.replace("\n", " ")[:160]
    return f"{label} response was not valid JSON: {snippet}"


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
