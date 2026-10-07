"""Code-node graph. Later slices add narrative and PDF nodes in this module."""

import json
from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from story_guard.score import score_health as score_record

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
    return {"record": record}


def validate_contract(state: GraphState) -> dict:
    errors = _contract_errors(state.get("record"), state.get("story_id"))
    if errors:
        raise ContractError("; ".join(errors))
    return {}


def score_health(state: GraphState) -> dict:
    return {"score": score_record(state["record"])}


def build_graph():
    builder = StateGraph(GraphState)
    builder.add_node("gate_input", gate_input)
    builder.add_node("fetch", fetch)
    builder.add_node("validate_contract", validate_contract)
    builder.add_node("score_health", score_health)
    builder.add_edge(START, "gate_input")
    builder.add_edge("gate_input", "fetch")
    builder.add_edge("fetch", "validate_contract")
    builder.add_edge("validate_contract", "score_health")
    builder.add_edge("score_health", END)
    return builder.compile()


def run(state: GraphState | None = None) -> GraphState:
    return build_graph().invoke(state or {})


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
