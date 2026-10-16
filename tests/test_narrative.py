"""write_narrative posts one Ollama request. A bad body is posted again until the attempt budget is spent."""

import copy
import inspect
import json

import pytest

from story_guard import narrative
from story_guard.narrative import (
    NarrativeError,
    _load_response_json,
    ollama_chat,
    write_narrative,
)
from story_guard.prefix import load_prefix


def _score() -> dict:
    return {
        "story_id": "fixture-story",
        "health": "No open bugs",
        "health_band": "No open bugs",
        "scenario_count": 1,
        "test_count": 1,
        "mapped_count": 0,
        "bug_count": 0,
        "none_count": 1,
        "adequate_count": 0,
        "partial_count": 0,
        "rag": "absent",
        "scenarios": [
            {"ac_id": "AC-X", "mapped_test_ids": [], "mapped_ac_ids": []},
        ],
    }


def _good() -> dict:
    return {
        "headline": "No open bugs",
        "observations": [
            "Story health is No open bugs.",
            "The score records 1 scenario and 1 test.",
            "Mapped count is 0.",
            "Bug count is 0 and the none count is 1.",
        ],
        "sections": [{"name": "Story health", "prose": "Story health is No open bugs."}],
        "actions": [
            {"owner": "QA", "text": "Map tests before counting coverage."},
            {"owner": "Dev", "text": "Keep the story health from the score."},
            {"owner": "PO", "text": "Write acceptance criteria."},
        ],
    }


def _reply(content: str, **extra) -> dict:
    body = {"message": {"content": content}, "done_reason": "stop", "eval_count": 12}
    body.update(extra)
    return body


def test_token_count_is_the_successful_narrative_call(monkeypatch):
    calls = {"n": 0}

    def post(payload):
        calls["n"] += 1
        if calls["n"] == 1:
            return _reply("not-json", prompt_eval_count=5, eval_count=5)
        return _reply(json.dumps(_good()), prompt_eval_count=10, eval_count=4)

    monkeypatch.setattr("story_guard.narrative._post", post)
    result = write_narrative(_score())
    assert result["token_count"] == 14
    assert result["narrative_latency_ms"] >= 0


def test_structured_parser_accepts_ollama_thinking_fallback():
    response = {
        "message": {
            "content": "",
            "thinking": json.dumps(_good()),
        }
    }

    assert _load_response_json(response, "narrative") == _good()


def test_empty_structured_response_has_a_corrective_error():
    with pytest.raises(NarrativeError, match="content and thinking were empty"):
        _load_response_json({"message": {"content": "", "thinking": ""}}, "analysis")


def test_temperature_is_fixed_on_the_function():
    assert narrative.TEMPERATURE == 0.1
    assert list(inspect.signature(write_narrative).parameters) == ["score"]


def test_request_is_prefix_then_score_without_tools(monkeypatch):
    seen = []

    def post(payload):
        seen.append(payload)
        return _reply(json.dumps(_good()))

    monkeypatch.setattr("story_guard.narrative._post", post)
    score = _score()
    result = write_narrative(score)
    assert len(seen) == 1
    payload = seen[0]
    assert payload["format"] == "json"
    assert payload["stream"] is False
    assert payload["think"] is False
    assert "tools" not in payload
    assert payload["options"]["num_ctx"] == 8192
    assert payload["options"]["temperature"] == 0.1
    assert payload["options"]["num_predict"] == 8192
    assert [message["role"] for message in payload["messages"]] == ["system", "user"]
    assert payload["messages"][0]["content"] == load_prefix()
    assert json.loads(payload["messages"][1]["content"]) == score
    raw = json.dumps(payload)
    assert raw.index("rubric_version") < raw.index("fixture-story")
    assert result["score"] is score
    assert result["narrative"] == _good()


def test_invalid_json_retries_until_the_budget_is_spent(tmp_path, monkeypatch):
    calls = []

    def post(payload):
        calls.append(json.dumps(payload, sort_keys=True))
        return _reply("not-json")

    monkeypatch.setattr("story_guard.narrative._post", post)
    out = tmp_path / "121213.pdf"
    with pytest.raises(NarrativeError):
        write_narrative(_score())
    assert len(calls) == narrative.ATTEMPTS
    assert len(set(calls)) == 2
    assert "previous JSON was rejected" in json.loads(calls[1])["messages"][2]["content"]
    assert not out.exists()
    assert not (tmp_path / "121213.md").exists()


