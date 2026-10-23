"""write_narrative posts one Ollama request. A bad body is posted again until the attempt budget is spent."""

import copy
import inspect
import io
import json
import urllib.error

import pytest

from story_guard import narrative
from story_guard.narrative import (
    NarrativeError,
    _load_response_json,
    keep_only_model,
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


def test_payload_includes_step_pairs_and_cases_without_steps(monkeypatch):
    seen = []

    def post(payload):
        seen.append(payload)
        return _reply(json.dumps(_good()))

    monkeypatch.setenv("STORY_GUARD_LLM", "ollama")
    monkeypatch.delenv("STORY_GUARD_MODEL", raising=False)
    monkeypatch.setattr("story_guard.narrative._post", post)
    score = _score()
    score["test_cases"] = [
        {
            "id": "TC-1",
            "title": "Successful login",
            "steps": [
                {
                    "action": "Enter valid credentials and select Login.",
                    "expected_result": "The user reaches the dashboard.",
                }
            ],
        },
        {"id": "TC-2", "title": "Legacy case without steps", "steps": []},
    ]
    score["test_suite_truncated"] = False

    result = write_narrative(score)
    sent_score = json.loads(seen[0]["messages"][1]["content"])

    assert sent_score["test_cases"][0]["steps"] == [
        {
            "action": "Enter valid credentials and select Login.",
            "expected_result": "The user reaches the dashboard.",
        }
    ]
    assert sent_score["test_cases"][1] == {
        "id": "TC-2",
        "title": "Legacy case without steps",
        "steps": [],
    }
    assert result["score"]["test_suite_truncated"] is False
    assert score["test_suite_truncated"] is False


def test_large_suite_is_truncated_and_recorded_on_returned_score(monkeypatch):
    seen = []

    def post(payload):
        seen.append(payload)
        return _reply(json.dumps(_good()))

    monkeypatch.setenv("STORY_GUARD_LLM", "ollama")
    monkeypatch.delenv("STORY_GUARD_MODEL", raising=False)
    monkeypatch.setattr("story_guard.narrative._post", post)
    score = _score()
    score["test_cases"] = [
        {
            "id": f"TC-{index}",
            "title": f"Case {index}",
            "steps": [
                {
                    "action": "Perform action. " * 400,
                    "expected_result": "Expected outcome. " * 400,
                }
            ],
        }
        for index in range(6)
    ]
    score["test_cases"].append(
        {"id": "TC-NO-STEPS", "title": "Case without steps", "steps": []}
    )
    score["test_suite_truncated"] = False

    result = write_narrative(score)
    sent_score = json.loads(seen[0]["messages"][1]["content"])
    estimated_prompt_tokens = (
        len(seen[0]["messages"][0]["content"])
        + len(seen[0]["messages"][1]["content"])
        + 2
    ) // 3

    assert result["score"]["test_suite_truncated"] is True
    assert sent_score["test_suite_truncated"] is True
    assert [case["id"] for case in sent_score["test_cases"]] == ["TC-NO-STEPS"]
    assert estimated_prompt_tokens <= narrative.PROMPT_TOKEN_TARGET
    assert len(score["test_cases"]) == 7


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


def test_generation_over_180_seconds_fails_the_story(tmp_path, monkeypatch):
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
    with pytest.raises(NarrativeError, match="story fixture-story"):
        write_narrative(_score())
    assert len(calls) == 1
    assert not out.exists()


def test_ollama_down_fails_the_story_without_a_retry(monkeypatch):
    calls = {"n": 0}

    def post(payload):
        calls["n"] += 1
        raise NarrativeError("ollama request failed: connection refused")

    monkeypatch.setattr("story_guard.narrative._post", post)
    with pytest.raises(NarrativeError, match="story fixture-story"):
        write_narrative(_score())
    assert calls["n"] == 1


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
    monkeypatch.delenv("STORY_GUARD_MODEL", raising=False)
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


def test_ollama_http_error_names_the_missing_model(monkeypatch):
    monkeypatch.setenv("STORY_GUARD_LLM", "ollama")
    monkeypatch.setenv("OLLAMA_MODEL", "missing-model")
    monkeypatch.delenv("STORY_GUARD_MODEL", raising=False)

    def fake_urlopen(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url,
            404,
            "Not Found",
            hdrs=None,
            fp=io.BytesIO(b'{"error":"model not found"}'),
        )

    monkeypatch.setattr("story_guard.narrative.urllib.request.urlopen", fake_urlopen)
    with pytest.raises(NarrativeError, match="missing-model"):
        ollama_chat([{"role": "user", "content": "Return JSON."}])


def test_grok_chat_posts_json_to_xai(monkeypatch):
    monkeypatch.setenv("STORY_GUARD_LLM", "grok")
    monkeypatch.setenv("XAI_API_KEY", "test-key")
    monkeypatch.delenv("XAI_MODEL", raising=False)
    monkeypatch.delenv("STORY_GUARD_MODEL", raising=False)
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
    monkeypatch.delenv("STORY_GUARD_MODEL", raising=False)
    monkeypatch.delenv("DEEPSEEK_BASE_URL", raising=False)
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
    assert seen["body"]["model"] == "deepseek-flash"
    assert seen["body"]["max_tokens"] == narrative.MAX_TOKENS
    assert seen["body"]["response_format"] == {"type": "json_object"}
    assert seen["body"]["thinking"] == {"type": "disabled"}
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


def test_chatgpt_narrative_uses_json_chat_completions(monkeypatch):
    monkeypatch.setenv("STORY_GUARD_LLM", "chatgpt")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-test-key")
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.setenv("STORY_GUARD_MODEL", "gpt-5.6-terra")
    seen = {}

    def fake_urlopen(request, timeout):
        seen["url"] = request.full_url
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
                "usage": {"prompt_tokens": 8, "completion_tokens": 7},
            }
        ).encode("utf-8")
        return _OllamaBody(raw)

    monkeypatch.setattr("story_guard.narrative.urllib.request.urlopen", fake_urlopen)
    result = write_narrative(_score())
    assert seen["url"] == "https://api.openai.com/v1/chat/completions"
    assert seen["body"]["model"] == "gpt-5.6-terra"
    assert seen["body"]["max_completion_tokens"] == (
        narrative.MAX_TOKENS + narrative.REASONING_TOKEN_RESERVE
    )
    assert seen["body"]["response_format"] == {"type": "json_object"}
    assert seen["body"]["reasoning_effort"] == "low"
    assert "temperature" not in seen["body"]
    assert "tools" not in seen["body"]
    assert seen["authorization"] == "Bearer openai-test-key"
    assert result["narrative"] == _good()
    assert narrative.configured_llm() == ("openai", "gpt-5.6-terra")


