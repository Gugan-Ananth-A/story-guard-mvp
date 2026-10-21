"""Code-node graph. score stops after score_health. generate continues through the report."""

import json
import os
import re
from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from story_guard.narrative import NarrativeError, write_narrative as request_narrative
from story_guard.render import (
    RenderError,
    render_markdown,
    render_pdf as render_pdf_file,
    validate_template,
)
from story_guard.score import score_health as score_record
from story_guard.security import review_and_redact
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
    live_record: dict
    record: dict
    score: dict
    narrative: dict
    markdown_path: str
    pdf_path: str
    token_count: int
    narrative_latency_ms: int


class GateError(Exception):
    """The story id is blank, not numeric, or invalid for the selected source."""


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
    if live and int(story_id) <= 0:
        raise GateError("live story id must be a positive integer")
    validate_template(_template_path())
    return {"story_id": story_id, "live": live}


def fetch(state: GraphState) -> dict:
    story_id = state.get("story_id")
    if not isinstance(story_id, str) or story_id.strip() == "":
        raise ContractError("story id is missing")

    if state.get("live", False):
        record = state.get("live_record")
        if not isinstance(record, dict):
            record = load_live_story(story_id)
        sanitized_record, findings = review_and_redact(record)
        sanitized_record["security_findings"] = findings
        return {"record": sanitized_record}

    if story_id != _ACCEPTED_STORY_ID:
        record = _empty_story_record(story_id, source="fixture", not_found=True)
        sanitized_record, findings = review_and_redact(record)
        sanitized_record["security_findings"] = findings
        return {"record": sanitized_record}

    path = _repo_root() / "fixtures" / "FIX-121213.json"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ContractError("fixture FIX-121213.json is missing") from exc
    try:
        record = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ContractError("fixture FIX-121213.json is not valid JSON") from exc

    try:
        adapter_rows = fetch_tests(story_id)
    except DummyTestAdapterError as exc:
        raise ContractError(str(exc)) from exc
    record["tests"] = _tests_from_adapter(record.get("tests"), adapter_rows)
    sanitized_record, findings = review_and_redact(record)
    sanitized_record["security_findings"] = findings
    return {"record": sanitized_record}


def _empty_story_record(story_id: str, *, source: str, not_found: bool) -> dict:
    return {
        "id": story_id,
        "title": "",
        "type": "User Story",
        "state": "",
        "description": "",
        "area": "",
        "iteration": "",
        "acceptance_criteria_raw": "",
        "acceptance_criteria": [],
        "scenarios": [],
        "tests": [],
        "bugs": [],
        "note": "",
        "source": source,
        "not_found": not_found,
    }


def load_live_story(
    story_id: str,
    client=None,
    story_bundle: dict | None = None,
    plan_memberships: dict[str, list[int]] | None = None,
) -> dict:
    """Build one live graph record from a story and its explicit plan links."""
    from story_guard.ado_client import ADOClient, ADOResponseError

    ado_client = client or ADOClient.from_env()
    if story_bundle is None:
        results = ado_client.fetch_many_stories([int(story_id)])
        story_bundle = results[0]
    if not isinstance(story_bundle, dict):
        raise ADOResponseError(f"ADO story {story_id} response is invalid")
    if "error" in story_bundle:
        error = story_bundle.get("error")
        if isinstance(error, dict) and error.get("code") == "not_found":
            return _empty_story_record(
                story_id,
                source="Azure DevOps live data",
                not_found=True,
            )
        message = error.get("message") if isinstance(error, dict) else None
        raise ADOResponseError(message or f"Could not load ADO story {story_id}")

    story = story_bundle.get("story")
    test_cases = story_bundle.get("test_cases")
    if not isinstance(story, dict) or not isinstance(test_cases, list):
        raise ADOResponseError(f"ADO story {story_id} bundle is incomplete")
    if str(story.get("id")) != story_id:
        raise ADOResponseError(f"ADO returned the wrong story for ID {story_id}")

    if plan_memberships is None:
        case_ids = [int(case["id"]) for case in test_cases]
        plan_memberships = ado_client.test_case_plan_memberships(case_ids)
    return _story_record_from_ado(story_bundle, plan_memberships)


def _story_record_from_ado(
    bundle: dict, plan_memberships: dict[str, list[int]]
) -> dict:
    """Create a live story record using only its explicitly linked Test Cases."""
    story = bundle["story"]
    description = story.get("description") or ""
    linked_cases = bundle.get("test_cases") or []
    tests = []
    plan_ids = set()
    for case in linked_cases:
        case_id = str(case["id"])
        linked_plan_ids = plan_memberships.get(case_id, [])
        if not linked_plan_ids:
            continue
        tests.append(case)
        plan_ids.update(linked_plan_ids)

    if plan_ids:
        note = "Linked Test Plan IDs: " + ", ".join(
            str(plan_id) for plan_id in sorted(plan_ids)
        )
    else:
        note = (
            "No explicitly linked Test Plan was found; test coverage could not be assessed."
        )
    return {
        "id": story["id"],
        "title": story["title"],
        "type": story["type"],
        "state": story["state"],
        "description": description,
        "area": story.get("area") or "",
        "iteration": story.get("iteration") or "",
        "acceptance_criteria_raw": story.get("raw_ac_text") or "",
        "acceptance_criteria": story.get("acceptance_criteria") or [],
        "scenarios": _scenarios_from_description(description),
        "tests": tests,
        "bugs": bundle.get("bugs") or [],
        "note": note,
        "source": "Azure DevOps live data",
    }


