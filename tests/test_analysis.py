"""Live analysis keeps fetched counts. Health and coverage rows stay on the score."""

import json

import pytest

from story_guard.analysis import _PROMPT, analyze_live, result_from_judgment
from story_guard.narrative import NarrativeError


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


def _pair_reply(ac_id="AC-02", ids=None):
    mapped = ["121220"] if ids is None else list(ids)
    if mapped:
        finding = f"{ac_id} is checked by {', '.join(mapped)}."
    else:
        finding = f"No listed test checks {ac_id}."
    return {"ac_id": ac_id, "mapped_test_ids": mapped, "finding": finding}


def test_ollama_judges_one_criterion_against_one_suite(monkeypatch):
    captured = []

    def fake_chat(messages, num_predict=8192):
        captured.append({"messages": messages, "num_predict": num_predict})
        payload = json.loads(messages[1]["content"].split("\n", 1)[1])
        ac_id = payload["acceptance_criterion"]["ac_id"]
        test_ids = [test["id"] for test in payload["tests"]]
        ids = [test_ids[0]] if ac_id == "AC-01" else [test_ids[-1]]
        return {
            "message": {
                "content": json.dumps(
                    {
                        **_pair_reply(ac_id, ids),
                        "coverage_status": "partial",
                        "quality": {"status": "good", "testable": True, "issues": []},
                    }
                )
            },
            "prompt_eval_count": 3,
            "eval_count": 4,
        }

    monkeypatch.setattr("story_guard.analysis.ollama_chat", fake_chat)
    result = analyze_live(_record())

    assert len(captured) == 2
    system = captured[0]["messages"][0]["content"]
    user = captured[0]["messages"][1]["content"]
    assert "Judge this one acceptance criterion against every test in this one suite batch." in user
    assert "Admin signs in" in user
    assert "Admin is rejected" not in user
    assert "mapped_ac_ids" not in user
    assert "Valid login" in user
    assert "Bad password" in user
    assert "122590" not in user
    assert "How to judge coverage" in system
    assert "one acceptance criterion and one suite" in system
    assert 'Sharing only a generic word such as "login" is not enough.' in system
    assert "P is happy, N is negative, and A is adhoc." in system
    assert "no listed test checks" in system
    assert "Do not use a percent sign" in system
    assert "partially covered" in system
    assert "Coverage does not change health" in system
    assert "quality" in system
    assert captured[0]["num_predict"] == 2048
    assert captured[1]["num_predict"] == 2048
    rows = {row["ac_id"]: row for row in result["score"]["scenarios"]}
    assert rows["AC-01"]["mapped_test_ids"] == ["121216"]
    assert rows["AC-02"]["mapped_test_ids"] == ["121220"]
    assert result["score"]["health"] == "High"
    assert result["narrative"]["headline"] == (
        "Open P2 bug 122590: Password field is not accepting special characters."
    )
    assert "122590" in " ".join(result["narrative"]["observations"])


def test_analyze_live_retries_an_invalid_review(monkeypatch):
    calls = {"n": 0}

    def fake_chat(messages, num_predict=8192):
        calls["n"] += 1
        if calls["n"] == 1:
            content = json.dumps({"health": "Green"})
        else:
            assert "previous JSON was rejected" in messages[-1]["content"]
            payload = json.loads(messages[1]["content"].split("\n", 1)[1])
            content = json.dumps(_pair_reply(payload["acceptance_criterion"]["ac_id"]))
        return {
            "message": {"content": content},
            "prompt_eval_count": 3,
            "eval_count": 4,
        }

    monkeypatch.setattr("story_guard.analysis.ollama_chat", fake_chat)
    record = _record()
    record["acceptance_criteria"] = [record["acceptance_criteria"][1]]
    result = analyze_live(record)

    assert calls["n"] == 2
    assert result["score"]["health"] == "High"
    assert result["token_count"] == 7


def test_model_review_can_reject_a_source_link():
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
    assert row["row_status"] == "none"
    assert row["mapped_test_ids"] == []
    assert result["score"]["none_count"] == 1
    assert result["narrative"]["observations"][0] == "Story health - No open bugs"