@pytest.mark.parametrize(
    "model",
    ["gpt-5.6-luna", "gpt-6-luna", "gpt-6-astra", "gpt-6.1-sol"],
)
def test_gpt_requests_enable_low_reasoning(monkeypatch, model):
    monkeypatch.setenv("STORY_GUARD_LLM", "chatgpt")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-test-key")
    monkeypatch.setenv("STORY_GUARD_MODEL", model)
    seen = {}

    def fake_urlopen(request, timeout):
        seen["body"] = json.loads(request.data.decode("utf-8"))
        raw = json.dumps(
            {
                "choices": [
                    {"message": {"role": "assistant", "content": "{\"ok\": true}"}}
                ],
                "usage": {"prompt_tokens": 2, "completion_tokens": 1},
            }
        ).encode("utf-8")
        return _OllamaBody(raw)

    monkeypatch.setattr("story_guard.narrative.urllib.request.urlopen", fake_urlopen)
    ollama_chat([{"role": "user", "content": "Return JSON."}], num_predict=256)
    assert seen["body"]["model"] == model
    assert seen["body"]["reasoning_effort"] == "low"
    assert "temperature" not in seen["body"]
    assert seen["body"]["max_completion_tokens"] == 256 + narrative.REASONING_TOKEN_RESERVE


def test_older_openai_model_keeps_temperature(monkeypatch):
    monkeypatch.setenv("STORY_GUARD_LLM", "chatgpt")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-test-key")
    monkeypatch.setenv("STORY_GUARD_MODEL", "gpt-4o")
    seen = {}

    def fake_urlopen(request, timeout):
        seen["body"] = json.loads(request.data.decode("utf-8"))
        raw = json.dumps(
            {
                "choices": [
                    {"message": {"role": "assistant", "content": "{\"ok\": true}"}}
                ],
                "usage": {"prompt_tokens": 2, "completion_tokens": 1},
            }
        ).encode("utf-8")
        return _OllamaBody(raw)

    monkeypatch.setattr("story_guard.narrative.urllib.request.urlopen", fake_urlopen)
    ollama_chat([{"role": "user", "content": "Return JSON."}], num_predict=256)
    assert "reasoning_effort" not in seen["body"]
    assert seen["body"]["temperature"] == narrative.TEMPERATURE
    assert seen["body"]["max_completion_tokens"] == 256


