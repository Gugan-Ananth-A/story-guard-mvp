"""story-guard generate writes score-derived Markdown and PDF reports."""

import inspect
import json
import time
from pathlib import Path

import pytest

from story_guard.cli import main
from story_guard.graph import build_generate_graph, fetch, run, write_narrative as narrative_node
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


def test_narrative_node_keeps_the_bounded_score_for_rendering(monkeypatch):
    score = {"test_suite_truncated": True, "test_cases": []}
    narrative = {"headline": "Complete", "sections": [], "actions": []}
    monkeypatch.setattr(
        "story_guard.graph.request_narrative",
        lambda _score: {
            "score": score,
            "narrative": narrative,
            "token_count": 12,
            "narrative_latency_ms": 4,
        },
    )

    result = narrative_node({"score": {"test_suite_truncated": False}})

    assert result["score"] is score
    assert result["score"]["test_suite_truncated"] is True


def _pin_ollama_env(tmp_path, monkeypatch) -> None:
    """The project .env owns the model selector, so this test supplies its own file."""
    env_file = tmp_path / "selector.env"
    env_file.write_text(
        "STORY_GUARD_LLM=ollama\nOLLAMA_MODEL=qwen3.5:4b\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("story_guard.envfile.env_path", lambda: env_file)
    monkeypatch.delenv("STORY_GUARD_MODEL", raising=False)


def test_generate_writes_eight_headings_and_score_pdf(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("ADO_PAT", raising=False)
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    _pin_ollama_env(tmp_path, monkeypatch)
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
    captured = capsys.readouterr()
    printed = captured.out.strip()
    assert printed == str(report)
    assert "[story-guard] provider ollama, model qwen3.5:4b" in captured.err
    assert "[story-guard] starting generation for story 121213" in captured.err
    assert "[story-guard] rendering Markdown and PDF reports" in captured.err
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


def _assert_batch_skipped(tmp_path: Path, story_id: str) -> None:
    assert not (tmp_path / f"{story_id}.md").exists()
    assert not (tmp_path / f"{story_id}.pdf").exists()
    assert [path.name for path in tmp_path.iterdir()] == ["runs.jsonl"]
    rows = [
        json.loads(line)
        for line in (tmp_path / "runs.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert rows == [{"requested": [story_id], "written": [], "skipped": [story_id]}]


def test_score_command_does_not_call_the_model(monkeypatch, capsys):
    def fail(score):
        raise AssertionError("narrative ran")

    monkeypatch.setattr("story_guard.graph.request_narrative", fail)
    assert main(["score", "--story-id", "121213"]) == 0
    capsys.readouterr()


@pytest.mark.parametrize("story_id", ["abc", ""])
def test_bad_story_id_writes_no_report(tmp_path, monkeypatch, capsys, story_id):
    monkeypatch.setattr("story_guard.graph.artifacts_dir", lambda: tmp_path)

    def fail(score):
        raise AssertionError("narrative ran")

    monkeypatch.setattr("story_guard.graph.request_narrative", fail)
    assert main(["generate", "--story-id", story_id]) == 1
    _assert_batch_skipped(tmp_path, story_id)
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
    _assert_batch_skipped(tmp_path, "121213")
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
    _assert_batch_skipped(tmp_path, "121213")
    assert "test_count" in capsys.readouterr().err


def test_narrative_coverage_claim_writes_no_artifact(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("story_guard.graph.artifacts_dir", lambda: tmp_path)

    def covered_ac(score):
        result = _fake_narrative(score)
        result["narrative"]["headline"] = "AC-1 is covered."
        return result

    monkeypatch.setattr("story_guard.graph.request_narrative", covered_ac)
    assert main(["generate", "--story-id", "121213"]) == 1
    _assert_batch_skipped(tmp_path, "121213")
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
    _assert_batch_skipped(tmp_path, "121213")
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
    assert "8 acceptance criteria | 0 adequately covered | 0 with gaps | 8 not covered" in report
    assert "Tests: 2. Mapped: 0. Bugs: 1." in report
    assert "Password field is not accepting special characters" in report
    assert "Raw test IDs: 121216, 121228" in report
    assert "Test suites:" not in report
    assert "Suite 121215" not in report
    capsys.readouterr()


def _case(test_id: str, title: str, steps: str = "") -> dict:
    row = {
        "id": test_id,
        "title": title,
        "type": "",
        "mapped_ac_ids": [],
        "last_result": "",
        "last_result_at": None,
        "linked_bug_ids": [],
        "suite_id": "121215",
        "suite_name": "Story Guard - AI Agent",
        "suite_type": "staticTestSuite",
        "plan_id": "121214",
    }
    if steps:
        row["steps"] = steps
    return row


def test_live_generate_links_positive_negative_and_adhoc_before_the_report(
    tmp_path, monkeypatch
):
    """Report generation maps the cases. The written mapping and the PDF use those links."""
    from pypdf import PdfReader

    from story_guard import graph
    from story_guard.ado_client import ADOClient
    from story_guard.analysis import result_from_judgment

    raw_ac = (
        "Scenario: AC-03 Password visibility — Show\n"
        "Expected: When the user has entered a password and clicks Show, "
        "the password is displayed as plain text.\n"
        "Scenario: AC-04 Forgot Password navigation\n"
        "Expected: When the user clicks Forgot Password?, "
        "the user is redirected to the password recovery page.\n"
    )

    class FakeADOClient:
        def load_live_story(self, story_id, test_plan_id=None):
            return {
                "id": "123086",
                "title": "SNAP Login Screen - Admin",
                "type": "User Story",
                "state": "New",
                "description": "",
                "area": "Ecom MVP",
                "iteration": "Ecom MVP",
                "raw_ac_text": raw_ac,
                "acceptance_criteria": [],
                "tests": [
                    _case("121224", "Verify 'Show' toggle reveals the entered password"),
                    _case("123378", "Verify click Show button with an invalid password"),
                    _case("123379", "Verify Show password with leading/trailing spaces"),
                    _case("121228", "Verify navigation to the Forgot Password flow"),
                    _case("123390", "Verify click Forgot Password with empty credentials"),
                    _case(
                        "123396",
                        "Verify navigate using keyboard",
                        "Use Tab to focus Forgot Password?. The password recovery page opens.",
                    ),
                ],
                "bugs": [],
            }

    monkeypatch.setattr(ADOClient, "from_env", classmethod(lambda cls: FakeADOClient()))
    monkeypatch.setattr("story_guard.graph.artifacts_dir", lambda: tmp_path)
    monkeypatch.setattr("story_guard.cli.record_success", lambda *_args: None)

    def fake_analyze(record):
        return result_from_judgment(
            record,
            {
                "headline": "No open bugs.",
                "health": "No open bugs",
                "analysis": "The model reviewed every acceptance criterion.",
                "reviews": [
                    {
                        "ac_id": "AC-03",
                        "mapped_test_ids": ["121224", "123378", "123379"],
                        "test_types": {
                            "121224": "happy",
                            "123378": "negative",
                            "123379": "adhoc",
                        },
                        "coverage_status": "adequate",
                        "quality": {"status": "good", "testable": True, "issues": []},
                    },
                    {
                        "ac_id": "AC-04",
                        "mapped_test_ids": ["121228", "123390", "123396"],
                        "test_types": {
                            "121228": "happy",
                            "123390": "negative",
                            "123396": "adhoc",
                        },
                        "coverage_status": "adequate",
                        "quality": {"status": "good", "testable": True, "issues": []},
                    },
                ],
            },
            token_count=12,
            narrative_latency_ms=5,
        )

    monkeypatch.setattr(graph, "analyze_live", fake_analyze)

    assert main(["generate", "--story-id", "123086", "--live"]) == 0

    report = (tmp_path / "123086.md").read_text(encoding="utf-8")
    assert "2 adequately covered" in report
    assert "AC-03: linked tests 121224, 123378, 123379" in report
    assert "AC-04: linked tests 121228, 123390, 123396" in report
    pdf_text = "\n".join(
        page.extract_text() or "" for page in PdfReader(tmp_path / "123086.pdf").pages
    )
    assert "Positive scenarios are covered" in pdf_text
    assert "Negative scenarios are covered" in pdf_text
    assert "Adhoc scenarios are covered" in pdf_text
    assert pdf_text.count("Adequate") >= 2


def _live_story(story_id: str) -> dict:
    return {
        "id": story_id,
        "title": f"Story {story_id}",
        "type": "User Story",
        "state": "New",
        "description": "",
        "area": "Ecom MVP",
        "iteration": "Ecom MVP",
        "raw_ac_text": (
            "Scenario: AC-01 Admin signs in\n"
            "Expected: The admin reaches the dashboard."
        ),
        "tests": [
            {
                "id": "42",
                "title": "Admin signs in",
                "type": "",
                "mapped_ac_ids": [],
                "last_result": "",
                "last_result_at": None,
                "linked_bug_ids": [],
                "suite_id": "S1",
                "suite_name": "Suite",
            }
        ],
        "bugs": [],
    }


@pytest.mark.parametrize("mode", ["json", "down", "timeout"])
def test_a_failed_story_writes_nothing_and_the_next_story_still_runs(
    tmp_path, monkeypatch, capsys, mode
):
    import json

    from story_guard.ado_client import ADOClient
    from story_guard.narrative import ATTEMPTS, NarrativeError

    calls = {"111111": 0, "222222": 0}

    class FakeADOClient:
        def load_live_story(self, story_id, test_plan_id=None):
            return _live_story(str(story_id))

    def fake_chat(messages, num_predict=8192):
        payload = json.loads(messages[1]["content"].split("\n", 1)[1])
        story_id = payload["story_id"]
        calls[story_id] += 1
        if story_id == "111111":
            if mode == "down":
                raise NarrativeError("ollama request failed: connection refused")
            if mode == "timeout":
                return {
                    "message": {
                        "content": json.dumps(
                            {
                                "ac_id": "AC-01",
                                "mapped_test_ids": [],
                                "finding": "No listed test checks AC-01.",
                            }
                        )
                    },
                    "load_duration": 0,
                    "total_duration": 181_000_000_000,
                    "eval_count": 1,
                }
            return {"message": {"content": "not json"}}
        return {
            "message": {
                "content": json.dumps(
                    {
                        "ac_id": "AC-01",
                        "mapped_test_ids": ["42"],
                        "test_types": {"42": "happy"},
                        "coverage_status": "partial",
                        "quality": {"status": "good", "testable": True, "issues": []},
                        "finding": "AC-01 is checked by 42.",
                    }
                )
            },
            "prompt_eval_count": 2,
            "eval_count": 3,
        }

    monkeypatch.setattr(ADOClient, "from_env", classmethod(lambda cls: FakeADOClient()))
    monkeypatch.setattr("story_guard.graph.artifacts_dir", lambda: tmp_path)
    monkeypatch.setattr("story_guard.analysis.ollama_chat", fake_chat)
    monkeypatch.setattr("story_guard.cli.record_success", lambda *_args: None)

    code = main(
        [
            "generate",
            "--story-id",
            "111111",
            "--story-id",
            "222222",
            "--live",
        ]
    )
    captured = capsys.readouterr()

    assert code == 1
    assert "story 111111:" in captured.err
    assert not (tmp_path / "111111.md").exists()
    assert not (tmp_path / "111111.pdf").exists()
    assert (tmp_path / "222222.md").is_file()
    assert (tmp_path / "222222.pdf").is_file()
    assert str(tmp_path / "222222.md") in captured.out
    assert str(tmp_path / "111111.md") not in captured.out
    assert calls["111111"] == (ATTEMPTS if mode == "json" else 1)
    assert calls["222222"] == 1
    rows = [
        json.loads(line)
        for line in (tmp_path / "runs.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert rows == [
        {
            "requested": ["111111", "222222"],
            "written": ["222222"],
            "skipped": ["111111"],
        }
    ]


def test_graph_live_path_does_not_call_behavior_links():
    import story_guard.analysis as analysis
    import story_guard.graph as graph

    graph_source = inspect.getsource(graph)
    analysis_source = inspect.getsource(analysis)
    assert "apply_behavior_links" not in graph_source
    assert "apply_behavior_links" not in analysis_source
    for test_id in range(121216, 121234):
        assert str(test_id) not in graph_source
        assert str(test_id) not in analysis_source


def test_live_generate_with_no_tests_renders_without_a_model_call(
    tmp_path, monkeypatch
):
    from pypdf import PdfReader

    from story_guard.ado_client import ADOClient

    def fail_chat(*_args, **_kwargs):
        raise AssertionError("model call")

    class FakeADOClient:
        def load_live_story(self, story_id, test_plan_id=None):
            return {
                "id": "123086",
                "title": "SNAP Login Screen - Admin",
                "type": "User Story",
                "state": "New",
                "description": "",
                "area": "Ecom MVP",
                "iteration": "Ecom MVP",
                "raw_ac_text": (
                    "Scenario: AC-01 Admin signs in\n"
                    "Expected: The admin reaches the dashboard."
                ),
                "tests": [],
                "bugs": [],
            }

    monkeypatch.setattr(ADOClient, "from_env", classmethod(lambda cls: FakeADOClient()))
    monkeypatch.setattr("story_guard.graph.artifacts_dir", lambda: tmp_path)
    monkeypatch.setattr("story_guard.analysis.ollama_chat", fail_chat)
    monkeypatch.setattr("story_guard.cli.record_success", lambda *_args: None)

    assert main(["generate", "--story-id", "123086", "--live"]) == 0

    report = (tmp_path / "123086.md").read_text(encoding="utf-8")
    assert "1 acceptance criteria | 0 adequately covered | 0 with gaps | 1 not covered" in report
    assert "Tests: 0. Mapped: 0. Bugs: 0." in report
    assert "No listed test checks AC-01." in report
    pdf_text = "\n".join(
        page.extract_text() or "" for page in PdfReader(tmp_path / "123086.pdf").pages
    )
    assert "No coverage" in pdf_text
    assert "No open bugs" in pdf_text


def test_live_generate_accepts_test_ids_outside_the_fixture_range(tmp_path, monkeypatch):
    from story_guard import graph
    from story_guard.ado_client import ADOClient
    from story_guard.analysis import result_from_judgment

    class FakeADOClient:
        def load_live_story(self, story_id, test_plan_id=None):
            return {
                "id": "123086",
                "title": "SNAP Login Screen - Admin",
                "type": "User Story",
                "state": "New",
                "description": "",
                "area": "Ecom MVP",
                "iteration": "Ecom MVP",
                "raw_ac_text": (
                    "Scenario: AC-01 Admin signs in\n"
                    "Expected: The admin reaches the dashboard."
                ),
                "tests": [
                    _case("42", "Admin signs in"),
                    _case("77", "Admin is rejected"),
                ],
                "bugs": [],
            }

    seen = {}

    def fake_analyze(record):
        seen["ids"] = [test["id"] for test in record["tests"]]
        seen["links"] = [test["mapped_ac_ids"] for test in record["tests"]]
        return result_from_judgment(
            record,
            {
                "headline": "No open bugs.",
                "health": "No open bugs",
                "analysis": "The model reviewed the fetched tests.",
                "reviews": [
                    {
                        "ac_id": "AC-01",
                        "mapped_test_ids": ["42"],
                        "test_types": {"42": "happy"},
                        "coverage_status": "partial",
                        "quality": {"status": "good", "testable": True, "issues": []},
                    }
                ],
            },
        )

    monkeypatch.setattr(ADOClient, "from_env", classmethod(lambda cls: FakeADOClient()))
    monkeypatch.setattr("story_guard.graph.artifacts_dir", lambda: tmp_path)
    monkeypatch.setattr(graph, "analyze_live", fake_analyze)
    monkeypatch.setattr("story_guard.cli.record_success", lambda *_args: None)

    assert main(["generate", "--story-id", "123086", "--live"]) == 0

    assert seen["ids"] == ["42", "77"]
    assert seen["links"] == [[], []]
    report = (tmp_path / "123086.md").read_text(encoding="utf-8")
    assert "Raw test IDs: 42, 77" in report


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
    _assert_batch_skipped(tmp_path, "121213")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert str(exception) in captured.err


def test_usage_lists_the_batch_forms(capsys):
    assert main([]) == 0
    text = capsys.readouterr().out
    for line in (
        "story-guard score --story-id 121213",
        "story-guard generate --story-id 123086 --live",
        "story-guard generate --story-id 121213 --story-id 123086 --live",
        "story-guard generate --story-ids 121213,123086 --live",
        'story-guard generate --sprint "<iteration path>" --live',
        "story-guard generate --story-id 121213 --test-plan-id 121214 --live",
    ):
        assert line in text


def test_offline_score_is_unchanged(monkeypatch, capsys):
    def fail():
        raise AssertionError("model setup ran")

    monkeypatch.setattr("story_guard.cli.keep_only_model", fail)
    assert main(["score", "--story-id", "121213"]) == 0
    score = json.loads(capsys.readouterr().out)
    assert score["story_id"] == "121213"
    assert score["health"] == "No open bugs"
    assert score["mapped_count"] == 0
    assert score["scenario_count"] == 8
    assert score["test_count"] == 18
    assert score["rule_ids"] == ["SR-1", "SR-2", "SR-3"]
    with pytest.raises(SystemExit) as raised:
        main(["score", "--story-id", "121213", "--story-ids", "123086"])
    assert raised.value.code == 2
    with pytest.raises(SystemExit) as raised:
        main(["score", "--sprint", "Ecom MVP"])
    assert raised.value.code == 2


def _batch_client(loaded: list[tuple[int, int | None]]):
    from story_guard.ado_client import ADOClient

    class FakeADOClient:
        def story_ids_for_iteration(self, path):
            assert path == "Ecom MVP\\Phase"
            return ["121213", "123086"]

        def load_live_story(self, story_id, test_plan_id=None):
            loaded.append((story_id, test_plan_id))
            return _live_story(str(story_id))

    return FakeADOClient


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["generate", "--story-id", "123086", "--live"], ["123086"]),
        (
            ["generate", "--story-id", "121213", "--story-id", "123086", "--live"],
            ["121213", "123086"],
        ),
        (["generate", "--story-ids", "121213, 123086", "--live"], ["121213", "123086"]),
        (["generate", "--sprint", "Ecom MVP\\Phase", "--live"], ["121213", "123086"]),
        (
            ["generate", "--story-id", "123086", "--story-id", "123086", "--live"],
            ["123086"],
        ),
    ],
)
def test_batch_forms_write_each_story_without_overlapping_calls(
    tmp_path, monkeypatch, capsys, argv, expected
):
    from story_guard.ado_client import ADOClient
    from story_guard.prefix import load_prefix
    import hashlib

    loaded: list[tuple[int, int | None]] = []
    state = {"in_flight": 0, "max_in_flight": 0, "ids": []}
    order: list[str] = []

    def keep():
        order.append("keep")

    def fake_chat(messages, num_predict=8192):
        assert order == ["keep"]
        state["in_flight"] += 1
        state["max_in_flight"] = max(state["max_in_flight"], state["in_flight"])
        time.sleep(0.02)
        try:
            payload = json.loads(messages[1]["content"].split("\n", 1)[1])
            state["ids"].append(payload["story_id"])
            ac_id = payload["acceptance_criterion"]["ac_id"]
            return {
                "message": {
                    "content": json.dumps(
                        {
                            "ac_id": ac_id,
                            "mapped_test_ids": ["42"],
                            "test_types": {"42": "happy"},
                            "coverage_status": "partial",
                            "quality": {"status": "good", "testable": True, "issues": []},
                            "finding": f"{ac_id} is checked by 42.",
                        }
                    )
                },
                "prompt_eval_count": 2,
                "eval_count": 3,
            }
        finally:
            state["in_flight"] -= 1

    monkeypatch.setattr(ADOClient, "from_env", classmethod(lambda cls: _batch_client(loaded)()))
    monkeypatch.setattr("story_guard.graph.artifacts_dir", lambda: tmp_path)
    monkeypatch.setattr("story_guard.cli.keep_only_model", keep)
    monkeypatch.setattr("story_guard.analysis.ollama_chat", fake_chat)
    monkeypatch.setenv("LANGSMITH_API_KEY", "")

    assert main(argv) == 0
    assert state["max_in_flight"] == 1
    assert state["ids"] == expected
    assert order == ["keep"]
    assert [story_id for story_id, plan_id in loaded] == [int(story_id) for story_id in expected]
    assert all(plan_id is None for _story_id, plan_id in loaded)
    digest = hashlib.sha256(load_prefix().encode("utf-8")).hexdigest()
    rows = [
        json.loads(line)
        for line in (tmp_path / "runs.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    story_rows = [row for row in rows if "story_id" in row]
    assert [row["story_id"] for row in story_rows] == expected
    assert all(row["token_count"] == 5 and row["prefix_sha256"] == digest for row in story_rows)
    assert rows[-1] == {"requested": expected, "written": expected, "skipped": []}
    for story_id in expected:
        assert (tmp_path / f"{story_id}.md").is_file()
        assert (tmp_path / f"{story_id}.pdf").is_file()
    capsys.readouterr()


def test_batch_keeps_qwen35_4b_as_the_only_loaded_model(tmp_path, monkeypatch, capsys):
    from story_guard.ado_client import ADOClient

    class _Body:
        def __init__(self, raw: bytes):
            self._raw = raw

        def read(self, _n=-1):
            return self._raw

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    seen: list[tuple[str, str, bytes | None]] = []
    state = {"in_flight": 0, "max_in_flight": 0}
    models: list[str] = []

    def fake_urlopen(request, timeout):
        url = request.full_url
        seen.append((url, request.get_method(), request.data))
        assert "pull" not in url
        if url.endswith("/api/ps"):
            raw = json.dumps(
                {"models": [{"name": "qwen3.5:9b"}, {"name": "qwen3.5:4b"}]}
            ).encode("utf-8")
            return _Body(raw)
        if url.endswith("/api/generate"):
            return _Body(b'{"done": true}')
        state["in_flight"] += 1
        state["max_in_flight"] = max(state["max_in_flight"], state["in_flight"])
        time.sleep(0.02)
        try:
            body = json.loads(request.data.decode("utf-8"))
            models.append(body["model"])
            payload = json.loads(body["messages"][1]["content"].split("\n", 1)[1])
            ac_id = payload["acceptance_criterion"]["ac_id"]
            content = json.dumps(
                {
                    "ac_id": ac_id,
                    "mapped_test_ids": ["42"],
                    "test_types": {"42": "happy"},
                    "coverage_status": "partial",
                    "quality": {"status": "good", "testable": True, "issues": []},
                    "finding": f"{ac_id} is checked by 42.",
                }
            )
            raw = json.dumps(
                {
                    "message": {"role": "assistant", "content": content},
                    "prompt_eval_count": 4,
                    "eval_count": 5,
                }
            ).encode("utf-8")
            return _Body(raw)
        finally:
            state["in_flight"] -= 1

    class FakeADOClient:
        def load_live_story(self, story_id, test_plan_id=None):
            assert test_plan_id is None
            return _live_story(str(story_id))

    _pin_ollama_env(tmp_path, monkeypatch)
    monkeypatch.setenv("LANGSMITH_API_KEY", "")
    monkeypatch.setattr("story_guard.narrative.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr(ADOClient, "from_env", classmethod(lambda cls: FakeADOClient()))
    monkeypatch.setattr("story_guard.graph.artifacts_dir", lambda: tmp_path)

    assert main(["generate", "--story-ids", "121213,123086", "--live"]) == 0
    assert models == ["qwen3.5:4b", "qwen3.5:4b"]
    assert state["max_in_flight"] == 1
    unloads = [
        json.loads(data.decode("utf-8"))
        for url, method, data in seen
        if method == "POST" and url.endswith("/api/generate") and data is not None
    ]
    assert unloads == [{"model": "qwen3.5:9b", "keep_alive": 0}]
    assert (tmp_path / "121213.pdf").is_file()
    assert (tmp_path / "123086.pdf").is_file()
    capsys.readouterr()


def test_test_plan_id_rejects_more_than_one_story(tmp_path, monkeypatch, capsys):
    from story_guard.ado_client import ADOClient

    def fail(cls):
        raise AssertionError("ADO client was constructed")

    monkeypatch.setattr(ADOClient, "from_env", classmethod(fail))
    monkeypatch.setattr("story_guard.graph.artifacts_dir", lambda: tmp_path)
    code = main(
        [
            "generate",
            "--story-id",
            "121213",
            "--story-id",
            "123086",
            "--test-plan-id",
            "121214",
            "--live",
        ]
    )
    assert code == 1
    assert "--test-plan-id applies only to one story" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


def test_test_plan_id_rejects_a_sprint_of_two_stories(tmp_path, monkeypatch, capsys):
    from story_guard.ado_client import ADOClient

    class FakeADOClient:
        def story_ids_for_iteration(self, _path):
            return ["121213", "123086"]

        def load_live_story(self, _story_id, _test_plan_id=None):
            raise AssertionError("story was loaded")

    monkeypatch.setattr(ADOClient, "from_env", classmethod(lambda cls: FakeADOClient()))
    monkeypatch.setattr("story_guard.graph.artifacts_dir", lambda: tmp_path)
    code = main(
        [
            "generate",
            "--sprint",
            "Ecom MVP\\Phase",
            "--test-plan-id",
            "121214",
            "--live",
        ]
    )
    assert code == 1
    assert "--test-plan-id applies only to one story" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


def test_test_plan_id_applies_to_one_sprint_story(tmp_path, monkeypatch, capsys):
    from story_guard.ado_client import ADOClient

    seen = []

    class FakeADOClient:
        def story_ids_for_iteration(self, path):
            assert path == "Ecom MVP\\Phase"
            return ["123086"]

        def load_live_story(self, story_id, test_plan_id=None):
            seen.append((story_id, test_plan_id))
            story = _live_story("123086")
            story["tests"] = []
            return story

    monkeypatch.setattr(ADOClient, "from_env", classmethod(lambda cls: FakeADOClient()))
    monkeypatch.setattr("story_guard.graph.artifacts_dir", lambda: tmp_path)
    monkeypatch.setattr("story_guard.cli.keep_only_model", lambda: None)
    monkeypatch.setenv("LANGSMITH_API_KEY", "")
    assert (
        main(
            [
                "generate",
                "--sprint",
                "Ecom MVP\\Phase",
                "--test-plan-id",
                "121214",
                "--live",
            ]
        )
        == 0
    )
    assert seen == [(123086, 121214)]
    assert (tmp_path / "123086.pdf").is_file()
    assert not (tmp_path / "121213.pdf").exists()
    capsys.readouterr()


def test_sprint_without_ado_configuration_exits_cleanly(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("story_guard.envfile.env_path", lambda: tmp_path / "missing.env")
    monkeypatch.delenv("ADO_PROJECT_URL", raising=False)
    monkeypatch.delenv("ADO_PAT", raising=False)

    result = main(["generate", "--sprint", "Project\\Sprint"])

    captured = capsys.readouterr()
    assert result == 1
    assert captured.out == ""
    assert "ADO_PROJECT_URL, ADO_PAT" in captured.err


def test_empty_sprint_generates_nothing(tmp_path, monkeypatch, capsys):
    from story_guard.ado_client import ADOClient

    class FakeADOClient:
        def story_ids_for_iteration(self, _path):
            return []

        def load_live_story(self, _story_id, _test_plan_id=None):
            raise AssertionError("story was loaded")

    monkeypatch.setattr(ADOClient, "from_env", classmethod(lambda cls: FakeADOClient()))
    monkeypatch.setattr("story_guard.graph.artifacts_dir", lambda: tmp_path)
    assert main(["generate", "--sprint", "Ecom MVP\\Empty", "--live"]) == 1
    assert "has no user stories" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


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
