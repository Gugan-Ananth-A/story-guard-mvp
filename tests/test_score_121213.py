"""Health counts for story 121213, read from fixtures/FIX-121213.json."""

import json
from pathlib import Path

from story_guard.score import SR_1, SR_2, score_health

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "FIX-121213.json"

_SCORE_KEYS = {
    "story_id",
    "title",
    "source",
    "ac_field",
    "scenario_count",
    "scenarios",
    "test_count",
    "mapped_count",
    "bug_count",
    "bugs",
    "coverage_by_type",
    "rag",
    "rule_id",
    "note",
}


def _load() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_score_fixture_counts():
    record = _load()
    score = score_health(record)
    assert SR_1 == "SR-1"
    assert SR_2 == "SR-2"
    assert set(score) == _SCORE_KEYS
    assert score["story_id"] == "121213"
    assert score["title"] == "SNAP Login Screen"
    assert score["source"] == "fixture"
    assert score["ac_field"] == "empty"
    assert score["scenario_count"] == 8
    assert [row["ac_id"] for row in score["scenarios"]] == [f"AC-{i}" for i in range(1, 9)]
    assert all(row["covered"] is False for row in score["scenarios"])
    assert all(row["mapped_test_ids"] == [] for row in score["scenarios"])
    assert score["test_count"] == 18
    assert score["mapped_count"] == 0
    assert score["bug_count"] == 0
    assert score["bugs"] == []
    assert score["coverage_by_type"] == {
        "happy": 0,
        "negative": 0,
        "edge": 0,
        "security": 0,
        "adhoc": 0,
        "unset": 18,
    }
    assert score["rag"] == "Red"
    assert score["rule_id"] == "SR-2"
    assert score["note"] == record["note"]
    scenario_lines = [
        line for line in record["description"].splitlines() if line.lstrip().startswith("Scenario:")
    ]
    assert len(scenario_lines) == 8


def test_score_empty_mapped_ac_ids_covers_nothing():
    record = _load()
    tests = [dict(test) for test in record["tests"]]
    tests[0] = dict(tests[0], mapped_ac_ids=["AC-1"])
    tests[1] = dict(tests[1], mapped_ac_ids=[])
    record = dict(record, tests=tests)
    score = score_health(record)
    empty_id = tests[1]["id"]
    mapped_id = tests[0]["id"]
    assert all(empty_id not in row["mapped_test_ids"] for row in score["scenarios"])
    assert score["scenarios"][0]["covered"] is True
    assert score["scenarios"][0]["mapped_test_ids"] == [mapped_id]
    assert all(row["covered"] is False for row in score["scenarios"][1:])
    assert score["mapped_count"] == 1
    assert score["rag"] == ""
    assert score["rule_id"] == ""


def test_score_ac_field_does_not_hide_scenarios():
    record = dict(_load(), acceptance_criteria_raw="Given a registered user")
    score = score_health(record)
    assert score["ac_field"] == "present"
    assert score["scenario_count"] == 8
    assert score["rag"] == "Red"
    assert score["rule_id"] == "SR-2"


def test_score_coverage_by_type_uses_the_type_field():
    record = _load()
    assert score_health(record)["coverage_by_type"]["unset"] == 18
    tests = [dict(test) for test in record["tests"]]
    tests[0] = dict(tests[0], type="happy")
    tests[1] = dict(tests[1], type="negative")
    score = score_health(dict(record, tests=tests))
    assert score["coverage_by_type"]["happy"] == 1
    assert score["coverage_by_type"]["negative"] == 1
    assert score["coverage_by_type"]["unset"] == 16


def test_score_stand_in_text_is_labeled():
    text = (ROOT / "docs" / "rag-stand-in.md").read_text(encoding="utf-8")
    paragraphs = [part.strip() for part in text.split("\n\n") if part.strip()]
    assert "stand-in" in paragraphs[0].lower()
    assert "TBD-HEALTH-1" in paragraphs[1]
    assert "still open" in paragraphs[1]
    assert "sprint stand-in" in paragraphs[1]
    assert "not the published RAG rule" in paragraphs[1]
    assert (
        "A scenario is covered only when some test lists its `ac_id` in `mapped_ac_ids`."
        in text
    )
    assert "An empty list covers nothing." in text
    assert "Story health is the highest open bug priority." in text
    assert "SR-2 is why 121213 is No open bugs." in text
    assert "The row does not say \"partially covered\"." in text