def _openai_completion(message: dict, usage: dict, finish_reason: str = "stop") -> bytes:
    return json.dumps(
        {
            "choices": [
                {"message": message, "finish_reason": finish_reason},
            ],
            "usage": usage,
        }
    ).encode("utf-8")


def test_openai_reasoning_json_comes_from_the_answer(monkeypatch):
    monkeypatch.setenv("STORY_GUARD_LLM", "chatgpt")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-test-key")
    monkeypatch.setenv("STORY_GUARD_MODEL", "gpt-6-astra")
    answer = json.dumps({"ok": True, "mapped_test_ids": ["121221"]})

    def fake_urlopen(request, timeout):
        return _OllamaBody(
            _openai_completion(
                {
                    "role": "assistant",
                    "content": [
                        {"type": "reasoning_text", "text": '{"ok": false}'},
                        {"type": "text", "text": answer},
                    ],
                    "reasoning_content": '{"ok": false}',
                },
                {
                    "prompt_tokens": 10,
                    "completion_tokens": 50,
                    "completion_tokens_details": {"reasoning_tokens": 40},
                },
            )
        )

    monkeypatch.setattr("story_guard.narrative.urllib.request.urlopen", fake_urlopen)
    response = ollama_chat([{"role": "user", "content": "Return JSON."}])
    assert response["message"]["content"] == answer
    assert "thinking" not in response["message"]
    assert response["eval_count"] == 10
    assert response["reasoning_tokens"] == 40
    assert _load_response_json(response) == {"ok": True, "mapped_test_ids": ["121221"]}
    assert narrative._token_count(response) == 60
    narrative._check_cap(response)


def test_openai_length_stop_with_no_answer_is_retried(monkeypatch):
    monkeypatch.setenv("STORY_GUARD_LLM", "chatgpt")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-test-key")
    monkeypatch.setenv("STORY_GUARD_MODEL", "gpt-6-astra")

    def fake_urlopen(request, timeout):
        return _OllamaBody(
            _openai_completion(
                {
                    "role": "assistant",
                    "content": "",
                    "reasoning_content": json.dumps({"ok": True}),
                },
                {
                    "prompt_tokens": 10,
                    "completion_tokens": 4096,
                    "completion_tokens_details": {"reasoning_tokens": 4096},
                },
                finish_reason="length",
            )
        )

    monkeypatch.setattr("story_guard.narrative.urllib.request.urlopen", fake_urlopen)
    with pytest.raises(NarrativeError, match="stopped before the JSON object") as caught:
        ollama_chat([{"role": "user", "content": "Return JSON."}])
    assert caught.value.retry_hint is True


