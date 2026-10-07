"""Code-node graph. score stops after score_health. generate continues through the report."""

import json
from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from story_guard.narrative import write_narrative as request_narrative
from story_guard.render import render_markdown
from story_guard.score import score_health as score_record
from story_guard.test_adapter import DummyTestAdapterError, fetch_tests

# Keys and the test-type enum are the ones named in fixtures/SCHEMA.md.
STORY_KEYS = (
    "id",
    "title",
    "type",
    "state",
    "description",
    "area",
    "iteration",
    "acceptance_criteria_raw",
    "acceptance_criteria",
    "scenarios",
    "note",
)
BUNDLE_KEYS = ("tests", "bugs")
AC_KEYS = ("ac_id", "text", "testable", "flags")
TEST_KEYS = (
    "id",
    "title",
    "type",
    "mapped_ac_ids",
    "last_result",
    "last_result_at",
    "linked_bug_ids",
)
BUG_KEYS = (
    "id",
    "title",
    "severity",
    "priority",
    "status",
    "age",
    "found_in",
    "linked_story_id",
    "linked_tc_id",
)
STRING_STORY_KEYS = (
    "id",
    "title",
    "type",
    "state",
    "description",
    "area",
    "iteration",
    "acceptance_criteria_raw",
    "note",
)
TEST_TYPES = {"happy", "negative", "edge", "security", "adhoc", ""}
_ACCEPTED_STORY_ID = "121213"


class GraphState(TypedDict, total=False):
    story_id: str
    record: dict
    score: dict
    narrative: dict
    markdown_path: str
    token_count: int
    narrative_latency_ms: int


class GateError(Exception):
    """The story id is blank, not numeric, or not the fixture id."""


class ContractError(Exception):
    """The payload does not match fixtures/SCHEMA.md."""


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def gate_input(state: GraphState) -> dict:
    raw = state.get("story_id")
    story_id = raw.strip() if isinstance(raw, str) else ""
    if story_id == "":
        raise GateError("story id is blank")
    if not story_id.isdigit():
        raise GateError("story id is not numeric")
    if story_id != _ACCEPTED_STORY_ID:
        raise GateError(f"story id {story_id} is not in the fixture")
    return {"story_id": story_id}


def fetch(state: GraphState) -> dict:
    path = _repo_root() / "fixtures" / "FIX-121213.json"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ContractError("fixture FIX-121213.json is missing") from exc
    try:
        record = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ContractError("fixture FIX-121213.json is not valid JSON") from exc
    story_id = state.get("story_id")
    if not isinstance(story_id, str) or story_id.strip() == "":
        story_id = str(record.get("id") or "")
    try:
        adapter_rows = fetch_tests(story_id)
    except DummyTestAdapterError as exc:
        raise ContractError(str(exc)) from exc
    record["tests"] = _tests_from_adapter(record.get("tests"), adapter_rows)
    return {"record": record}


def _tests_from_adapter(fixture_tests: object, adapter_rows: list) -> list:
    """Keep fixture TestCase fields. Id, title, and mapped_ac_ids come from the adapter."""
    by_id = {}
    if isinstance(fixture_tests, list):
        for row in fixture_tests:
            if isinstance(row, dict) and row.get("id") is not None:
                by_id[str(row["id"])] = row
    merged = []
    for row in adapter_rows:
        base = dict(by_id.get(str(row.get("id")), {}))
        base.update(row)
        merged.append(base)
    return merged


def validate_contract(state: GraphState) -> dict:
    errors = _contract_errors(state.get("record"), state.get("story_id"))
    if errors:
        raise ContractError("; ".join(errors))
    return {}


def score_health(state: GraphState) -> dict:
    return {"score": score_record(state["record"])}


def write_narrative(state: GraphState) -> dict:
    """One model call. The node passes the score object and nothing else."""
    result = request_narrative(state["score"])
    return {
        "narrative": result["narrative"],
        "token_count": result["token_count"],
        "narrative_latency_ms": result["narrative_latency_ms"],
    }


def render_pdf(state: GraphState) -> dict:
    """Write the markdown report. A later slice adds the PDF file."""
    out = artifacts_dir() / f"{state['story_id']}.md"
    written = render_markdown(
        state["score"],
        state["narrative"],
        _template_path(),
        out,
        record=state.get("record"),
    )
    return {"markdown_path": str(written)}


def artifacts_dir() -> Path:
    return _repo_root() / "artifacts"


def _template_path() -> Path:
    return _repo_root() / "templates" / "health_report.md"


def _score_builder():
    builder = StateGraph(GraphState)
    builder.add_node("gate_input", gate_input)
    builder.add_node("fetch", fetch)
    builder.add_node("validate_contract", validate_contract)
    builder.add_node("score_health", score_health)
    builder.add_edge(START, "gate_input")
    builder.add_edge("gate_input", "fetch")
    builder.add_edge("fetch", "validate_contract")
    builder.add_edge("validate_contract", "score_health")
    return builder


