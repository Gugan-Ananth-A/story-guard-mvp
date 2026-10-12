"""story-guard generate writes score-derived Markdown and PDF reports."""

import inspect
from pathlib import Path

import pytest

from story_guard.cli import main
from story_guard.graph import build_generate_graph, fetch, run
from story_guard.narrative import NarrativeError
from story_guard.render import RenderError, render_markdown

ROOT = Path(__file__).resolve().parents[1]
HEADINGS = (
    "## Title block",
    "## Overall RAG",
    "## AC review",
    "## AC ↔ test mapping",
    "## Coverage by type",
    "## Bugs",
    "## Recommended actions",
    "## Appendix",
)


def _fake_narrative(score):
    return {
        "score": score,
        "narrative": {
            "headline": "No open bugs on this story",
            "sections": [
                {
                    "name": "Story health",
                    "prose": "Story health is No open bugs. The None count is on the score.",
                }
            ],
            "actions": [
                {"owner": "PO", "text": "Write acceptance criteria for the empty AC field."},
                {"owner": "QA", "text": "Map each scenario to a test before counting coverage."},
                {"owner": "Dev", "text": "Leave the story health as the score recorded it."},
            ],
        },
        "token_count": 40,
        "narrative_latency_ms": 12,
    }


def test_generate_graph_order():
    edges = {(edge.source, edge.target) for edge in build_generate_graph().get_graph().edges}
    assert edges == {
        ("__start__", "gate_input"),
        ("gate_input", "fetch"),
        ("fetch", "validate_contract"),
        ("validate_contract", "score_health"),
        ("score_health", "write_narrative"),
        ("write_narrative", "render_pdf"),
        ("render_pdf", "__end__"),
    }


