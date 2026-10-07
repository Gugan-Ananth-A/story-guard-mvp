"""Deterministic health score for one story record. No model call."""

SR_1 = "SR-1"
SR_2 = "SR-2"

_TYPE_KEYS = ("happy", "negative", "edge", "security", "adhoc")


def score_health(story_record: dict) -> dict:
    """Apply SR-1 for coverage and SR-2 for the RAG. Counts come from the record."""
    scenarios = list(story_record.get("scenarios") or [])
    tests = list(story_record.get("tests") or [])
    bugs = list(story_record.get("bugs") or [])
    rows, mapped_count = _scenarios(scenarios, tests)
    scenario_count = len(scenarios)
    rag, rule_id = _rag(scenario_count, mapped_count)
    note = story_record.get("note")
    if note is None:
        note = ""
    return {
        "story_id": str(story_record.get("id", "")),
        "title": story_record.get("title", ""),
        "source": "fixture",
        "ac_field": _ac_field(story_record),
        "scenario_count": scenario_count,
        "scenarios": rows,
        "test_count": len(tests),
        "mapped_count": mapped_count,
        "bug_count": len(bugs),
        "bugs": bugs,
        "coverage_by_type": _coverage_by_type(tests),
        "rag": rag,
        "rule_id": rule_id,
        "note": note,
    }


def _ac_field(story_record: dict) -> str:
    raw = story_record.get("acceptance_criteria_raw") or ""
    items = story_record.get("acceptance_criteria") or []
    if str(raw).strip() == "" and len(items) == 0:
        return "empty"
    return "present"


def _scenarios(scenarios: list, tests: list) -> tuple[list[dict], int]:
    """Apply SR-1. A scenario is covered only when a test lists its ac_id. An empty list adds nothing."""
    if not SR_1:
        raise RuntimeError("coverage rule id is empty")
    ac_ids = [item["ac_id"] for item in scenarios]
    mapped: dict[str, list[str]] = {ac_id: [] for ac_id in ac_ids}
    for test in tests:
        links = test.get("mapped_ac_ids")
        if not isinstance(links, list):
            continue
        test_id = str(test.get("id", ""))
        seen: set[str] = set()
        for ac_id in links:
            if ac_id in mapped and ac_id not in seen:
                mapped[ac_id].append(test_id)
                seen.add(ac_id)
    rows = [
        {
            "ac_id": ac_id,
            "covered": bool(mapped[ac_id]),
            "mapped_test_ids": mapped[ac_id],
        }
        for ac_id in ac_ids
    ]
    mapped_count = sum(len(row["mapped_test_ids"]) for row in rows)
    return rows, mapped_count


def _rag(scenario_count: int, mapped_count: int) -> tuple[str, str]:
    """SR-2 is the only RAG assignment. When it does not apply, the RAG stays unset."""
    if scenario_count >= 1 and mapped_count == 0:
        return "Red", SR_2
    return "", ""


def _coverage_by_type(tests: list) -> dict[str, int]:
    counts = {key: 0 for key in _TYPE_KEYS}
    counts["unset"] = 0
    for test in tests:
        kind = test.get("type") or ""
        if kind in _TYPE_KEYS:
            counts[kind] += 1
        else:
            counts["unset"] += 1
    return counts