def test_fully_linked_story_is_still_reviewed_by_the_model(monkeypatch):
    from story_guard.score import apply_explicit_links

    calls = []

    def fake_chat(messages, num_predict=8192):
        calls.append(messages)
        payload = json.loads(messages[1]["content"].split("\n", 1)[1])
        return {
            "message": {
                "content": json.dumps(
                    _pair_reply(payload["acceptance_criterion"]["ac_id"], ["121220"])
                )
            },
            "prompt_eval_count": 3,
            "eval_count": 4,
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

    assert result["score"]["scenarios"][0]["mapped_test_ids"] == ["121220"]
    assert result["narrative"]["headline"] == "No open bugs."
    assert len(calls) == 1
    assert result["token_count"] == 7


def test_each_criterion_is_judged_against_each_suite(monkeypatch):
    calls = []

    def fake_chat(messages, num_predict=8192):
        user = messages[1]["content"]
        payload = json.loads(user.split("\n", 1)[1])
        ac_id = payload["acceptance_criterion"]["ac_id"]
        suite_id = payload["suite"]["id"]
        test_ids = [item["id"] for item in payload["tests"]]
        calls.append((ac_id, suite_id, test_ids))
        if suite_id == "S1":
            assert "Bad password" not in user
        if suite_id == "S2":
            assert "Valid login" not in user
        if ac_id == "AC-01":
            assert "Admin is rejected" not in user
        chosen = test_ids[:1]
        return {
            "message": {
                "content": json.dumps(
                    {
                        "ac_id": ac_id,
                        "mapped_test_ids": chosen,
                        "finding": f"{ac_id} is checked by {chosen[0]}.",
                    }
                )
            },
            "prompt_eval_count": 1,
            "eval_count": 1,
        }

    record = _record()
    record["bugs"] = []
    record["acceptance_criteria"] = [
        {"ac_id": "AC-01", "text": "Admin signs in", "testable": True, "flags": []},
        {"ac_id": "AC-02", "text": "Admin is rejected", "testable": True, "flags": []},
    ]
    record["tests"] = [
        {
            "id": "121216",
            "title": "Valid login",
            "type": "happy",
            "mapped_ac_ids": [],
            "suite_id": "S1",
            "suite_name": "Suite One",
        },
        {
            "id": "121217",
            "title": "Empty email",
            "type": "negative",
            "mapped_ac_ids": [],
            "suite_id": "S1",
            "suite_name": "Suite One",
        },
        {
            "id": "121220",
            "title": "Bad password",
            "type": "negative",
            "mapped_ac_ids": [],
            "suite_id": "S2",
            "suite_name": "Suite Two",
        },
    ]
    monkeypatch.setattr("story_guard.analysis.ollama_chat", fake_chat)
    result = analyze_live(record)
    rows = {row["ac_id"]: row for row in result["score"]["scenarios"]}

    assert calls == [
        ("AC-01", "S1", ["121216", "121217"]),
        ("AC-01", "S2", ["121220"]),
        ("AC-02", "S1", ["121216", "121217"]),
        ("AC-02", "S2", ["121220"]),
    ]
    assert rows["AC-01"]["mapped_test_ids"] == ["121216", "121220"]
    assert rows["AC-02"]["mapped_test_ids"] == ["121216", "121220"]
    assert result["token_count"] == 8
    assert result["narrative"]["headline"] == "No open bugs."


def test_a_story_with_no_fetched_tests_makes_no_model_call(monkeypatch):
    def fake_chat(messages, num_predict=8192):
        raise AssertionError("model call")

    record = _record()
    record["bugs"] = []
    record["tests"] = []
    record["acceptance_criteria"] = [
        {"ac_id": "AC-01", "text": "Admin signs in", "testable": True, "flags": []},
    ]
    monkeypatch.setattr("story_guard.analysis.ollama_chat", fake_chat)
    result = analyze_live(record)
    row = result["score"]["scenarios"][0]

    assert row["row_status"] == "none"
    assert row["mapped_test_ids"] == []
    assert row["ac_quality"]["status"] == "needs_improvement"
    assert "No listed test checks AC-01." in result["narrative"]["observations"]
    assert result["token_count"] == 0
    assert result["score"]["test_count"] == 0
    assert result["narrative"]["headline"] == "No open bugs."


def test_calls_for_one_story_do_not_overlap(monkeypatch):
    state = {"in_flight": 0, "max_in_flight": 0, "calls": 0}

    def fake_chat(messages, num_predict=8192):
        state["in_flight"] += 1
        state["max_in_flight"] = max(state["max_in_flight"], state["in_flight"])
        state["calls"] += 1
        try:
            payload = json.loads(messages[1]["content"].split("\n", 1)[1])
            ac_id = payload["acceptance_criterion"]["ac_id"]
            suite_id = payload["suite"]["id"]
            assert len(payload["tests"]) >= 1
            assert suite_id in {"S1", "S2"}
            return {
                "message": {
                    "content": json.dumps(
                        _pair_reply(ac_id, [payload["tests"][0]["id"]])
                    )
                },
                "prompt_eval_count": 1,
                "eval_count": 1,
            }
        finally:
            state["in_flight"] -= 1

    record = _record()
    record["bugs"] = []
    record["tests"] = [
        {
            "id": "900001",
            "title": "Valid login",
            "type": "happy",
            "mapped_ac_ids": [],
            "suite_id": "S1",
            "suite_name": "Suite One",
        },
        {
            "id": "900002",
            "title": "Bad password",
            "type": "negative",
            "mapped_ac_ids": [],
            "suite_id": "S2",
            "suite_name": "Suite Two",
        },
    ]
    monkeypatch.setattr("story_guard.analysis.ollama_chat", fake_chat)
    result = analyze_live(record)

    assert state["calls"] == 4
    assert state["max_in_flight"] == 1
    assert result["score"]["test_count"] == 2
    assert {row["ac_id"] for row in result["score"]["scenarios"]} == {"AC-01", "AC-02"}


def test_slow_analysis_retries_with_a_shorter_limit(monkeypatch):
    from story_guard.narrative import NarrativeError

    calls = []

    def fake_chat(messages, num_predict=8192):
        calls.append((num_predict, messages[-1]["content"]))
        if len(calls) == 1:
            raise NarrativeError("narrative exceeded 60 seconds of generation")
        payload = json.loads(messages[1]["content"].split("\n", 1)[1])
        return {
            "message": {
                "content": json.dumps(
                    _pair_reply(payload["acceptance_criterion"]["ac_id"])
                )
            },
            "prompt_eval_count": 1,
            "eval_count": 2,
        }

    monkeypatch.setattr("story_guard.analysis.ollama_chat", fake_chat)
    record = _record()
    record["acceptance_criteria"] = [record["acceptance_criteria"][1]]
    result = analyze_live(record)

    assert calls[0][0] == 2048
    assert calls[1][0] == 1024
    assert "too long" in calls[1][1]
    assert result["score"]["health"] == "High"


def test_unknown_ids_and_other_types_are_dropped_and_health_stays_on_the_bugs():
    from story_guard.report_layout import _facts

    record = _record()
    record["bugs"] = [
        {
            "id": "122589",
            "title": "Login outage",
            "severity": "1 - Critical",
            "priority": "P1",
            "status": "New",
            "age": 1,
            "found_in": "Staging",
            "linked_story_id": "123086",
            "linked_tc_id": "",
        }
    ]
    record["tests"] = [
        {
            "id": "42",
            "title": "Valid login",
            "type": "",
            "mapped_ac_ids": [],
        },
        {
            "id": "43",
            "title": "Bad password",
            "type": "",
            "mapped_ac_ids": [],
        },
        {
            "id": "44",
            "title": "Refresh the page",
            "type": "",
            "mapped_ac_ids": [],
        },
        {
            "id": "45",
            "title": "Security scan",
            "type": "",
            "mapped_ac_ids": [],
        },
    ]
    judgment = _judgment()
    judgment["health"] = "Green"
    judgment["test_coverage_percent"] = 99
    judgment["reviews"] = [
        {
            "ac_id": "AC-01",
            "mapped_test_ids": ["42", "999", "43", "44", "45"],
            "test_types": {
                "42": "positive",
                "43": "negative",
                "44": "adhoc",
                "45": "security",
                "46": "edge",
                "999": "happy",
            },
            "coverage_status": "adequate",
            "finding": "AC-01 is 80% covered by 999.",
        },
        {
            "ac_id": "AC-02",
            "mapped_test_ids": ["999"],
            "test_types": {"43": "edge"},
            "coverage_status": "adequate",
        },
    ]
    result = result_from_judgment(record, judgment)
    score = result["score"]
    rows = {row["ac_id"]: row for row in score["scenarios"]}
    facts = _facts(score, record)

    assert rows["AC-01"]["mapped_test_ids"] == ["42", "43", "44", "45"]
    assert "999" not in rows["AC-01"]["mapped_test_ids"]
    assert rows["AC-02"]["mapped_test_ids"] == []
    assert rows["AC-02"]["row_status"] == "none"
    assert score["coverage_by_type"]["happy"] == 1
    assert score["coverage_by_type"]["negative"] == 2
    assert score["coverage_by_type"]["adhoc"] == 1
    assert score["coverage_by_type"]["edge"] == 0
    assert score["coverage_by_type"]["security"] == 0
    assert score["coverage_by_type"]["unset"] == 0
    assert score["health"] == "Critical"
    assert score["health_band"] == "At Risk"
    assert "test_coverage_percent" not in score
    assert facts["coverage_label"] == "50%"
    assert facts["health"] == "Critical"
    assert "99%" not in facts["coverage_label"]


def test_a_finding_with_a_percent_sign_is_replaced(monkeypatch):
    def fake_chat(messages, num_predict=8192):
        payload = json.loads(messages[1]["content"].split("\n", 1)[1])
        ac_id = payload["acceptance_criterion"]["ac_id"]
        return {
            "message": {
                "content": json.dumps(
                    {
                        "ac_id": ac_id,
                        "mapped_test_ids": ["121216"] if ac_id == "AC-01" else [],
                        "test_types": {"121216": "edge", "121220": "security"},
                        "coverage_status": "adequate",
                        "quality": {"status": "good", "testable": True, "issues": []},
                        "finding": f"{ac_id} is 40% covered.",
                    }
                )
            },
            "prompt_eval_count": 1,
            "eval_count": 1,
        }

    monkeypatch.setattr("story_guard.analysis.ollama_chat", fake_chat)
    result = analyze_live(_record())
    text = " ".join(result["narrative"]["observations"])
    rows = {row["ac_id"]: row for row in result["score"]["scenarios"]}

    assert "%" not in text
    assert "No listed test checks AC-02." in text
    assert "AC-01 is checked by 121216." in text
    assert result["score"]["coverage_by_type"]["unset"] == 1
    assert result["score"]["coverage_by_type"]["adhoc"] == 1
    assert result["score"]["coverage_by_type"]["edge"] == 0
    assert rows["AC-01"]["mapped_test_ids"] == ["121216"]
    assert result["score"]["health"] == "High"


def test_live_review_calls_qwen35_4b(monkeypatch):
    monkeypatch.setenv("STORY_GUARD_LLM", "ollama")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3.5:4b")
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
        seen["body"] = json.loads(request.data.decode("utf-8"))
        payload = json.loads(seen["body"]["messages"][1]["content"].split("\n", 1)[1])
        ac_id = payload["acceptance_criterion"]["ac_id"]
        content = json.dumps(
            {
                "ac_id": ac_id,
                "mapped_test_ids": ["42"],
                "test_types": {"42": "happy"},
                "coverage_status": "partial",
                "quality": {"status": "good", "testable": True, "issues": []},
                "finding": "AC-01 is checked by 42.",
            }
        )
        raw = json.dumps(
            {
                "message": {"role": "assistant", "content": content},
                "prompt_eval_count": 5,
                "eval_count": 6,
            }
        ).encode("utf-8")
        return _Body(raw)

    record = _record()
    record["bugs"] = []
    record["acceptance_criteria"] = [record["acceptance_criteria"][0]]
    record["tests"] = [
        {
            "id": "42",
            "title": "Admin signs in with a valid password",
            "type": "",
            "mapped_ac_ids": [],
            "suite_id": "S9",
            "suite_name": "Admin suite",
        }
    ]
    monkeypatch.setattr("story_guard.narrative.urllib.request.urlopen", fake_urlopen)
    result = analyze_live(record)

    assert seen["url"].endswith("/api/chat")
    assert seen["body"]["model"] == "qwen3.5:4b"
    assert seen["body"]["format"] == "json"
    assert seen["body"]["think"] is False
    assert seen["body"]["options"]["num_ctx"] == 8192
    assert result["score"]["scenarios"][0]["mapped_test_ids"] == ["42"]


def _failure_reply(mode: str, ac_id: str) -> dict:
    if mode == "down":
        raise NarrativeError("ollama request failed: connection refused")
    if mode == "timeout":
        return {
            "message": {
                "content": json.dumps(
                    {
                        "ac_id": ac_id,
                        "mapped_test_ids": [],
                        "finding": f"No listed test checks {ac_id}.",
                    }
                )
            },
            "prompt_eval_count": 1,
            "eval_count": 1,
            "load_duration": 0,
            "total_duration": 181_000_000_000,
        }
    return {"message": {"content": "not json"}}


@pytest.mark.parametrize("mode", ["json", "down", "timeout"])
def test_model_failure_names_the_story_and_stops_that_review(monkeypatch, mode):
    from story_guard.narrative import ATTEMPTS

    calls = {"n": 0}

    def fake_chat(messages, num_predict=8192):
        calls["n"] += 1
        payload = json.loads(messages[1]["content"].split("\n", 1)[1])
        return _failure_reply(mode, payload["acceptance_criterion"]["ac_id"])

    record = _record()
    record["acceptance_criteria"] = [record["acceptance_criteria"][0]]
    monkeypatch.setattr("story_guard.analysis.ollama_chat", fake_chat)
    with pytest.raises(NarrativeError, match="story 123086"):
        analyze_live(record)
    assert calls["n"] == (ATTEMPTS if mode == "json" else 1)


def test_long_test_text_is_reviewed_in_parts_and_combined(monkeypatch):
    marker = "UNIQUE-NEGATIVE-MARKER"
    steps = ("a" * 1200) + marker + ("b" * 100)
    seen = []

    def fake_chat(messages, num_predict=8192):
        payload = json.loads(messages[1]["content"].split("\n", 1)[1])
        texts = [item["text"] for item in payload["tests"]]
        seen.append(texts)
        mapped = ["121216"] if any(marker in text for text in texts) else []
        body = {
            "ac_id": payload["acceptance_criterion"]["ac_id"],
            "mapped_test_ids": mapped,
            "test_types": {"121216": "negative"} if mapped else {},
            "coverage_status": "partial" if mapped else "none",
            "quality": {"status": "good", "testable": True, "issues": []},
            "finding": "AC-01 is checked by 121216." if mapped else "No listed test checks AC-01.",
        }
        return {
            "message": {"content": json.dumps(body)},
            "prompt_eval_count": 1,
            "eval_count": 1,
        }

    record = _record()
    record["bugs"] = []
    record["acceptance_criteria"] = [record["acceptance_criteria"][0]]
    record["tests"] = [
        {
            "id": "121216",
            "title": "Admin login",
            "type": "",
            "steps": steps,
            "suite_id": "S1",
            "suite_name": "Suite",
        }
    ]
    monkeypatch.setattr("story_guard.analysis.ollama_chat", fake_chat)
    result = analyze_live(record)
    row = result["score"]["scenarios"][0]
    joined = "".join(text for texts in seen for text in texts)

    assert len(seen) >= 2
    assert marker in joined
    assert steps in joined
    assert row["mapped_test_ids"] == ["121216"]
    assert "Negative scenarios are covered" in row["depth"]


def test_story_description_is_sent_in_parts(monkeypatch):
    description = "D" * 1300
    parts = []

    def fake_chat(messages, num_predict=8192):
        payload = json.loads(messages[1]["content"].split("\n", 1)[1])
        parts.append(payload["story_description"]["text"])
        ac_id = payload["acceptance_criterion"]["ac_id"]
        return {
            "message": {
                "content": json.dumps(
                    {
                        "ac_id": ac_id,
                        "mapped_test_ids": [],
                        "finding": f"No listed test checks {ac_id}.",
                    }
                )
            },
            "prompt_eval_count": 1,
            "eval_count": 1,
        }

    record = _record()
    record["bugs"] = []
    record["description"] = description
    record["acceptance_criteria"] = [record["acceptance_criteria"][0]]
    record["tests"] = [record["tests"][0]]
    monkeypatch.setattr("story_guard.analysis.ollama_chat", fake_chat)
    analyze_live(record)

    assert len(parts) == 2
    assert "".join(parts) == description


def test_description_scenario_is_judged_with_the_acceptance_criteria(monkeypatch):
    calls = []

    def fake_chat(messages, num_predict=8192):
        payload = json.loads(messages[1]["content"].split("\n", 1)[1])
        ac_id = payload["acceptance_criterion"]["ac_id"]
        calls.append(ac_id)
        return {
            "message": {
                "content": json.dumps(
                    {
                        "ac_id": ac_id,
                        "mapped_test_ids": [],
                        "finding": f"No listed test checks {ac_id}.",
                    }
                )
            },
            "prompt_eval_count": 1,
            "eval_count": 1,
        }

    record = _record()
    record["bugs"] = []
    record["acceptance_criteria"] = [record["acceptance_criteria"][0]]
    record["scenarios"] = [
        {
            "ac_id": "AC-05",
            "text": "A password reset email is sent.",
            "testable": True,
            "flags": [],
        }
    ]
    monkeypatch.setattr("story_guard.analysis.ollama_chat", fake_chat)
    result = analyze_live(record)
    rows = {row["ac_id"]: row for row in result["score"]["scenarios"]}

    assert calls == ["AC-01", "AC-05"]
    assert rows["AC-05"]["row_status"] == "none"


def test_the_same_test_can_cover_a_different_path_for_each_criterion():
    record = _record()
    record["bugs"] = []
    record["tests"] = [
        {
            "id": "42",
            "title": "Login",
            "type": "",
            "mapped_ac_ids": [],
        }
    ]
    judgment = _judgment()
    judgment["reviews"] = [
        {
            "ac_id": "AC-01",
            "mapped_test_ids": ["42"],
            "test_types": {"42": "happy"},
            "coverage_status": "partial",
            "finding": "AC-01 is checked by 42.",
        },
        {
            "ac_id": "AC-02",
            "mapped_test_ids": ["42"],
            "test_types": {"42": "negative"},
            "coverage_status": "partial",
            "finding": "AC-02 is checked by 42.",
        },
    ]
    result = result_from_judgment(record, judgment)
    rows = {row["ac_id"]: row for row in result["score"]["scenarios"]}

    assert "Positive scenarios are covered" in rows["AC-01"]["depth"]
    assert "No Negative scenarios Covered" in rows["AC-01"]["gap"]
    assert "Negative scenarios are covered" in rows["AC-02"]["depth"]
    assert "No Positive scenarios Covered" in rows["AC-02"]["gap"]


def test_title_token_sets_the_path_and_failure_proof_stays_positive():
    record = _record()
    record["bugs"] = []
    record["acceptance_criteria"] = [
        {
            "ac_id": "AC-02",
            "text": (
                "Invalid credentials. When the user submits an unregistered email, "
                "or a registered email with the wrong password, an error says the "
                "credentials are invalid, and the user stays on the login page."
            ),
            "testable": True,
            "flags": [],
        }
    ]
    record["tests"] = [
        {"id": "124311", "title": "[US-XXXXX-N01] Verify login fails with an unregistered email address", "type": ""},
        {"id": "124312", "title": "[US-XXXXX-N02] Verify login fails with a registered email and wrong password", "type": ""},
        {"id": "124319", "title": "[US-XXXXX-A04] Verify password field is case-sensitive", "type": ""},
    ]
    judgment = _judgment()
    judgment["reviews"] = [
        {
            "ac_id": "AC-02",
            "mapped_test_ids": ["124311", "124312", "124319"],
            "test_types": {"124311": "negative", "124312": "negative", "124319": "happy"},
            "coverage_status": "partial",
            "finding": "AC-02 is checked by 124311, 124312, 124319.",
        }
    ]
    result = result_from_judgment(record, judgment)
    row = result["score"]["scenarios"][0]
    paths = row  # depth and gap show the buckets

    assert row["row_status"] == "adequate"
    assert "Positive scenarios are covered" in paths["depth"]
    assert "Negative scenarios are covered" in paths["depth"]
    assert "Adhoc scenarios are covered" in paths["depth"]
    assert result["score"]["coverage_by_type"]["adhoc"] == 1
    assert result["score"]["coverage_by_type"]["negative"] == 2


def test_negative_and_adhoc_variants_join_a_linked_behavior():
    record = _record()
    record["bugs"] = []
    record["acceptance_criteria"] = [
        {
            "ac_id": "AC-03",
            "text": (
                "Password visibility — Show. When the user has entered a password "
                "and clicks Show, the password is displayed as plain text."
            ),
            "testable": True,
            "flags": [],
        },
        {
            "ac_id": "AC-04",
            "text": (
                "Forgot Password navigation. When the user clicks Forgot Password?, "
                "the user is redirected to the password recovery page."
            ),
            "testable": True,
            "flags": [],
        },
    ]
    record["tests"] = [
        {"id": "124309", "title": "[US-XXXXX-P03] Verify password is displayed as plain text when Show is clicked", "type": ""},
        {"id": "124314", "title": "[US-XXXXX-N04] Verify password remains masked when Show is NOT clicked", "type": ""},
        {"id": "124316", "title": "[US-XXXXX-A01] Verify Show/Hide toggle behavior with empty password field", "type": ""},
        {"id": "124311", "title": "[US-XXXXX-N01] Verify login fails with an unregistered email address", "type": ""},
        {"id": "124310", "title": "[US-XXXXX-P04] Verify Forgot Password? link redirects to the password recovery page", "type": ""},
        {"id": "124321", "title": "[US-XXXXX-A06] Verify Forgot Password? link is reachable across viewports", "type": ""},
        {"id": "124401", "title": "[US-XXXXX-N09] Verify the footer link opens the help page", "type": ""},
        {"id": "124402", "title": "[US-XXXXX-A10] Verify the footer link survives a refresh", "type": ""},
    ]
    judgment = _judgment()
    judgment["reviews"] = [
        {
            "ac_id": "AC-03",
            "mapped_test_ids": ["124309"],
            "test_types": {"124309": "happy"},
            "coverage_status": "adequate",
            "finding": "AC-03 is checked by 124309.",
        },
        {
            "ac_id": "AC-04",
            "mapped_test_ids": ["124310", "124321"],
            "test_types": {"124310": "happy", "124321": "happy"},
            "coverage_status": "adequate",
            "finding": "AC-04 is checked by 124310, 124321.",
        },
    ]
    result = result_from_judgment(record, judgment)
    rows = {row["ac_id"]: row for row in result["score"]["scenarios"]}

    assert rows["AC-03"]["mapped_test_ids"] == ["124309", "124314", "124316"]
    assert rows["AC-03"]["row_status"] == "adequate"
    assert "124311" not in rows["AC-03"]["mapped_test_ids"]
    assert rows["AC-04"]["mapped_test_ids"] == ["124310", "124321"]
    assert rows["AC-04"]["row_status"] == "partial"
    assert "No Negative scenarios Covered" in rows["AC-04"]["gap"]
    assert "Adhoc scenarios are covered" in rows["AC-04"]["depth"]
    assert "P is happy, N is negative, and A is adhoc." in _PROMPT


def test_a_mapped_test_with_no_model_type_is_classified_from_its_text(monkeypatch):
    def fake_chat(messages, num_predict=8192):
        payload = json.loads(messages[1]["content"].split("\n", 1)[1])
        ac_id = payload["acceptance_criterion"]["ac_id"]
        return {
            "message": {
                "content": json.dumps(
                    {
                        "ac_id": ac_id,
                        "mapped_test_ids": ["121220"],
                        "finding": "AC-01 is checked by 121220.",
                    }
                )
            },
            "prompt_eval_count": 1,
            "eval_count": 1,
        }

    record = _record()
    record["bugs"] = []
    record["acceptance_criteria"] = [record["acceptance_criteria"][0]]
    record["tests"] = [
        {
            "id": "121220",
            "title": "Bad password",
            "type": "",
            "steps": "Enter an incorrect password. An error is shown.",
        }
    ]
    monkeypatch.setattr("story_guard.analysis.ollama_chat", fake_chat)
    result = analyze_live(record)
    row = result["score"]["scenarios"][0]

    assert row["mapped_test_ids"] == ["121220"]
    assert "Negative scenarios are covered" in row["depth"]


def test_bug_description_and_repro_steps_reach_the_report(monkeypatch):
    def fake_chat(messages, num_predict=8192):
        payload = json.loads(messages[1]["content"].split("\n", 1)[1])
        assert "repro" not in messages[1]["content"].casefold()
        ac_id = payload["acceptance_criterion"]["ac_id"]
        return {
            "message": {
                "content": json.dumps(
                    {
                        "ac_id": ac_id,
                        "mapped_test_ids": [],
                        "finding": f"No listed test checks {ac_id}.",
                    }
                )
            },
            "prompt_eval_count": 1,
            "eval_count": 1,
        }

    record = _record()
    record["acceptance_criteria"] = [record["acceptance_criteria"][0]]
    record["bugs"][0]["description"] = "The field rejects the typed character."
    record["bugs"][0]["repro_steps"] = "R" * 1300
    monkeypatch.setattr("story_guard.analysis.ollama_chat", fake_chat)
    result = analyze_live(record)
    observations = "\n".join(result["narrative"]["observations"])

    assert "Bug 122590 description: The field rejects the typed character." in observations
    assert "Bug 122590 repro steps part 1 of 2:" in observations
    assert "Bug 122590 repro steps part 2 of 2:" in observations
    assert observations.count("R") == 1300
