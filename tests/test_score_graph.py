"""Four code nodes through score_health. A bad story id writes nothing."""

import inspect
import json
from pathlib import Path

import pytest

from story_guard.cli import main
from story_guard.graph import ContractError, GateError, build_graph, run, validate_contract

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "FIX-121213.json"


def test_score_graph_order():
    edges = {(edge.source, edge.target) for edge in build_graph().get_graph().edges}
    assert edges == {
        ("__start__", "gate_input"),
        ("gate_input", "fetch"),
        ("fetch", "validate_contract"),
        ("validate_contract", "score_health"),
        ("score_health", "__end__"),
    }


def test_score_graph_nodes_do_not_call_a_model():
    from story_guard import graph

    for fn in (graph.gate_input, graph.fetch, graph.validate_contract, graph.score_health):
        source = inspect.getsource(fn)
        assert "ollama" not in source.lower()
        assert "11434" not in source


@pytest.mark.parametrize("story_id", ["", "   ", "abc", "999999", "121214"])
def test_score_gate_rejects_before_fetch(monkeypatch, story_id):
    def fail_fetch(state):
        raise AssertionError("fetch ran")

    monkeypatch.setattr("story_guard.graph.fetch", fail_fetch)
    with pytest.raises(GateError):
        run({"story_id": story_id})


def test_score_contract_stops_before_score(monkeypatch):
    record = json.loads(FIXTURE.read_text(encoding="utf-8"))
    del record["tests"]

    def bad_fetch(state):
        return {"record": record}

    def fail_score(state):
        raise AssertionError("score ran")

    monkeypatch.setattr("story_guard.graph.fetch", bad_fetch)
    monkeypatch.setattr("story_guard.graph.score_health", fail_score)
    with pytest.raises(ContractError):
        run({"story_id": "121213"})


def test_score_contract_rejects_title_prefix_as_type():
    record = json.loads(FIXTURE.read_text(encoding="utf-8"))
    record["tests"][0]["type"] = "P"
    with pytest.raises(ContractError):
        validate_contract({"story_id": "121213", "record": record})


def test_score_command_prints_json(capsys):
    assert main(["score", "--story-id", "121213"]) == 0
    score = json.loads(capsys.readouterr().out)
    assert score["health"] == "No open bugs"
    assert score["health_band"] == "No open bugs"
    assert score["rule_ids"] == ["SR-1", "SR-2", "SR-3"]
    assert "rag" not in score
    assert score["mapped_count"] == 0
    assert score["scenario_count"] == 8
    assert score["test_count"] == 18
    assert score["bug_count"] == 0
    assert score["none_count"] == 8
    assert score["ac_field"] == "empty"


def test_score_bad_id_exits_nonzero(capsys):
    assert main(["score", "--story-id", "999999"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "999999" in captured.err


def test_score_commands_write_no_artifact(capsys):
    artifacts = ROOT / "artifacts"
    before = set(artifacts.rglob("*")) if artifacts.exists() else set()
    assert main(["score", "--story-id", "999999"]) == 1
    assert main(["score", "--story-id", "121213"]) == 0
    after = set(artifacts.rglob("*")) if artifacts.exists() else set()
    assert after == before
    capsys.readouterr()
