"""Live analysis keeps fetched counts. Health and coverage rows stay on the score."""

import json

from story_guard.analysis import analyze_live, result_from_judgment


def _record():
    return {
        "id": "123086",
        "title": "SNAP Login Screen - Admin",
        "type": "User Story",
        "state": "New",
        "description": "",
        "area": "Ecom MVP",
        "iteration": "",
        "acceptance_criteria_raw": "present",
        "acceptance_criteria": [
            {"ac_id": "AC-01", "text": "Admin signs in", "testable": True, "flags": []},
            {"ac_id": "AC-02", "text": "Admin is rejected", "testable": True, "flags": []},
        ],
        "scenarios": [],
        "note": "",
        "source": "ADO dummy project",
        "tests": [
            {
                "id": "121216",
                "title": "Valid login",
                "type": "",
                "mapped_ac_ids": ["AC-01"],
                "last_result": "",
                "last_result_at": None,
                "linked_bug_ids": [],
            },
            {
                "id": "121220",
                "title": "Bad password",
                "type": "",
                "mapped_ac_ids": [],
                "last_result": "",
                "last_result_at": None,
                "linked_bug_ids": [],
            },
        ],
        "bugs": [
            {
                "id": "122590",
                "title": "Password field is not accepting special characters",
                "severity": "2 - High",
                "priority": "P2",
                "status": "New",
                "age": 1,
                "found_in": "Staging",
                "linked_story_id": "123086",
                "linked_tc_id": "",
            }
        ],
    }


def _judgment():
    return {
        "headline": "Open bug on admin login",
        "health": "Low",
        "analysis": "The password bug is still open.",
        "reviews": [
            {
                "ac_id": "AC-01",
                "row_status": "partial",
                "depth": "Happy path only",
                "gap": "No negative test",
                "mapped_test_ids": ["121216", "999"],
            },
            {
                "ac_id": "AC-02",
                "row_status": "adequate",
                "depth": "Covered",
                "gap": "Adequate",
                "mapped_test_ids": ["999"],
            },
            {
                "ac_id": "AC-99",
                "row_status": "adequate",
                "depth": "Invented",
                "gap": "Invented",
                "mapped_test_ids": ["121216"],
            },
        ],
        "actions": [
            {"owner": "Dev", "text": "Fix the password bug."},
            {"owner": "QA", "text": "Add a negative test."},
            {"owner": "PO", "text": "Confirm the admin criteria."},
        ],
    }


def test_judgment_keeps_fetched_counts_and_drops_invented_ids():
    result = result_from_judgment(_record(), _judgment())
    score = result["score"]
    rows = {row["ac_id"]: row for row in score["scenarios"]}

    assert score["test_count"] == 2
    assert score["bug_count"] == 1
    assert score["open_bug_count"] == 1
    assert score["scenario_count"] == 2
    assert score["health"] == "High"
    assert score["health_band"] == "At Risk"
    assert score["mapped_count"] == 1
    assert rows["AC-01"]["row_status"] == "partial"
    assert rows["AC-01"]["mapped_test_ids"] == ["121216"]
    assert rows["AC-02"]["row_status"] == "none"
    assert "AC-99" not in rows
    assert "2 tests and 1 mapped." in result["narrative"]["observations"]
    assert result["narrative"]["observations"][0] == "Story health - High"
    assert any(item.startswith("Fix open bug 122590") for item in (
        action["text"] for action in result["narrative"]["actions"]
    ))
    assert result["narrative"]["headline"] == "Open bug on admin login"


def test_a_long_analysis_is_kept_as_separate_sentences():
    record = _record()
    record["bugs"] = []
    judgment = _judgment()
    judgment["health"] = "No open bugs"
    judgment["analysis"] = (
        "No open bug sets health. "
        "AC-01 is linked to test 121216 and still lacks a negative case. "
        "AC-02 has no mapped test. "
        "The rejected work is not in this record."
    )
    result = result_from_judgment(record, judgment)
    observations = result["narrative"]["observations"]

    assert "No open bug sets health." in observations
    assert "AC-02 has no mapped test." in observations
    assert observations[-1] == "The rejected work is not in this record."


def test_ollama_receives_evaluation_instructions(monkeypatch):
    captured = {}

    def fake_chat(messages, num_predict=8192):
        captured["messages"] = messages
        captured["num_predict"] = num_predict
        return {
            "message": {"content": json.dumps(_judgment())},
            "prompt_eval_count": 3,
            "eval_count": 4,
        }

    monkeypatch.setattr("story_guard.analysis.ollama_chat", fake_chat)
    analyze_live(_record())

    system = captured["messages"][0]["content"]
    user = captured["messages"][1]["content"]
    assert "Evaluate every acceptance criterion" in user
    assert '"open":true' in user
    assert '"mapped_ac_ids":["AC-01"]' in user
    assert "How to judge coverage" in system
    assert "How to judge health" in system
    assert "Coverage does not change health" in system
    assert "An open P1 sets health to Critical" in system
    assert "an open P2 sets health to High" in system
    assert "no listed test checks" in system
    assert "Do not use a percent sign" in system
    assert "partially covered" in system
    assert "one review" in system.lower() or "every object in acceptance_criteria" in system
    assert "Return one review only for these ac ids: AC-02" in user
    assert "six to ten sentences" in system
    assert "six to ten sentences" in user
    assert captured["num_predict"] == 3456