def _scenarios_from_description(description: str) -> list[dict]:
    scenarios = []
    title = None
    expected_lines = []

    def append_scenario() -> None:
        if not title:
            return
        expected = " ".join(expected_lines)
        text = f"{title}. {expected}" if expected else title
        scenarios.append(
            {
                "ac_id": f"AC-{len(scenarios) + 1}",
                "text": text,
                "testable": bool(expected),
                "flags": [],
            }
        )

    for raw_line in description.splitlines():
        line = raw_line.strip()
        if line.startswith("Scenario:"):
            append_scenario()
            title = line.removeprefix("Scenario:").strip()
            expected_lines = []
        elif title and line.startswith(("Expected:", "Expected result:")):
            expected_lines.append(line.partition(":")[2].strip())

    append_scenario()
    return scenarios


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
    """Write narrative prose unless the story does not exist."""
    score = state["score"]
    if score.get("record_status") == "not_found":
        return {
            "narrative": {"headline": "", "sections": [], "actions": []},
            "token_count": 0,
            "narrative_latency_ms": 0,
        }
    result = request_narrative(score)
    return {
        "score": result["score"],
        "narrative": result["narrative"],
        "token_count": result["token_count"],
        "narrative_latency_ms": result["narrative_latency_ms"],
    }


def render_pdf(state: GraphState) -> dict:
    """Write both reports from the same score, narrative, and fixture record."""
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
    strings = [narrative.get("headline", "")]
    sections = narrative.get("sections", [])
    if isinstance(sections, list):
        for section in sections:
            if isinstance(section, str):
                strings.append(section)
            elif isinstance(section, dict):
                strings.extend((section.get("name", ""), section.get("prose", section.get("text", ""))))
    actions = narrative.get("actions", [])
    if isinstance(actions, list):
        strings.extend(action.get("text", action.get("action", "")) for action in actions if isinstance(action, dict))
    text = "\n".join(value for value in strings if isinstance(value, str))
    checks = (
        ("scenario_count", r"\b(\d+)\s+(?:scenarios?|acceptance criteria)\b"),
        ("test_count", r"\b(\d+)\s+(?:tests?|test cases?)\b"),
        ("mapped_count", r"\b(\d+)\s+mapped(?:\s+(?:ACs?|tests?))?\b"),
        ("bug_count", r"\b(\d+)\s+bugs?\b"),
    )
    for key, pattern in checks:
        expected = score.get(key)
        if isinstance(expected, int):
            for match in re.finditer(pattern, text, flags=re.IGNORECASE):
                if int(match.group(1)) != expected:
                    raise NarrativeError(
                        f"narrative {key} {match.group(1)} does not match score {expected}"
                    )
    mapped_count = score.get("mapped_count")
    if isinstance(mapped_count, int):
        for match in re.finditer(
            r"\bmapped(?:\s+ACs?|\s+tests?)?\s*(?:count)?\s*[:=]\s*(\d+)\b",
            text,
            flags=re.IGNORECASE,
        ):
            if int(match.group(1)) != mapped_count:
                raise NarrativeError(
                    f"narrative mapped_count {match.group(1)} does not match score {mapped_count}"
                )
    health = score.get("health")
    if isinstance(health, str) and re.search(r"\bstory health\s*(?:is|:)\s*([^.!\n]+)", text, re.IGNORECASE):
        match = re.search(r"\bstory health\s*(?:is|:)\s*([^.!\n]+)", text, re.IGNORECASE)
        assert match is not None
        if match.group(1).strip().casefold() != health.casefold():
            raise NarrativeError("narrative story health does not match the score")
    if score.get("mapped_count") == 0 and re.search(
        r"\b(?:AC[-\w]*|acceptance criteria)\s+(?:is|are)\s+covered\b",
        text,
        re.IGNORECASE,
    ):
        raise NarrativeError("narrative claims coverage absent from the score")
    rag = score.get("rag")
    if isinstance(rag, str):
        match = re.search(
            r"\b(?:RAG|coverage)\s*(?:is|:)\s*(Red|Amber|Green)\b",
            text,
            re.IGNORECASE,
        )
        if match and match.group(1).casefold() != rag.casefold():
            raise NarrativeError("narrative RAG does not match the score")


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