def test_health_colour_claim_is_rejected_and_then_accepted(monkeypatch):
    seen = []

    def post(payload):
        seen.append(payload)
        if len(seen) == 1:
            rejected = _good()
            rejected["actions"] = list(rejected["actions"])
            rejected["actions"][0] = {
                "owner": "QA",
                "text": "Move the health band from Red to a green state by mapping tests.",
            }
            return _reply(json.dumps(rejected))
        return _reply(json.dumps(_good()))

    monkeypatch.setattr("story_guard.narrative._post", post)
    result = write_narrative(_score())
    assert result["narrative"] == _good()
    assert "not a RAG colour" in seen[1]["messages"][2]["content"]


def test_rule_miss_is_sent_back_before_the_next_attempt(monkeypatch):
    seen = []

    def post(payload):
        seen.append(payload)
        if len(seen) == 1:
            rejected = _good()
            rejected["observations"] = [
                "Story health is Critical.",
                "The score records 1 scenario and 1 test.",
                "Mapped count is 0.",
                "Bug count is 0 and the none count is 1.",
            ]
            return _reply(json.dumps(rejected))
        return _reply(json.dumps(_good()))

    monkeypatch.setattr("story_guard.narrative._post", post)
    result = write_narrative(_score())
    assert result["narrative"] == _good()
    assert len(seen) == 2
    assert [message["role"] for message in seen[0]["messages"]] == ["system", "user"]
    assert [message["role"] for message in seen[1]["messages"]] == ["system", "user", "user"]
    assert "story health" in seen[1]["messages"][2]["content"].casefold()


def test_schema_miss_then_valid_json_keeps_the_body(monkeypatch):
    calls = {"n": 0}

    def post(payload):
        calls["n"] += 1
        if calls["n"] == 1:
            return _reply('{"headline": "only"}')
        return _reply(json.dumps(_good()))

    monkeypatch.setattr("story_guard.narrative._post", post)
    score = _score()
    snapshot = copy.deepcopy(score)
    result = write_narrative(score)
    assert calls["n"] == 2
    assert result["narrative"] == _good()
    assert result["score"] is score
    assert score == snapshot
    assert score["rag"] == "absent"
    assert score["mapped_count"] == 0
    assert score["scenarios"][0]["mapped_ac_ids"] == []


def test_token_cap_retries_then_keeps_a_short_reply(monkeypatch):
    calls = {"n": 0}

    def post(payload):
        calls["n"] += 1
        if calls["n"] == 1:
            return _reply(json.dumps(_good()), eval_count=8192)
        return _reply(json.dumps(_good()), eval_count=20)

    monkeypatch.setattr("story_guard.narrative._post", post)
    result = write_narrative(_score())
    assert calls["n"] == 2
    assert result["narrative"]["headline"] == "No open bugs"


def test_second_timeout_raises(tmp_path, monkeypatch):
    calls = []

    def post(payload):
        calls.append(payload)
        return _reply(
            json.dumps(_good()),
            load_duration=0,
            total_duration=181_000_000_000,
        )

    monkeypatch.setattr("story_guard.narrative._post", post)
    out = tmp_path / "report.pdf"
    with pytest.raises(NarrativeError):
        write_narrative(_score())
    assert len(calls) == narrative.ATTEMPTS
    assert len({json.dumps(payload, sort_keys=True) for payload in calls}) == 1
    assert not out.exists()


def test_cold_start_is_outside_the_generation_cap(monkeypatch):
    def post(payload):
        return _reply(
            json.dumps(_good()),
            load_duration=120_000_000_000,
            total_duration=130_000_000_000,
            eval_count=30,
        )

    monkeypatch.setattr("story_guard.narrative._post", post)
    result = write_narrative(_score())
    assert result["narrative"]["actions"][0]["owner"] == "QA"