def test_analyze_live_retries_an_invalid_health(monkeypatch):
    calls = {"n": 0}

    def fake_chat(messages, num_predict=8192):
        calls["n"] += 1
        if calls["n"] == 1:
            content = json.dumps({"health": "Green"})
        else:
            assert "previous JSON was rejected" in messages[-1]["content"]
            content = json.dumps(_judgment())
        return {
            "message": {"content": content},
            "prompt_eval_count": 3,
            "eval_count": 4,
        }

    monkeypatch.setattr("story_guard.analysis.ollama_chat", fake_chat)
    result = analyze_live(_record())

    assert calls["n"] == 2
    assert result["score"]["health"] == "High"
    assert result["token_count"] == 7


def test_explicit_link_survives_a_none_review():
    from story_guard.score import apply_explicit_links

    record = _record()
    record["id"] = "121213"
    record["acceptance_criteria"] = [
        {
            "ac_id": "AC-11",
            "text": "Login page retention. The entered email remains.",
            "testable": True,
            "flags": [],
        }
    ]
    record["bugs"] = []
    record["tests"] = apply_explicit_links(
        [
            {
                "id": "121220",
                "title": "invalid email format",
                "type": "",
                "mapped_ac_ids": [],
            },
            {
                "id": "121221",
                "title": "unregistered email",
                "type": "",
                "mapped_ac_ids": [],
            },
            {
                "id": "121222",
                "title": "incorrect password and field reset",
                "type": "",
                "mapped_ac_ids": [],
            },
        ]
    )
    judgment = _judgment()
    judgment["health"] = "No open bugs"
    judgment["reviews"] = [
        {
            "ac_id": "AC-11",
            "row_status": "none",
            "depth": "None",
            "gap": "No coverage",
            "mapped_test_ids": [],
        }
    ]
    result = result_from_judgment(record, judgment)
    row = result["score"]["scenarios"][0]

    assert row["ac_id"] == "AC-11"
    assert row["row_status"] == "partial"
    assert row["mapped_test_ids"] == ["121220", "121221"]
    assert result["score"]["none_count"] == 0
    assert result["narrative"]["observations"][0] == "Story health - No open bugs"


def test_fully_linked_story_asks_for_no_reviews(monkeypatch):
    from story_guard.score import apply_explicit_links

    captured = {}

    def fake_chat(messages, num_predict=8192):
        captured["messages"] = messages
        captured["num_predict"] = num_predict
        body = _judgment()
        body["health"] = "No open bugs"
        body["reviews"] = []
        return {
            "message": {"content": json.dumps(body)},
            "prompt_eval_count": 1,
            "eval_count": 2,
        }

    record = _record()
    record["id"] = "121213"
    record["bugs"] = []
    record["acceptance_criteria"] = [
        {
            "ac_id": "AC-11",
            "text": "Login page retention. The entered email remains.",
            "testable": True,
            "flags": [],
        }
    ]
    record["tests"] = apply_explicit_links(
        [
            {
                "id": "121220",
                "title": "invalid email format",
                "type": "",
                "mapped_ac_ids": [],
            }
        ]
    )
    monkeypatch.setattr("story_guard.analysis.ollama_chat", fake_chat)
    result = analyze_live(record)
    user = captured["messages"][1]["content"]

    assert "reviews must be []" in user
    assert "invalid email format" not in user
    assert captured["num_predict"] == 3072
    assert result["score"]["scenarios"][0]["mapped_test_ids"] == ["121220"]


def test_slow_analysis_retries_with_a_shorter_limit(monkeypatch):
    from story_guard.narrative import NarrativeError

    calls = []

    def fake_chat(messages, num_predict=8192):
        calls.append((num_predict, messages[-1]["content"]))
        if len(calls) == 1:
            raise NarrativeError("narrative exceeded 60 seconds of generation")
        return {
            "message": {"content": json.dumps(_judgment())},
            "prompt_eval_count": 1,
            "eval_count": 2,
        }

    monkeypatch.setattr("story_guard.analysis.ollama_chat", fake_chat)
    result = analyze_live(_record())

    assert calls[0][0] == 3456
    assert calls[1][0] == 1728
    assert "too long" in calls[1][1]
    assert result["score"]["health"] == "High"
