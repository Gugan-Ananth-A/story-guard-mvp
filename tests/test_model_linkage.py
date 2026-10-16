"""Live linkage is predicted per AC and is independent of fixture links."""

import json

from story_guard.analysis import analyze_live
from story_guard.render import _template_values


def _record():
    return {
        "id": "STORY-1",
        "title": "Login",
        "type": "User Story",
        "state": "New",
        "description": "",
        "area": "App",
        "iteration": "Sprint",
        "acceptance_criteria_raw": "present",
        "acceptance_criteria": [
            {"ac_id": "AC-01", "text": "Valid login redirects to home.", "testable": True, "flags": []},
            {"ac_id": "AC-02", "text": "The screen works.", "testable": True, "flags": []},
        ],
        "scenarios": [],
        "note": "",
        "tests": [
            {
                "id": "T1",
                "title": "Valid login redirects to home",
                "type": "happy",
                "mapped_ac_ids": ["AC-01"],
                "suite_id": "S1",
                "suite_name": "Functional",
            },
            {
                "id": "T2",
                "title": "Invalid login shows an error",
                "type": "negative",
                "mapped_ac_ids": [],
                "suite_id": "S1",
                "suite_name": "Functional",
            },
            {
                "id": "T3",
                "title": "Login works after refresh",
                "type": "adhoc",
                "mapped_ac_ids": [],
                "suite_id": "S2",
                "suite_name": "Resilience",
            },
        ],
        "bugs": [],
    }


def test_every_ac_is_checked_against_every_suite_and_quality_is_reported(monkeypatch):
    calls = []

    def fake_chat(messages, num_predict=8192):
        user = messages[1]["content"]
        payload = json.loads(user.split("\n", 1)[1])
        ac_id = payload["acceptance_criterion"]["ac_id"]
        suite_id = payload["suite"]["id"]
        calls.append((ac_id, suite_id, user))
        assert "mapped_ac_ids" not in user
        if ac_id == "AC-01":
            ids = ["T1"] if suite_id == "S1" else []
            quality = {"status": "good", "testable": True, "issues": []}
        else:
            ids = []
            quality = {
                "status": "needs_improvement",
                "testable": True,
                "issues": ["Expected result is vague"],
            }
        return {
            "message": {
                "content": json.dumps(
                    {
                        "ac_id": ac_id,
                        "mapped_test_ids": ids,
                        "coverage_status": "partial" if ids else "none",
                        "quality": quality,
                        "finding": f"No listed test checks {ac_id}." if not ids else f"{ac_id} is checked by T1.",
                    }
                )
            },
            "prompt_eval_count": 2,
            "eval_count": 3,
        }

    monkeypatch.setattr("story_guard.analysis.ollama_chat", fake_chat)
    result = analyze_live(_record())

    assert [(ac_id, suite_id) for ac_id, suite_id, _ in calls] == [
        ("AC-01", "S1"),
        ("AC-01", "S2"),
        ("AC-02", "S1"),
        ("AC-02", "S2"),
    ]
    rows = {row["ac_id"]: row for row in result["score"]["scenarios"]}
    assert rows["AC-01"]["mapped_test_ids"] == ["T1"]
    assert rows["AC-01"]["ac_quality"]["status"] == "good"
    assert rows["AC-02"]["mapped_test_ids"] == []
    assert rows["AC-02"]["row_status"] == "none"
    assert rows["AC-02"]["ac_quality"]["status"] == "needs_improvement"
    assert result["score"]["quality_good_count"] == 1
    assert result["score"]["quality_needs_review_count"] == 1
    assert result["token_count"] == 20


def test_empty_test_pack_still_gets_an_ac_quality_review(monkeypatch):
    record = _record()
    record["tests"] = []
    calls = []

    def fake_chat(messages, num_predict=8192):
        payload = json.loads(messages[1]["content"].split("\n", 1)[1])
        calls.append(payload)
        ac_id = payload["acceptance_criterion"]["ac_id"]
        return {
            "message": {
                "content": json.dumps(
                    {
                        "ac_id": ac_id,
                        "mapped_test_ids": [],
                        "coverage_status": "none",
                        "quality": {"status": "poor", "testable": False, "issues": ["Too vague"]},
                        "finding": f"No listed test checks {ac_id}.",
                    }
                )
            },
            "prompt_eval_count": 1,
            "eval_count": 1,
        }

    monkeypatch.setattr("story_guard.analysis.ollama_chat", fake_chat)
    result = analyze_live(record)

    assert len(calls) == 2
    assert all(payload["tests"] == [] for payload in calls)
    assert all(row["ac_quality"]["status"] == "poor" for row in result["score"]["scenarios"])


def test_report_template_values_include_model_linkage_and_ac_quality():
    record = _record()
    score = {
        "story_id": "STORY-1",
        "title": "Login",
        "source": "ADO dummy project",
        "ac_field": "present",
        "scenario_count": 1,
        "scenarios": [
            {
                "ac_id": "AC-01",
                "mapped_test_ids": ["T1"],
                "row_status": "partial",
                "ac_quality": {
                    "status": "needs_improvement",
                    "testable": True,
                    "issues": ["Expected result is vague"],
                },
                "model_coverage_status": "partial",
            }
        ],
        "test_count": 1,
        "mapped_count": 1,
        "adequate_count": 0,
        "partial_count": 1,
        "none_count": 0,
        "quality_good_count": 0,
        "quality_needs_review_count": 1,
        "coverage_by_type": {},
        "bug_count": 0,
        "bugs": [],
        "rag": "Amber",
        "health": "No open bugs",
        "rule_ids": [],
    }
    values = _template_values(score, {}, record, generated_at="now")

    assert "quality: needs_improvement" in values["ac_review"]
    assert "model coverage status: partial" in values["ac_review"]
    assert "Model-predicted mapped ACs: 1" in values["ac_test_mapping"]
    assert "AC quality: 0 good; 1 need review" in values["coverage_by_type"]