def test_generate_writes_eight_headings_and_score_pdf(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("ADO_PAT", raising=False)
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.setattr("story_guard.graph.artifacts_dir", lambda: tmp_path)
    monkeypatch.setattr("story_guard.graph.request_narrative", _fake_narrative)
    score = run({"story_id": "121213"})["score"]
    received_scores = []
    from story_guard.render import render_pdf as actual_render_pdf

    def capture_rendered_score(received, *args, **kwargs):
        received_scores.append(received)
        return actual_render_pdf(received, *args, **kwargs)

    monkeypatch.setattr("story_guard.graph.render_pdf_file", capture_rendered_score)
    assert main(["generate", "--story-id", "121213"]) == 0
    report = tmp_path / "121213.md"
    pdf = tmp_path / "121213.pdf"
    assert report.is_file()
    assert pdf.is_file() and pdf.stat().st_size > 0
    assert received_scores == [score]
    text = report.read_text(encoding="utf-8")
    assert [line for line in text.splitlines() if line.startswith("## ")] == list(HEADINGS)
    assert "Story Health Report" in text
    assert "dummy fixture" in text
    assert "The AC field is empty." in text
    assert "No open bugs" in text
    assert "Overall RAG" in text
    assert "Red" in text
    assert "SR-1, SR-2, SR-3" in text
    assert "8 acceptance criteria | 0 adequately covered | 0 with gaps | 8 not covered" in text
    assert "Tests: 18. Mapped: 0. Bugs: 0." in text
    assert "Color key: Adequate, Partial, None." in text
    assert "Bug ID" in text and "Assigned To" in text
    assert "No bugs." in text
    assert "partially covered" not in text
    assert "%" not in text
    printed = capsys.readouterr().out.strip()
    assert printed == str(report)
    pdf_text = pdf.read_bytes()
    for marker in (
        b"1. Portfolio Summary",
        b"2. Story Health Overview",
        b"3. Acceptance Criteria vs Test Case Coverage",
        b"4. Bug Details",
        b"Key Observations",
        b"The AC field is empty.",
        b"No open bugs",
        b"18",
        b"No bugs.",
        b"Page 1 of",
    ):
        assert marker in pdf_text
    assert b"Test coverage: 66%" not in pdf_text
    assert b"0%" in pdf_text
    assert b"n/a" not in pdf_text
    assert b"Story health - No open bugs" in pdf_text
    assert b"Test suite" not in pdf_text
    assert f"{score['scenario_count']} acceptance criteria".encode() in pdf_text
    assert f"{score['none_count']} not covered".encode() in pdf_text
    assert b"The None count is on the score." in pdf_text


def test_score_command_does_not_call_the_model(monkeypatch, capsys):
    def fail(score):
        raise AssertionError("narrative ran")

    monkeypatch.setattr("story_guard.graph.request_narrative", fail)
    assert main(["score", "--story-id", "121213"]) == 0
    capsys.readouterr()


@pytest.mark.parametrize("story_id", ["999999", "abc", ""])
def test_bad_story_id_writes_no_report(tmp_path, monkeypatch, capsys, story_id):
    monkeypatch.setattr("story_guard.graph.artifacts_dir", lambda: tmp_path)

    def fail(score):
        raise AssertionError("narrative ran")

    monkeypatch.setattr("story_guard.graph.request_narrative", fail)
    assert main(["generate", "--story-id", story_id]) == 1
    assert list(tmp_path.iterdir()) == []
    assert not (tmp_path / "runs.jsonl").exists()
    assert capsys.readouterr().out == ""


def test_narrative_failure_writes_no_report(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("story_guard.graph.artifacts_dir", lambda: tmp_path)

    def fail(score):
        raise NarrativeError("narrative response was not valid JSON")

    def render_should_not_run(*_args, **_kwargs):
        raise AssertionError("render ran")

    monkeypatch.setattr("story_guard.graph.request_narrative", fail)
    monkeypatch.setattr("story_guard.graph.render_markdown", render_should_not_run)
    assert main(["generate", "--story-id", "121213"]) == 1
    assert list(tmp_path.iterdir()) == []
    assert not (tmp_path / "runs.jsonl").exists()
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "narrative" in captured.err


def test_narrative_count_mismatch_writes_no_artifact(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("story_guard.graph.artifacts_dir", lambda: tmp_path)
    bad = _fake_narrative

    def wrong_count(score):
        result = bad(score)
        result["narrative"]["headline"] = "There are 17 tests and 0 bugs."
        return result

    monkeypatch.setattr("story_guard.graph.request_narrative", wrong_count)
    assert main(["generate", "--story-id", "121213"]) == 1
    assert list(tmp_path.iterdir()) == []
    assert "test_count" in capsys.readouterr().err


def test_narrative_coverage_claim_writes_no_artifact(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("story_guard.graph.artifacts_dir", lambda: tmp_path)

    def covered_ac(score):
        result = _fake_narrative(score)
        result["narrative"]["headline"] = "AC-1 is covered."
        return result

    monkeypatch.setattr("story_guard.graph.request_narrative", covered_ac)
    assert main(["generate", "--story-id", "121213"]) == 1
    assert list(tmp_path.iterdir()) == []
    assert "claims coverage" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("headline", "expected_error"),
    [
        ("There are 9 acceptance criteria.", "scenario_count"),
        ("Mapped ACs: 2.", "mapped_count"),
        ("Coverage RAG is Green.", "RAG"),
        ("Story health is Critical.", "story health"),
    ],
)
def test_narrative_score_conflicts_write_no_artifact(
    tmp_path, monkeypatch, capsys, headline, expected_error
):
    monkeypatch.setattr("story_guard.graph.artifacts_dir", lambda: tmp_path)

    def conflicting_narrative(score):
        result = _fake_narrative(score)
        result["narrative"]["headline"] = headline
        return result

    monkeypatch.setattr("story_guard.graph.request_narrative", conflicting_narrative)
    assert main(["generate", "--story-id", "121213"]) == 1
    assert list(tmp_path.iterdir()) == []
    assert expected_error.lower() in capsys.readouterr().err.lower()


def test_default_generate_never_constructs_ado_client(tmp_path, monkeypatch, capsys):
    from story_guard.ado_client import ADOClient

    def fail(cls):
        raise AssertionError("ADO client was constructed")

    monkeypatch.setattr(ADOClient, "from_env", classmethod(fail))
    monkeypatch.setattr("story_guard.graph.artifacts_dir", lambda: tmp_path)
    monkeypatch.setattr("story_guard.graph.request_narrative", _fake_narrative)
    monkeypatch.setattr("story_guard.cli.record_success", lambda *_args: None)

    assert main(["generate", "--story-id", "121213"]) == 0
    assert (tmp_path / "121213.md").is_file()
    capsys.readouterr()


def test_live_generate_uses_ado_story_and_plan_tests(tmp_path, monkeypatch, capsys):
    import json

    from story_guard import graph
    from story_guard.ado_client import ADOClient

    fixture_record = json.loads((ROOT / "fixtures" / "FIX-121213.json").read_text())
    ado_calls = []

    class FakeADOClient:
        def load_live_story(self, story_id, test_plan_id=None):
            ado_calls.append((story_id, test_plan_id))
            return {
                "id": "121213",
                "title": "Live ADO Login Screen",
                "type": "User Story",
                "state": "New",
                "description": fixture_record["description"],
                "area": "StoryGuard",
                "iteration": "StoryGuard\\Sprint",
                "raw_ac_text": "",
                "acceptance_criteria": [],
                "tests": [
                    {
                        "id": "121216",
                        "title": "Valid login",
                        "type": "",
                        "mapped_ac_ids": [],
                        "last_result": "",
                        "last_result_at": None,
                        "linked_bug_ids": [],
                        "suite_id": "121215",
                        "suite_name": "Story Guard - AI Agent",
                        "suite_type": "staticTestSuite",
                        "plan_id": "121214",
                    },
                    {
                        "id": "121228",
                        "title": "Forgot password",
                        "type": "",
                        "mapped_ac_ids": [],
                        "last_result": "",
                        "last_result_at": None,
                        "linked_bug_ids": [],
                        "suite_id": "121215",
                        "suite_name": "Story Guard - AI Agent",
                        "suite_type": "staticTestSuite",
                        "plan_id": "121214",
                    },
                ],
                "bugs": [
                    {
                        "id": "122590",
                        "title": "Password field is not accepting special characters",
                        "severity": "2 - High",
                        "priority": "P2",
                        "status": "New",
                        "age": 0,
                        "found_in": "Staging",
                        "linked_story_id": "121213",
                        "linked_tc_id": "",
                        "assigned_to": "Gugan",
                        "application": "Ecom MVP",
                        "created": "2026-10-09",
                    }
                ],
            }

    def fail_fixture(_story_id):
        raise AssertionError("fixture tests were loaded")

    analyzed = []

    def fake_analyze(record):
        from story_guard.analysis import result_from_judgment

        analyzed.append(record)
        return result_from_judgment(
            record,
            {
                "headline": "Admin login needs bug review",
                "health": "High",
                "analysis": "The open bug blocks a confident sign-off.",
                "reviews": [],
                "actions": [
                    {"owner": "Dev", "text": "Fix the password bug."},
                    {"owner": "QA", "text": "Retest the login screen."},
                    {"owner": "PO", "text": "Confirm the acceptance criteria."},
                ],
            },
            token_count=10,
            narrative_latency_ms=5,
        )

    monkeypatch.setattr(ADOClient, "from_env", classmethod(lambda cls: FakeADOClient()))
    monkeypatch.setattr(graph, "fetch_tests", fail_fixture)
    monkeypatch.setattr(graph, "artifacts_dir", lambda: tmp_path)
    monkeypatch.setattr(graph, "analyze_live", fake_analyze)
    monkeypatch.setattr("story_guard.cli.record_success", lambda *_args: None)

    assert main(["generate", "--story-id", "121213", "--test-plan-id", "121214", "--live"]) == 0

    report = (tmp_path / "121213.md").read_text(encoding="utf-8")
    assert ado_calls == [(121213, 121214)]
    assert analyzed[0]["bugs"][0]["id"] == "122590"
    assert "Title: Live ADO Login Screen" in report
    assert "Source: ADO dummy project" in report
    assert "Admin login needs bug review" in report
    assert "8 acceptance criteria | 0 adequately covered | 2 with gaps | 6 not covered" in report
    assert "Tests: 2. Mapped: 2. Bugs: 1." in report
    assert "Password field is not accepting special characters" in report
    assert "Raw test IDs: 121216, 121228" in report
    assert "Test suites:" not in report
    assert "Suite 121215" not in report
    capsys.readouterr()


@pytest.mark.parametrize("error_type", ["not_found", "not_story"])
def test_live_ado_errors_exit_nonzero_without_report(
    tmp_path, monkeypatch, capsys, error_type
):
    from story_guard.ado_client import (
        ADOClient,
        NonStoryWorkItemError,
        WorkItemNotFoundError,
    )

    exception = (
        WorkItemNotFoundError("work item missing")
        if error_type == "not_found"
        else NonStoryWorkItemError("work item is not a User Story")
    )

    class FailedADOClient:
        def load_live_story(self, _story_id, _test_plan_id=None):
            raise exception

    monkeypatch.setattr(
        ADOClient,
        "from_env",
        classmethod(lambda cls: FailedADOClient()),
    )
    monkeypatch.setattr("story_guard.graph.artifacts_dir", lambda: tmp_path)
    monkeypatch.setattr("story_guard.graph.request_narrative", _fake_narrative)

    assert main(["generate", "--story-id", "121213", "--live"]) == 1
    assert list(tmp_path.iterdir()) == []
    captured = capsys.readouterr()
    assert captured.out == ""
    assert str(exception) in captured.err


def test_generate_path_does_not_name_ado_pat():
    import story_guard.cli as cli
    import story_guard.graph as graph
    import story_guard.narrative as narrative
    import story_guard.prefix as prefix
    import story_guard.render as render
    import story_guard.trace as trace

    for module in (cli, graph, narrative, prefix, render, trace):
        assert "ADO_PAT" not in inspect.getsource(module)


def test_test_plan_id_requires_live(capsys):
    assert main(["generate", "--story-id", "121213", "--test-plan-id", "121214"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "requires --live" in captured.err


def test_demo_script_has_no_live_flag():
    text = (ROOT / "scripts" / "demo.sh").read_text(encoding="utf-8")
    assert "live" not in text.lower()
    assert "story-guard generate --story-id 121213" in text


def test_fetch_uses_the_dummy_adapter(monkeypatch):
    def fake(story_id):
        assert story_id == "121213"
        return [{"id": "121216", "title": "from adapter", "mapped_ac_ids": []}]

    monkeypatch.setattr("story_guard.graph.fetch_tests", fake)
    state = fetch({"story_id": "121213"})
    tests = state["record"]["tests"]
    assert len(tests) == 1
    assert tests[0]["title"] == "from adapter"
    assert tests[0]["mapped_ac_ids"] == []
    assert tests[0]["type"] == ""
    assert "last_result" in tests[0]


def test_fetch_keeps_the_fixture_pack():
    state = fetch({"story_id": "121213"})
    tests = state["record"]["tests"]
    assert [test["id"] for test in tests] == [str(number) for number in range(121216, 121234)]
    assert all(test["mapped_ac_ids"] == [] for test in tests)
    assert all("type" in test and "last_result" in test for test in tests)


def test_missing_template_writes_no_file(tmp_path):
    out = tmp_path / "121213.md"
    with pytest.raises(RenderError):
        render_markdown({}, {"headline": "x"}, tmp_path / "missing.md", out)
    assert not out.exists()
    assert not (tmp_path / "121213.pdf").exists()
