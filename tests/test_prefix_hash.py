"""Verify the production rubric loader returns stable, story-neutral content."""

import hashlib
import json
from pathlib import Path

from story_guard.cli import main
from story_guard.prefix import load_prefix

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "FIX-121213.json"


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        return [text for item in value for text in _strings(item)]
    if isinstance(value, dict):
        return [text for item in value.values() for text in _strings(item)]
    return []


def test_rubric_prefix_hash_is_stable_and_story_agnostic() -> None:
    first_read = load_prefix()
    second_read = load_prefix()
    first_content = first_read.encode("utf-8")
    second_content = second_read.encode("utf-8")
    first_hash = hashlib.sha256(first_content).hexdigest()
    second_hash = hashlib.sha256(second_content).hexdigest()

    assert first_read == second_read
    assert first_content == second_content
    assert first_hash == second_hash

    prefix_text = first_read.casefold()
    assert "rubric_version: rubric_v1" in prefix_text
    assert '"headline"' in prefix_text
    assert '"sections"' in prefix_text
    assert '"actions"' in prefix_text
    assert "cite its computed counts" in prefix_text
    assert "invent coverage" in prefix_text
    assert "mapped_ac_ids" in prefix_text
    assert "story health" in prefix_text
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert all(marker.casefold() not in prefix_text for marker in _strings(fixture))
    assert "121213" not in prefix_text
    assert "8 scenarios" not in prefix_text
    assert "18 tests" not in prefix_text
    assert "0 mapped" not in prefix_text
    assert "0 bugs" not in prefix_text


def test_two_generate_runs_record_the_same_prefix_hash(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setattr("story_guard.graph.artifacts_dir", lambda: tmp_path)
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)

    def offline_narrative(score):
        return {
            "score": score,
            "narrative": {
                "headline": "Coverage remains on the score.",
                "sections": [],
                "actions": [
                    {"owner": "QA", "text": "Review explicit coverage links."},
                    {"owner": "Dev", "text": "Keep the recorded health value."},
                    {"owner": "PO", "text": "Review the story requirements."},
                ],
            },
            "token_count": 1,
            "narrative_latency_ms": 1,
        }

    monkeypatch.setattr("story_guard.graph.request_narrative", offline_narrative)
    assert main(["generate", "--story-id", "121213"]) == 0
    assert main(["generate", "--story-id", "121213"]) == 0
    capsys.readouterr()

    lines = [json.loads(line) for line in (tmp_path / "runs.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 2
    assert lines[0]["prefix_sha256"] == lines[1]["prefix_sha256"]
    assert lines[0]["prefix_sha256"] == hashlib.sha256(load_prefix().encode("utf-8")).hexdigest()
    assert "121213" not in load_prefix()
