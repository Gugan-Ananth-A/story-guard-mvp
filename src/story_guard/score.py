"""Deterministic health score for one story record. No model call."""

import re

SR_1 = "SR-1"
SR_2 = "SR-2"
SR_3 = "SR-3"
RULE_IDS = [SR_1, SR_2, SR_3]

_TYPE_KEYS = ("happy", "negative", "edge", "security", "adhoc")
_CLOSED_STATUSES = {"resolved", "closed", "rejected", "unable to reproduce"}
_PRIORITY = re.compile(r"\b(P[1-4])\b", re.IGNORECASE)
_HEALTH = {
    "P1": ("Critical", "At Risk"),
    "P2": ("High", "At Risk"),
    "P3": ("Medium", "Healthy"),
    "P4": ("Low", "Healthy"),
}
_DEPTH = (
    ("positive", "Positive scenarios are covered", "No Positive scenarios Covered"),
    ("negative", "Negative scenarios are covered", "No Negative scenarios Covered"),
    ("adhoc", "Adhoc scenarios are covered", "No Adhoc scenarios Covered"),
)


def score_health(story_record: dict) -> dict:
    """Apply SR-1, SR-2, and SR-3. Counts come from the record."""
    if not SR_1 or not SR_2 or not SR_3:
        raise RuntimeError("coverage rule id is empty")
    scenarios = list(story_record.get("scenarios") or [])
    tests = list(story_record.get("tests") or [])
    bugs = list(story_record.get("bugs") or [])
    rows, mapped_count = _scenarios(scenarios, tests)
    health, health_band = _health(bugs)
    note = story_record.get("note")
    if note is None:
        note = ""
    return {
        "story_id": str(story_record.get("id", "")),
        "title": story_record.get("title", ""),
        "source": story_record.get("source", "fixture"),
        "ac_field": _ac_field(story_record),
        "scenario_count": len(scenarios),
        "scenarios": rows,
        "test_count": len(tests),
        "mapped_count": mapped_count,
        "bug_count": len(bugs),
        "open_bug_count": sum(1 for bug in bugs if _is_open(bug)),
        "escaped_bug_count": sum(1 for bug in bugs if _is_escaped(bug)),
        "open_bugs_by_priority": _open_bugs_by_priority(bugs),
        "adequate_count": sum(1 for row in rows if row["row_status"] == "adequate"),
        "partial_count": sum(1 for row in rows if row["row_status"] == "partial"),
        "none_count": sum(1 for row in rows if row["row_status"] == "none"),
        "rag": _coverage_rag(rows),
        "bugs": bugs,
        "coverage_by_type": _coverage_by_type(tests),
        "health": health,
        "health_band": health_band,
        "rule_ids": list(RULE_IDS),
        "note": note,
    }


def _coverage_rag(rows: list[dict]) -> str:
    """Summarize explicit coverage independently of SR-2 story health."""
    if not rows:
        return "Unavailable"
    if all(row["row_status"] == "none" for row in rows):
        return "Red"
    if any(row["row_status"] != "adequate" for row in rows):
        return "Amber"
    return "Green"


def _ac_field(story_record: dict) -> str:
    raw = story_record.get("acceptance_criteria_raw") or ""
    items = story_record.get("acceptance_criteria") or []
    if str(raw).strip() == "" and len(items) == 0:
        return "empty"
    return "present"


def _scenarios(scenarios: list, tests: list) -> tuple[list[dict], int]:
    """SR-1 links tests to scenarios. SR-3 sets depth, gap, and row status from those links."""
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
    rows = [_row(ac_id, mapped[ac_id], tests) for ac_id in ac_ids]
    mapped_count = sum(len(row["mapped_test_ids"]) for row in rows)
    return rows, mapped_count


def _row(ac_id: str, test_ids: list[str], tests: list) -> dict:
    if not test_ids:
        return {
            "ac_id": ac_id,
            "covered": False,
            "mapped_test_ids": test_ids,
            "depth": "None",
            "gap": "No coverage",
            "row_status": "none",
        }
    present = set()
    for test_id in test_ids:
        for test in tests:
            if str(test.get("id", "")) == test_id:
                bucket = _type_bucket(test.get("type"))
                if bucket:
                    present.add(bucket)
    missing = [gap for key, _line, gap in _DEPTH if key not in present]
    if not missing:
        gap = "Adequate"
        row_status = "adequate"
    else:
        gap = "\n".join(missing)
        row_status = "partial"
    depth = "\n".join(line for key, line, _gap in _DEPTH if key in present)
    return {
        "ac_id": ac_id,
        "covered": True,
        "mapped_test_ids": test_ids,
        "depth": depth,
        "gap": gap,
        "row_status": row_status,
    }


def _type_bucket(kind: object) -> str:
    text = str(kind or "").strip().lower()
    if text in ("happy", "positive"):
        return "positive"
    if text == "negative":
        return "negative"
    if text == "adhoc":
        return "adhoc"
    return ""


def _health(bugs: list) -> tuple[str, str]:
    """SR-2. The highest open P1–P4 wins. Coverage does not change the result."""
    best = ""
    unset_open = False
    for bug in bugs:
        if not _is_open(bug):
            continue
        priority = _priority(bug)
        if not priority:
            unset_open = True
            continue
        if best == "" or priority < best:
            best = priority
    if best:
        return _HEALTH[best]
    if unset_open:
        return ("Open bugs, priority unset", "Open bugs, priority unset")
    return ("No open bugs", "No open bugs")


def _open_bugs_by_priority(bugs: list) -> dict[str, int]:
    counts = {"P1": 0, "P2": 0, "P3": 0, "P4": 0}
    for bug in bugs:
        if not _is_open(bug):
            continue
        priority = _priority(bug)
        if priority:
            counts[priority] += 1
    return counts


def _is_open(bug: dict) -> bool:
    status = str(bug.get("status") or "").strip().lower()
    return status not in _CLOSED_STATUSES


def _priority(bug: dict) -> str:
    match = _PRIORITY.search(str(bug.get("priority") or ""))
    if match is None:
        return ""
    return match.group(1).upper()


def _is_escaped(bug: dict) -> bool:
    found = str(bug.get("found_in") or "").lower()
    return "uat" in found or "prod" in found


def _coverage_by_type(tests: list) -> dict[str, int]:
    counts = {key: 0 for key in _TYPE_KEYS}
    counts["unset"] = 0
    for test in tests:
        kind = str(test.get("type") or "")
        if kind == "positive":
            kind = "happy"
        if kind in _TYPE_KEYS:
            counts[kind] += 1
        else:
            counts["unset"] += 1
    return counts
