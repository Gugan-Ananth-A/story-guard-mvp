"""A successful generate records one local line. LangSmith runs only with a key."""

import hashlib
import json

import pytest

from story_guard.cli import main
from story_guard.prefix import load_prefix
from story_guard.trace import _send_trace, record_success


def _fake_narrative(score):
    return {
        "score": score,
        "narrative": {
            "headline": "No open bugs",
            "sections": [{"name": "Story health", "prose": "Health is No open bugs."}],
            "actions": [
                {"owner": "QA", "text": "Map the scenarios."},
                {"owner": "Dev", "text": "Keep the recorded health."},
                {"owner": "PO", "text": "Write the acceptance criteria."},
            ],
        },
        "token_count": 40,
        "narrative_latency_ms": 12,
    }


def _generate(monkeypatch, tmp_path):
    monkeypatch.delenv("ADO_PAT", raising=False)
    monkeypatch.setattr("story_guard.graph.artifacts_dir", lambda: tmp_path)
    monkeypatch.setattr("story_guard.graph.request_narrative", _fake_narrative)
    assert main(["generate", "--story-id", "121213"]) == 0


def _line(tmp_path) -> dict:
    text = (tmp_path / "runs.jsonl").read_text(encoding="utf-8")
    rows = [json.loads(row) for row in text.splitlines() if row.strip()]
    assert len(rows) == 1
    return rows[0]


@pytest.mark.parametrize("key", [None, "", "   "])
def test_empty_key_makes_zero_langsmith_calls(monkeypatch, tmp_path, capsys, key):
    if key is None:
        monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    else:
        monkeypatch.setenv("LANGSMITH_API_KEY", key)
    calls = []
    monkeypatch.setattr(
        "story_guard.trace._send_trace",
        lambda api_key, line: calls.append((api_key, line)),
    )
    _generate(monkeypatch, tmp_path)
    assert calls == []
    line = _line(tmp_path)
    assert line == {
        "story_id": "121213",
        "token_count": 40,
        "narrative_latency_ms": 12,
        "prefix_sha256": hashlib.sha256(load_prefix().encode("utf-8")).hexdigest(),
    }
    assert "121213" in (tmp_path / "121213.md").read_text(encoding="utf-8")
    capsys.readouterr()


def test_set_key_makes_one_langsmith_call(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("LANGSMITH_API_KEY", "test-key")
    calls = []
    monkeypatch.setattr(
        "story_guard.trace._send_trace",
        lambda api_key, line: calls.append((api_key, line)),
    )
    _generate(monkeypatch, tmp_path)
    assert len(calls) == 1
    api_key, line = calls[0]
    assert api_key == "test-key"
    assert line["story_id"] == "121213"
    assert line["token_count"] == 40
    assert line["narrative_latency_ms"] == 12
    assert line["prefix_sha256"] == hashlib.sha256(load_prefix().encode("utf-8")).hexdigest()
    saved = (tmp_path / "runs.jsonl").read_text(encoding="utf-8")
    report = (tmp_path / "121213.md").read_text(encoding="utf-8")
    assert "test-key" not in saved
    assert "test-key" not in report
    captured = capsys.readouterr()
    assert "test-key" not in captured.out
    assert "test-key" not in captured.err


def test_langsmith_failure_still_completes(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("LANGSMITH_API_KEY", "test-key")

    def boom(api_key, line):
        raise OSError("offline")

    monkeypatch.setattr("story_guard.trace._send_trace", boom)
    _generate(monkeypatch, tmp_path)
    assert _line(tmp_path)["story_id"] == "121213"
    assert (tmp_path / "121213.md").is_file()
    captured = capsys.readouterr()
    assert "test-key" not in captured.err
    assert "not sent" in captured.err


def test_send_trace_posts_one_run_without_the_key_in_the_body(monkeypatch):
    seen = {}

    class _Body:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _n=-1):
            return b""

    def fake_urlopen(request, timeout):
        seen["url"] = request.full_url
        seen["timeout"] = timeout
        seen["headers"] = {name.lower(): value for name, value in request.header_items()}
        seen["body"] = json.loads(request.data.decode("utf-8"))
        return _Body()

    monkeypatch.setenv("LANGSMITH_PROJECT", "story-guard")
    monkeypatch.delenv("LANGSMITH_ENDPOINT", raising=False)
    monkeypatch.setattr("story_guard.trace.urllib.request.urlopen", fake_urlopen)
    _send_trace(
        "test-key",
        {"story_id": "121213", "token_count": 40, "narrative_latency_ms": 12},
    )
    assert seen["url"] == "https://api.smith.langchain.com/runs"
    assert seen["timeout"] == 10
    assert seen["headers"]["x-api-key"] == "test-key"
    body = seen["body"]
    assert body["run_type"] == "chain"
    assert body["name"] == "story-guard generate"
    assert body["session_name"] == "story-guard"
    assert body["inputs"] == {"story_id": "121213"}
    assert body["outputs"]["token_count"] == 40
    assert "test-key" not in json.dumps(body)


def test_two_successes_append_two_lines(tmp_path, monkeypatch):
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.setattr("story_guard.trace.runs_path", lambda: tmp_path / "runs.jsonl")
    record_success("121213", 10, 20)
    record_success("121213", 11, 21)
    rows = [
        json.loads(row)
        for row in (tmp_path / "runs.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert rows == [
        {
            "story_id": "121213",
            "token_count": 10,
            "narrative_latency_ms": 20,
            "prefix_sha256": hashlib.sha256(load_prefix().encode("utf-8")).hexdigest(),
        },
        {
            "story_id": "121213",
            "token_count": 11,
            "narrative_latency_ms": 21,
            "prefix_sha256": hashlib.sha256(load_prefix().encode("utf-8")).hexdigest(),
        },
    ]
