"""Code-node graph. score stops after score_health. generate continues through the report."""

import html
import json
import os
import re
from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from story_guard.analysis import analyze_live
from story_guard.narrative import (
    NarrativeError,
    enforce_narrative_rules,
    write_narrative as request_narrative,
)
from story_guard.render import (
    RenderError,
    render_markdown,
    render_pdf as render_pdf_file,
    validate_template,
)
from story_guard.score import apply_behavior_links, score_health as score_record, scored_criteria
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
    live: bool
    test_plan_id: str
    record: dict
    score: dict
    narrative: dict
    markdown_path: str
    pdf_path: str
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
    live = state.get("live", False)
    if not isinstance(live, bool):
        raise GateError("live flag must be a boolean")
    if story_id != _ACCEPTED_STORY_ID and not live:
        raise GateError(f"story id {story_id} is not in the fixture")
    plan_id = state.get("test_plan_id")
    if plan_id is not None:
        plan_id = plan_id.strip() if isinstance(plan_id, str) else ""
        if plan_id == "" or not plan_id.isdigit() or plan_id == "0":
            raise GateError("test plan id is not numeric")
        if not live:
            raise GateError("test plan id requires --live")
    validate_template(_template_path())
    gated = {"story_id": story_id, "live": live}
    if plan_id:
        gated["test_plan_id"] = plan_id
    return gated


def fetch(state: GraphState) -> dict:
    if state.get("live", False):
        return {"record": _fetch_live(state)}
    path = _repo_root() / "fixtures" / "FIX-121213.json"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ContractError("fixture FIX-121213.json is missing") from exc
    try:
        fixture_record = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ContractError("fixture FIX-121213.json is not valid JSON") from exc

    story_id = state.get("story_id")
    if not isinstance(story_id, str) or story_id.strip() == "":
        story_id = str(fixture_record.get("id") or "")

    try:
        adapter_rows = fetch_tests(story_id)
    except DummyTestAdapterError as exc:
        raise ContractError(str(exc)) from exc
    fixture_record["tests"] = _tests_from_adapter(fixture_record.get("tests"), adapter_rows)
    return {"record": fixture_record}


def _fetch_live(state: GraphState) -> dict:
    """Load the story and the cases in its Azure DevOps test plan."""
    from story_guard.ado_client import ADOClient

    story_id = state.get("story_id")
    if not isinstance(story_id, str) or not story_id.isdigit():
        raise GateError("story id is not numeric")
    plan_text = state.get("test_plan_id")
    plan_id = int(plan_text) if isinstance(plan_text, str) and plan_text.isdigit() else None
    story = ADOClient.from_env().load_live_story(int(story_id), plan_id)
    record = _story_record_from_ado(story, _blank_story_record())
    record["tests"] = apply_behavior_links(
        scored_criteria(record),
        list(story.get("tests") or []),
    )
    record["bugs"] = list(story.get("bugs") or [])
    return record


def _blank_story_record() -> dict:
    return {
        "id": "",
        "title": "",
        "type": "",
        "state": "",
        "description": "",
        "area": "",
        "iteration": "",
        "acceptance_criteria_raw": "",
        "acceptance_criteria": [],
        "scenarios": [],
        "note": "",
        "tests": [],
        "bugs": [],
    }


def _story_record_from_ado(story: dict, fixture_record: dict) -> dict:
    """Replace fixture story fields with ADO fields while keeping fixture test data."""
    record = dict(fixture_record)
    description = story.get("description") or ""
    raw_ac = story.get("raw_ac_text") or ""
    record.update(
        {
            "id": story["id"],
            "title": story["title"],
            "type": story["type"],
            "state": story["state"],
            "description": description,
            "area": story.get("area") or "",
            "iteration": story.get("iteration") or "",
            "acceptance_criteria_raw": raw_ac,
            "acceptance_criteria": _criteria_from_text(raw_ac),
            "scenarios": _criteria_from_text(description),
            "source": "ADO dummy project",
        }
    )
    return record


