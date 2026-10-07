"""story-guard generate writes markdown from the fixture. A failed narrative writes nothing."""

import inspect
from pathlib import Path

import pytest

from story_guard.cli import main
from story_guard.graph import build_generate_graph, fetch
from story_guard.narrative import NarrativeError
from story_guard.render import RenderError, render_markdown

ROOT = Path(__file__).resolve().parents[1]
HEADINGS = (
    "# Title block",
    "# Story health",
    "# Acceptance criteria vs test coverage",
    "# Bug details",
    "# Recommended actions",
    "# Appendix",
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


def test_generate_writes_the_six_headings(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("ADO_PAT", raising=False)
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.setattr("story_guard.graph.artifacts_dir", lambda: tmp_path)
    monkeypatch.setattr("story_guard.graph.request_narrative", _fake_narrative)
    assert main(["generate", "--story-id", "121213"]) == 0
    report = tmp_path / "121213.md"
    assert report.is_file()
    assert not (tmp_path / "121213.pdf").exists()
    text = report.read_text(encoding="utf-8")
    assert [line for line in text.splitlines() if line.startswith("# ")] == list(HEADINGS)
    assert "Story Health Report" in text
    assert "dummy fixture" in text
    assert "The AC field is empty." in text
    assert "No open bugs" in text
    assert "8 acceptance criteria | 0 adequately covered | 0 with gaps | 8 not covered" in text
    assert "Tests: 18. Mapped: 0. Bugs: 0." in text
    assert "Color key: Adequate, Partial, None." in text
    assert "Bug ID" in text and "Assigned To" in text
    assert "No bugs." in text
    assert "partially covered" not in text
    assert "%" not in text
    printed = capsys.readouterr().out.strip()
    assert printed == str(report)


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


def test_live_flag_exits_before_the_graph(monkeypatch, capsys):
    def fail(_state):
        raise AssertionError("graph ran")

    monkeypatch.setattr("story_guard.cli.run_generate", fail)
    assert main(["generate", "--story-id", "121213", "--live"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "not wired" in captured.err


def test_generate_path_does_not_name_ado_pat():
    import story_guard.cli as cli
    import story_guard.graph as graph
    import story_guard.narrative as narrative
    import story_guard.prefix as prefix
    import story_guard.render as render
    import story_guard.trace as trace

    for module in (cli, graph, narrative, prefix, render, trace):
        assert "ADO_PAT" not in inspect.getsource(module)


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