def test_host_and_model_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:9999/")
    monkeypatch.setenv("OLLAMA_MODEL", "phi4-mini")
    monkeypatch.delenv("ADO_PAT", raising=False)
    seen = {}

    class _Body:
        def __init__(self, raw: bytes):
            self._raw = raw

        def read(self, _n=-1):
            return self._raw

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def fake_urlopen(request, timeout):
        seen["url"] = request.full_url
        seen["timeout"] = timeout
        seen["body"] = json.loads(request.data.decode("utf-8"))
        seen["header_names"] = [name.lower() for name, _value in request.header_items()]
        raw = json.dumps(_reply(json.dumps(_good()))).encode("utf-8")
        return _Body(raw)

    monkeypatch.setattr("story_guard.narrative.urllib.request.urlopen", fake_urlopen)
    write_narrative(_score())
    assert seen["url"] == "http://127.0.0.1:9999/api/chat"
    assert seen["timeout"] == narrative.HTTP_TIMEOUT_S
    assert seen["body"]["model"] == "phi4-mini"
    assert "authorization" not in seen["header_names"]
    assert "tools" not in seen["body"]


def test_grok_chat_posts_json_to_xai(monkeypatch):
    monkeypatch.setenv("STORY_GUARD_LLM", "grok")
    monkeypatch.setenv("XAI_API_KEY", "test-key")
    monkeypatch.delenv("XAI_MODEL", raising=False)
    seen = {}

    class _Body:
        def __init__(self, raw: bytes):
            self._raw = raw

        def read(self, _n=-1):
            return self._raw

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def fake_urlopen(request, timeout):
        seen["url"] = request.full_url
        seen["timeout"] = timeout
        seen["body"] = json.loads(request.data.decode("utf-8"))
        seen["authorization"] = request.get_header("Authorization")
        raw = json.dumps(
            {
                "choices": [{"message": {"role": "assistant", "content": "{\"ok\": true}"}}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 4},
            }
        ).encode("utf-8")
        return _Body(raw)

    monkeypatch.setattr("story_guard.narrative.urllib.request.urlopen", fake_urlopen)
    response = ollama_chat(
        [{"role": "user", "content": "Return one JSON object."}],
        num_predict=512,
    )
    assert seen["url"] == narrative.GROK_CHAT_URL
    assert seen["timeout"] == narrative.HTTP_TIMEOUT_S
    assert seen["body"]["model"] == "grok-4.7"
    assert seen["body"]["response_format"] == {"type": "json_object"}
    assert seen["body"]["max_tokens"] == 512
    assert seen["body"]["store"] is False
    assert "tools" not in seen["body"]
    assert seen["authorization"] == "Bearer test-key"
    assert response["message"]["content"] == "{\"ok\": true}"
    assert response["prompt_eval_count"] == 11
    assert response["eval_count"] == 4


def test_grok_chat_requires_an_api_key(monkeypatch):
    monkeypatch.setenv("STORY_GUARD_LLM", "grok")
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    with pytest.raises(NarrativeError, match="XAI_API_KEY"):
        ollama_chat([{"role": "user", "content": "{}"}])


def test_deepseek_narrative_uses_json_chat_completions(monkeypatch):
    monkeypatch.setenv("STORY_GUARD_LLM", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-test-key")
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)
    seen = {}

    class _Body:
        def __init__(self, raw: bytes):
            self._raw = raw

        def read(self, _n=-1):
            return self._raw

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def fake_urlopen(request, timeout):
        seen["url"] = request.full_url
        seen["timeout"] = timeout
        seen["body"] = json.loads(request.data.decode("utf-8"))
        seen["authorization"] = request.get_header("Authorization")
        raw = json.dumps(
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(_good()),
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 11, "completion_tokens": 4},
            }
        ).encode("utf-8")
        return _Body(raw)

    monkeypatch.setattr("story_guard.narrative.urllib.request.urlopen", fake_urlopen)
    result = write_narrative(_score())

    assert seen["url"] == "https://api.deepseek.com/chat/completions"
    assert seen["timeout"] == narrative.HTTP_TIMEOUT_S
    assert seen["body"]["model"] == "deepseek-chat"
    assert seen["body"]["max_tokens"] == narrative.MAX_TOKENS
    assert seen["body"]["response_format"] == {"type": "json_object"}
    assert seen["body"]["stream"] is False
    assert "think" not in seen["body"]
    assert seen["authorization"] == "Bearer deepseek-test-key"
    assert result["narrative"] == _good()
    assert result["token_count"] == 15


def test_deepseek_chat_requires_an_api_key(monkeypatch):
    monkeypatch.setenv("STORY_GUARD_LLM", "deepseek")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(NarrativeError, match="DEEPSEEK_API_KEY"):
        ollama_chat([{"role": "user", "content": "Return JSON."}])