def build_graph():
    builder = _score_builder()
    builder.add_edge("score_health", END)
    return builder.compile()


def build_generate_graph():
    builder = _score_builder()
    builder.add_node("write_narrative", write_narrative)
    builder.add_node("render_pdf", render_pdf)
    builder.add_edge("score_health", "write_narrative")
    builder.add_edge("write_narrative", "render_pdf")
    builder.add_edge("render_pdf", END)
    return builder.compile()


def run(state: GraphState | None = None) -> GraphState:
    return build_graph().invoke(state or {})


def run_generate(state: GraphState | None = None) -> GraphState:
    return build_generate_graph().invoke(state or {})


def _read_schema() -> str:
    path = _repo_root() / "fixtures" / "SCHEMA.md"
    if not path.is_file():
        raise ContractError("fixtures/SCHEMA.md is missing")
    return path.read_text(encoding="utf-8")


def _missing(obj: dict, keys: tuple[str, ...]) -> list[str]:
    return [key for key in keys if key not in obj]


def _contract_errors(record: object, story_id: str | None) -> list[str]:
    schema = _read_schema()
    named = (*STORY_KEYS, *BUNDLE_KEYS, *AC_KEYS, *TEST_KEYS, *BUG_KEYS)
    errors = [f"schema does not name {key}" for key in named if key not in schema]
    if not isinstance(record, dict):
        errors.append("payload is not an object")
        return errors
    missing = _missing(record, STORY_KEYS + BUNDLE_KEYS)
    if missing:
        errors.append("story missing " + ", ".join(missing))
        return errors
    for key in STRING_STORY_KEYS:
        if not isinstance(record[key], str):
            errors.append(f"{key} is not a string")
    if record["type"] != "User Story":
        errors.append("type is not User Story")
    if story_id is not None and record["id"] != story_id:
        errors.append("id does not match story id")
    errors.extend(_list_of(record, "acceptance_criteria", _ac_item_errors))
    errors.extend(_list_of(record, "scenarios", _ac_item_errors))
    errors.extend(_list_of(record, "tests", _test_item_errors))
    errors.extend(_list_of(record, "bugs", _bug_item_errors))
    return errors


def _list_of(record: dict, key: str, check_item) -> list[str]:
    items = record[key]
    if not isinstance(items, list):
        return [f"{key} is not a list"]
    errors: list[str] = []
    for index, item in enumerate(items):
        errors.extend(check_item(item, f"{key}[{index}]"))
    return errors


def _ac_item_errors(item: object, where: str) -> list[str]:
    if not isinstance(item, dict):
        return [f"{where} is not an object"]
    missing = _missing(item, AC_KEYS)
    if missing:
        return [f"{where} missing " + ", ".join(missing)]
    errors = []
    if not isinstance(item["ac_id"], str) or not isinstance(item["text"], str):
        errors.append(f"{where} ac_id and text must be strings")
    if not isinstance(item["testable"], bool):
        errors.append(f"{where} testable is not a boolean")
    if not isinstance(item["flags"], list):
        errors.append(f"{where} flags is not a list")
    return errors


def _test_item_errors(item: object, where: str) -> list[str]:
    if not isinstance(item, dict):
        return [f"{where} is not an object"]
    missing = _missing(item, TEST_KEYS)
    if missing:
        return [f"{where} missing " + ", ".join(missing)]
    errors = []
    for key in ("id", "title", "type", "last_result"):
        if not isinstance(item[key], str):
            errors.append(f"{where} {key} is not a string")
    if item["type"] not in TEST_TYPES:
        errors.append(f"{where} type is not a schema type")
    if item["last_result_at"] is not None and not isinstance(item["last_result_at"], str):
        errors.append(f"{where} last_result_at is not a string")
    errors.extend(_string_list(item["mapped_ac_ids"], f"{where} mapped_ac_ids"))
    errors.extend(_string_list(item["linked_bug_ids"], f"{where} linked_bug_ids"))
    return errors


def _bug_item_errors(item: object, where: str) -> list[str]:
    if not isinstance(item, dict):
        return [f"{where} is not an object"]
    missing = _missing(item, BUG_KEYS)
    if missing:
        return [f"{where} missing " + ", ".join(missing)]
    errors = []
    string_keys = (
        "id",
        "title",
        "severity",
        "priority",
        "status",
        "found_in",
        "linked_story_id",
        "linked_tc_id",
    )
    for key in string_keys:
        if not isinstance(item[key], str):
            errors.append(f"{where} {key} is not a string")
    age = item["age"]
    if isinstance(age, bool) or not isinstance(age, (int, str)):
        errors.append(f"{where} age is not a number or string")
    return errors


def _string_list(value: object, label: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        return [f"{label} is not a list of strings"]
    return []
