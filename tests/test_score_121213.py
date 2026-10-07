"""Health counts for story 121213, read from fixtures/FIX-121213.json."""

import json
from pathlib import Path

from story_guard.score import SR_1, SR_2, SR_3, score_health

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
    "open_bug_count",
    "escaped_bug_count",
    "open_bugs_by_priority",
    "adequate_count",
    "partial_count",
    "none_count",
    "bugs",
    "coverage_by_type",
    "health",
    "health_band",
    "rule_ids",
    "note",
}


def _load() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_score_fixture_counts():
    record = _load()
    score = score_health(record)
    assert SR_1 == "SR-1"
    assert SR_2 == "SR-2"
    assert SR_3 == "SR-3"
    assert set(score) == _SCORE_KEYS
    assert score["story_id"] == "121213"
    assert score["title"] == "SNAP Login Screen"
    assert score["source"] == "fixture"
    assert score["ac_field"] == "empty"
    assert score["scenario_count"] == 8
    assert [row["ac_id"] for row in score["scenarios"]] == [f"AC-{i}" for i in range(1, 9)]
    assert all(row["covered"] is False for row in score["scenarios"])
    assert all(row["mapped_test_ids"] == [] for row in score["scenarios"])
    assert all(row["depth"] == "None" for row in score["scenarios"])
    assert all(row["gap"] == "No coverage" for row in score["scenarios"])
    assert all(row["row_status"] == "none" for row in score["scenarios"])
    assert score["test_count"] == 18
    assert score["mapped_count"] == 0
    assert score["bug_count"] == 0
    assert score["open_bug_count"] == 0
    assert score["escaped_bug_count"] == 0
    assert score["open_bugs_by_priority"] == {"P1": 0, "P2": 0, "P3": 0, "P4": 0}
    assert score["adequate_count"] == 0
    assert score["partial_count"] == 0
    assert score["none_count"] == 8
    assert score["bugs"] == []
    assert score["coverage_by_type"] == {
        "happy": 0,
        "negative": 0,
        "edge": 0,
        "security": 0,
        "adhoc": 0,
        "unset": 18,
    }
    assert score["health"] == "No open bugs"
    assert score["health_band"] == "No open bugs"
    assert score["rule_ids"] == ["SR-1", "SR-2", "SR-3"]
    assert "rag" not in score
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
    assert score["scenarios"][0]["row_status"] == "partial"
    assert "partially covered" not in score["scenarios"][0]["gap"]
    assert all(row["covered"] is False for row in score["scenarios"][1:])
    assert score["mapped_count"] == 1
    assert score["health"] == "No open bugs"
    assert score["none_count"] == 7
    assert score["partial_count"] == 1


def test_score_ac_field_does_not_hide_scenarios():
    record = dict(_load(), acceptance_criteria_raw="Given a registered user")
    score = score_health(record)
    assert score["ac_field"] == "present"
    assert score["scenario_count"] == 8
    assert score["health"] == "No open bugs"
    assert score["health_band"] == "No open bugs"


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


def test_open_p1_sets_critical_at_risk():
    record = _load()
    record["bugs"] = [
        {
            "id": "B-1",
            "title": "Login accepts a blank password",
            "severity": "Critical",
            "priority": "P1",
            "status": "Open",
            "age": "1",
            "found_in": "QA",
            "linked_story_id": "121213",
            "linked_tc_id": "121216",
        }
    ]
    score = score_health(record)
    assert score["health"] == "Critical"
    assert score["health_band"] == "At Risk"
    assert score["bug_count"] == 1
    assert score["open_bug_count"] == 1
    assert score["open_bugs_by_priority"] == {"P1": 1, "P2": 0, "P3": 0, "P4": 0}
    assert score["escaped_bug_count"] == 0
    assert score["none_count"] == 8


def test_resolved_bug_does_not_raise_story_health():
    record = _load()
    record["bugs"] = [
        {
            "id": "B-2",
            "title": "Old login defect",
            "severity": "Critical",
            "priority": "P1",
            "status": "Resolved",
            "age": "20",
            "found_in": "UAT",
            "linked_story_id": "121213",
            "linked_tc_id": "",
        }
    ]
    score = score_health(record)
    assert score["health"] == "No open bugs"
    assert score["open_bug_count"] == 0
    assert score["bug_count"] == 1
    assert score["escaped_bug_count"] == 1
    assert score["open_bugs_by_priority"]["P1"] == 0


def test_three_mapped_types_make_one_row_adequate():
    record = _load()
    tests = [dict(test) for test in record["tests"]]
    tests[0] = dict(tests[0], type="happy", mapped_ac_ids=["AC-1"])
    tests[1] = dict(tests[1], type="negative", mapped_ac_ids=["AC-1"])
    tests[2] = dict(tests[2], type="adhoc", mapped_ac_ids=["AC-1"])
    score = score_health(dict(record, tests=tests))
    row = score["scenarios"][0]
    assert row["row_status"] == "adequate"
    assert row["gap"] == "Adequate"
    assert row["depth"] == "\n".join(
        [
            "Positive scenarios are covered",
            "Negative scenarios are covered",
            "Adhoc scenarios are covered",
        ]
    )
    assert "partially covered" not in row["gap"]
    assert score["adequate_count"] == 1
    assert score["partial_count"] == 0
    assert score["none_count"] == 7
    assert all(other["row_status"] == "none" for other in score["scenarios"][1:])
    assert score["health"] == "No open bugs"


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