def test_openai_chat_requires_an_api_key(monkeypatch):
    monkeypatch.setenv("STORY_GUARD_LLM", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("STORY_GUARD_MODEL", raising=False)
    with pytest.raises(NarrativeError, match="OPENAI_API_KEY"):
        ollama_chat([{"role": "user", "content": "Return JSON."}])


def test_story_guard_model_overrides_the_provider_model(monkeypatch):
    monkeypatch.setenv("STORY_GUARD_LLM", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-test-key")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-flash")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1/")
    monkeypatch.setenv("STORY_GUARD_MODEL", "deepseek-v4-pro")
    seen = {}

    def fake_urlopen(request, timeout):
        seen["url"] = request.full_url
        seen["body"] = json.loads(request.data.decode("utf-8"))
        raw = json.dumps(
            {
                "choices": [
                    {"message": {"role": "assistant", "content": "{\"ok\": true}"}}
                ],
                "usage": {"prompt_tokens": 2, "completion_tokens": 1},
            }
        ).encode("utf-8")
        return _OllamaBody(raw)

    monkeypatch.setattr("story_guard.narrative.urllib.request.urlopen", fake_urlopen)
    response = ollama_chat([{"role": "user", "content": "Return JSON."}], num_predict=256)
    assert seen["url"] == "https://api.deepseek.com/v1/chat/completions"
    assert seen["body"]["model"] == "deepseek-v4-pro"
    assert response["total_duration"] >= 0
    assert response["eval_duration"] == response["total_duration"]
    assert narrative.configured_llm() == ("deepseek", "deepseek-v4-pro")


def test_blank_story_guard_model_keeps_the_provider_default(monkeypatch):
    monkeypatch.setenv("STORY_GUARD_LLM", "ollama")
    monkeypatch.setenv("STORY_GUARD_MODEL", "   ")
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    assert narrative.configured_llm() == ("ollama", "qwen3.5:4b")


def test_grok_narrative_posts_to_xai(monkeypatch):
    monkeypatch.setenv("STORY_GUARD_LLM", "grok")
    monkeypatch.setenv("XAI_API_KEY", "test-key")
    monkeypatch.setenv("STORY_GUARD_MODEL", "grok-4")
    seen = {}

    def fake_urlopen(request, timeout):
        seen["url"] = request.full_url
        seen["body"] = json.loads(request.data.decode("utf-8"))
        raw = json.dumps(
            {
                "choices": [
                    {"message": {"role": "assistant", "content": json.dumps(_good())}}
                ],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2},
            }
        ).encode("utf-8")
        return _OllamaBody(raw)

    monkeypatch.setattr("story_guard.narrative.urllib.request.urlopen", fake_urlopen)
    result = write_narrative(_score())
    assert seen["url"] == narrative.GROK_CHAT_URL
    assert seen["body"]["model"] == "grok-4"
    assert seen["body"]["response_format"] == {"type": "json_object"}
    assert "format" not in seen["body"]
    assert result["narrative"] == _good()


class _OllamaBody:
    def __init__(self, raw: bytes):
        self._raw = raw

    def read(self, _n=-1):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def test_keep_only_model_unloads_every_model_except_qwen35_4b(monkeypatch):
    monkeypatch.setenv("STORY_GUARD_LLM", "ollama")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3.5:4b")
    seen = []

    def fake_urlopen(request, timeout):
        seen.append((request.full_url, request.get_method(), request.data))
        if request.full_url.endswith("/api/ps"):
            raw = json.dumps(
                {
                    "models": [
                        {"name": "qwen3.5:9b"},
                        {"name": "qwen3.5:4b"},
                        {"model": "phi4-mini"},
                    ]
                }
            ).encode("utf-8")
            return _OllamaBody(raw)
        return _OllamaBody(b'{"done": true}')

    monkeypatch.setattr("story_guard.narrative.urllib.request.urlopen", fake_urlopen)
    keep_only_model()

    assert not any("pull" in url for url, _method, _data in seen)
    posts = [
        (url, json.loads(data.decode("utf-8")))
        for url, method, data in seen
        if method == "POST" and data is not None
    ]
    assert posts == [
        (seen[1][0], {"model": "qwen3.5:9b", "keep_alive": 0}),
        (seen[2][0], {"model": "phi4-mini", "keep_alive": 0}),
    ]
    assert all(url.endswith("/api/generate") for url, _body in posts)
    assert seen[0][0].endswith("/api/ps")
    assert seen[0][1] == "GET"
    assert "/api/pull" not in inspect.getsource(narrative)


def test_keep_only_model_leaves_a_resident_qwen35_4b(monkeypatch):
    monkeypatch.setenv("STORY_GUARD_LLM", "ollama")
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    seen = []

    def fake_urlopen(request, timeout):
        seen.append(request.get_method())
        raw = json.dumps({"models": [{"name": "qwen3.5:4b"}]}).encode("utf-8")
        return _OllamaBody(raw)

    monkeypatch.setattr("story_guard.narrative.urllib.request.urlopen", fake_urlopen)
    keep_only_model()
    assert seen == ["GET"]


def test_keep_only_model_skips_a_hosted_provider(monkeypatch):
    monkeypatch.setenv("STORY_GUARD_LLM", "deepseek")

    def fail(*_args, **_kwargs):
        raise AssertionError("ollama was called")

    monkeypatch.setattr("story_guard.narrative.urllib.request.urlopen", fail)
    keep_only_model()


def test_keep_only_model_ignores_an_unreachable_host(monkeypatch, capsys):
    monkeypatch.delenv("STORY_GUARD_LLM", raising=False)
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:9")
    keep_only_model()
    assert capsys.readouterr().err == ""