_AC_LABEL = re.compile(r"^(AC-\d+)\b[:\s-]*(.*)$", re.IGNORECASE)


def _plain_lines(value: str) -> list[str]:
    """Turn an ADO HTML field into the lines a scenario splitter can read."""
    text = html.unescape(value or "")
    text = text.replace("\xa0", " ")
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(div|p|li|tr|h[1-6])>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    lines = []
    for raw_line in text.splitlines():
        line = re.sub(r"[ \t]+", " ", raw_line).strip()
        if line:
            lines.append(line)
    return lines


def _criteria_from_text(value: str) -> list[dict]:
    """Split Scenario / Expected text. An AC-01 label in the title is kept as ac_id."""
    criteria = []
    title = None
    body_lines: list[str] = []

    def append_criterion() -> None:
        if not title:
            return
        body = " ".join(line for line in body_lines if line).strip()
        criteria.append(_criterion(title, body, len(criteria) + 1))

    for line in _plain_lines(value):
        if line.startswith("Scenario:"):
            append_criterion()
            title = line.removeprefix("Scenario:").strip()
            body_lines = []
        elif title and line.startswith(("Expected:", "Expected result:")):
            body_lines.append(line.partition(":")[2].strip())
        elif title:
            body_lines.append(line)

    append_criterion()
    return criteria


def _criterion(title: str, body: str, index: int) -> dict:
    match = _AC_LABEL.match(title)
    if match:
        ac_id = match.group(1).upper()
        name = match.group(2).strip() or title
    else:
        ac_id = f"AC-{index}"
        name = title
    return {
        "ac_id": ac_id,
        "text": f"{name}. {body}" if body else name,
        "testable": bool(body),
        "flags": [],
    }


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
    if state.get("live"):
        result = analyze_live(state["record"])
        return {
            "score": result["score"],
            "narrative": result["narrative"],
            "token_count": result["token_count"],
            "narrative_latency_ms": result["narrative_latency_ms"],
        }
    return {"score": score_record(state["record"])}


def write_narrative(state: GraphState) -> dict:
    """Offline, one narrative call over the score. Live, the analysis call already ran."""
    if state.get("live"):
        narrative = state.get("narrative")
        if not isinstance(narrative, dict):
            raise NarrativeError("live analysis did not return a narrative")
        return {
            "narrative": narrative,
            "token_count": state.get("token_count", 0),
            "narrative_latency_ms": state.get("narrative_latency_ms", 0),
        }
    result = request_narrative(state["score"])
    return {
        "narrative": result["narrative"],
        "token_count": result["token_count"],
        "narrative_latency_ms": result["narrative_latency_ms"],
    }


def render_pdf(state: GraphState) -> dict:
    """Write both reports from the same score, narrative, and fixture record."""
    if not state.get("live"):
        _validate_narrative_counts(state["score"], state["narrative"])
    output_dir = artifacts_dir()
    template = _template_path()
    markdown_path = output_dir / f"{state['story_id']}.md"
    pdf_path = output_dir / f"{state['story_id']}.pdf"
    render_pdf_file(
        state["score"],
        template,
        pdf_path,
        narrative=state["narrative"],
        record=state.get("record"),
    )
    render_markdown(
        state["score"],
        state["narrative"],
        template,
        markdown_path,
        record=state.get("record"),
    )
    return {"markdown_path": str(markdown_path), "pdf_path": str(pdf_path)}


def _validate_narrative_counts(score: dict, narrative: dict) -> None:
    """Reject explicit narrative counts or coverage claims that conflict with the score."""
    enforce_narrative_rules(score, narrative)


def artifacts_dir() -> Path:
    configured = os.environ.get("STORY_GUARD_ARTIFACTS_DIR")
    return Path(configured) if configured else _repo_root() / "artifacts"


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
