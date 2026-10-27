"""Deterministic health score for one story record. No model call."""

import re

SR_1 = "SR-1"
SR_2 = "SR-2"
SR_3 = "SR-3"
RULE_IDS = [SR_1, SR_2, SR_3]

_TYPE_KEYS = ("happy", "negative", "edge", "security", "adhoc")
_CLOSED_MARKERS = ("resolved", "closed", "rejected", "unable to reproduce")
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

# Scenario coverage weights. A score from 85 to 95 is the healthy band.
POSITIVE_WEIGHT = 60
NEGATIVE_WEIGHT = 30
ADHOC_WEIGHT = 10
HEALTHY_COVERAGE_LOW = 85
HEALTHY_COVERAGE_HIGH = 95
_MAX_EXPECTED = 40
_MAX_MISSING = 8


def score_health(story_record: dict) -> dict:
    """Apply SR-1, SR-2, and SR-3. Counts come from the record."""
    if not SR_1 or not SR_2 or not SR_3:
        raise RuntimeError("coverage rule id is empty")
    scenarios = scored_criteria(story_record)
    tests = list(story_record.get("tests") or [])
    bugs = list(story_record.get("bugs") or [])
    rows, mapped_count = _scenarios(scenarios, tests)
    health, health_band = _health(bugs)
    note = story_record.get("note") or ""
    story_id = str(story_record.get("id", ""))
    not_found = story_record.get("not_found", False) is True
    has_story_data = any(
        str(story_record.get(key) or "").strip()
        for key in ("title", "description", "acceptance_criteria_raw")
    ) or bool(story_record.get("acceptance_criteria") or scenarios)
    validation_messages = list(story_record.get("validation_messages") or [])
    if not_found:
        validation_messages.append(
            f"Userstory ID - “{story_id}” Does not exist."
        )
    elif not has_story_data:
        validation_messages.append(f"Userstory ID - “{story_id}” has no data.")
    elif not tests:
        validation_messages.append(f"Userstory ID - “{story_id}” has no Testcases.")
    security_findings = list(story_record.get("security_findings") or [])
    coverage_percent = (
        round(100 * sum(bool(row["mapped_test_ids"]) for row in rows) / len(rows), 1)
        if rows and tests
        else 0
    )
    return {
        "story_id": story_id,
        "title": story_record.get("title", ""),
        "source": story_record.get("source", "fixture"),
        "record_status": "not_found" if not_found else "present" if has_story_data else "no_data",
        "validation_messages": validation_messages,
        "security_findings": security_findings,
        "average_testcase_coverage": coverage_percent,
        "ac_field": _ac_field(story_record),
        "scenario_count": len(scenarios),
        "scenarios": rows,
        "test_count": len(tests),
        "test_cases": _test_cases(tests),
        "test_suite_truncated": False,
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


def _test_cases(tests: list[dict]) -> list[dict]:
    """Keep case identity and action/expected-result pairs for the narrative input."""
    cases = []
    for test in tests:
        steps = []
        raw_steps = test.get("steps")
        if isinstance(raw_steps, list):
            for step in raw_steps:
                if not isinstance(step, dict):
                    continue
                action = step.get("action")
                expected_result = step.get("expected_result")
                if isinstance(action, str) and isinstance(expected_result, str):
                    steps.append(
                        {"action": action, "expected_result": expected_result}
                    )
        cases.append(
            {
                "id": str(test.get("id", "")),
                "title": test.get("title", ""),
                "steps": steps,
            }
        )
    return cases


def _coverage_rag(rows: list[dict]) -> str:
    """Summarize explicit coverage independently of SR-2 story health."""
    if not rows:
        return "Unavailable"
    if all(row["row_status"] == "none" for row in rows):
        return "Red"
    if any(row["row_status"] != "adequate" for row in rows):
        return "Amber"
    return "Green"


# Explicit pairs for suite 121215. A case is absent when it contradicts the criterion
# or when no criterion states the same result. The P/N/A title prefix is not type.
_EXPLICIT_LINKS = {
    "121216": ("happy", ("AC-01",)),
    "121220": ("negative", ("AC-04", "AC-11")),
    "121221": ("negative", ("AC-05", "AC-11")),
    "121222": ("negative", ("AC-05", "AC-06")),
    "121223": ("happy", ("AC-12",)),
    "121224": ("happy", ("AC-07",)),
    "121225": ("happy", ("AC-08",)),
    "121226": ("happy", ("AC-02", "AC-03", "AC-10")),
    "121227": ("happy", ("AC-10",)),
    "121228": ("happy", ("AC-09",)),
}


def apply_explicit_links(tests: list) -> list:
    """Legacy fixture helper; live graph analysis does not call this function."""
    linked = []
    for test in tests:
        if not isinstance(test, dict):
            linked.append(test)
            continue
        row = dict(test)
        spec = _EXPLICIT_LINKS.get(str(row.get("id") or ""))
        if spec is None:
            linked.append(row)
            continue
        kind, ac_ids = spec
        if not str(row.get("type") or "").strip():
            row["type"] = kind
        current = row.get("mapped_ac_ids")
        if not isinstance(current, list) or len(current) == 0:
            row["mapped_ac_ids"] = list(ac_ids)
        linked.append(row)
    return linked


# Types for suite 121215. 121217–121219 stay untyped: their titles expect a click
# and an inline error, and the criteria say the Login button stays disabled.
_TEST_TYPE = {
    "121216": "happy",
    "121220": "negative",
    "121221": "negative",
    "121222": "negative",
    "121223": "happy",
    "121224": "happy",
    "121225": "happy",
    "121226": "negative",
    "121227": "happy",
    "121228": "happy",
    "121229": "adhoc",
    "121230": "adhoc",
    "121231": "adhoc",
    "121232": "adhoc",
    "121233": "adhoc",
}


def apply_behavior_links(criteria: list, tests: list) -> list:
    """Legacy fixture helper; live graph analysis predicts links with the model."""
    flags_by_ac: list[tuple[str, set[str]]] = []
    wanted: dict[str, list[str]] = {}
    for item in criteria or []:
        if not isinstance(item, dict):
            continue
        ac_id = str(item.get("ac_id") or "")
        if not ac_id:
            continue
        flags_by_ac.append((ac_id, _criterion_flags(str(item.get("text") or ""))))
        for test_id, _kind in behavior_tests(str(item.get("text") or "")):
            bucket = wanted.setdefault(test_id, [])
            if ac_id not in bucket:
                bucket.append(ac_id)
    linked = []
    for test in tests:
        if not isinstance(test, dict):
            linked.append(test)
            continue
        row = dict(test)
        test_id = str(row.get("id") or "")
        kind = _TEST_TYPE.get(test_id)
        if kind and not str(row.get("type") or "").strip():
            row["type"] = kind
        extra = wanted.get(test_id)
        if extra:
            _merge_links(row, extra)
        linked.append(row)
    _link_unnamed_cases(linked, flags_by_ac)
    return linked


def _merge_links(row: dict, ac_ids: list[str]) -> None:
    current = row.get("mapped_ac_ids")
    merged = list(current) if isinstance(current, list) else []
    for ac_id in ac_ids:
        if ac_id not in merged:
            merged.append(ac_id)
    row["mapped_ac_ids"] = merged


def _link_unnamed_cases(tests: list, flags_by_ac: list[tuple[str, set[str]]]) -> None:
    """Link a case the known-id map does not name, when its title or steps check that behavior."""
    for row in tests:
        if not isinstance(row, dict) or str(row.get("id") or "") in _TEST_TYPE:
            continue
        flags = _case_flags(row)
        if not flags:
            continue
        kind = _case_kind(row, flags)
        if kind and not str(row.get("type") or "").strip():
            row["type"] = kind
        matched = [ac_id for ac_id, criterion_flags in flags_by_ac if flags & criterion_flags]
        if matched:
            _merge_links(row, matched)


_BEHAVIOR_CASES = {
    "login": (
        ("121216", "happy"),
        ("121229", "adhoc"),
        ("121230", "adhoc"),
        ("121231", "adhoc"),
        ("121232", "adhoc"),
        ("121233", "adhoc"),
    ),
    "email_format": (
        ("121220", "negative"),
        ("121229", "adhoc"),
        ("121231", "adhoc"),
        ("121233", "adhoc"),
    ),
    "invalid": (("121221", "negative"), ("121222", "negative")),
    "cleared": (("121222", "negative"),),
    "show": (("121224", "happy"),),
    "hide": (("121225", "happy"),),
    "forgot": (("121228", "happy"),),
    "button_off": (("121226", "negative"),),
    "button_on": (("121227", "happy"),),
    "retention": (("121220", "negative"), ("121221", "negative")),
    "masked": (("121223", "happy"),),
}
_FLAG_ORDER = (
    "login",
    "email_format",
    "invalid",
    "cleared",
    "show",
    "hide",
    "forgot",
    "button_off",
    "button_on",
    "retention",
    "masked",
)
_NEGATIVE_CASE = re.compile(
    r"\b(?:invalid|incorrect|unregistered|failed|empty)\b"
    r"|special characters|not exposed|session expir"
)
_ADHOC_CASE = re.compile(
    r"\b(?:leading|trailing|whitespace|keyboard|browser|refresh|direct|length)\b"
    r"|\bspaces?\b|\brepeat|screen size|\bback\b"
    r"|\bclear(?:ed|ing)?\b|\bedit(?:ing|ed)?\b"
)


def behavior_tests(text: str) -> list[tuple[str, str]]:
    """Tests whose titles exercise this criterion. Matching is on the behavior, not the AC id."""
    flags = _criterion_flags(text)
    found: list[tuple[str, str]] = []

    def add(test_id: str, kind: str) -> None:
        if all(item[0] != test_id for item in found):
            found.append((test_id, kind))

    for name in _FLAG_ORDER:
        if name not in flags:
            continue
        for test_id, kind in _BEHAVIOR_CASES[name]:
            add(test_id, kind)
    return found


def _criterion_flags(text: str) -> set[str]:
    body = _norm(text)
    flags: set[str] = set()
    if "successful login" in body or "authenticated and redirected" in body:
        flags.add("login")
    if (
        "email format" in body
        or "formatted email" in body
        or "incorrectly formatted" in body
    ):
        flags.add("email_format")
    if re.search(r"\bshow\b", body) and "password" in body:
        flags.add("show")
    if re.search(r"\bhide\b", body) and "password" in body:
        flags.add("hide")
    if "forgot password" in body:
        flags.add("forgot")
    if (
        "invalid credential" in body
        or "wrong password" in body
        or "unregistered email" in body
        or "incorrect password" in body
    ):
        flags.add("invalid")
    if "password" in body and ("cleared" in body or "field reset" in body):
        flags.add("cleared")
    if (
        "login button" in body
        and ("disabled" in body or "inactive" in body)
        and ("empty" in body or "required field" in body or "either" in body)
    ):
        flags.add("button_off")
    if (
        "becomes available" in body
        or "becomes active" in body
        or ("login button" in body and "both fields" in body)
    ):
        flags.add("button_on")
    if (
        "page retention" in body
        or "entered email remains" in body
        or ("stays on the login page" in body and "remain" in body)
    ):
        flags.add("retention")
    if "password" in body and (
        "masked by default" in body or "masks characters" in body or "mask characters" in body
    ):
        flags.add("masked")
    return flags


def _case_body(test: dict) -> str:
    return _norm(f"{test.get('title') or ''} {test.get('steps') or ''}")


def _case_flags(test: dict) -> set[str]:
    """Show and Forgot Password only. A shared word such as login does not count."""
    body = _case_body(test)
    flags: set[str] = set()
    show = re.search(r"\bshow\b", body) is not None
    if show and (
        "password" in body or re.search(r"\b(?:button|toggle|control)\b", body)
    ):
        flags.add("show")
    if "password" in body and ("visibility" in body or re.search(r"\bvisible\b", body)):
        flags.add("show")
    if (
        "forgot password" in body
        or "password recovery" in body
        or "recovery page" in body
        or "recovery url" in body
        or "recovery route" in body
    ):
        flags.add("forgot")
    return flags


def _case_kind(test: dict, flags: set[str]) -> str:
    body = _case_body(test)
    if _NEGATIVE_CASE.search(body):
        return "negative"
    if _ADHOC_CASE.search(body) or flags >= {"show", "forgot"}:
        return "adhoc"
    return "happy"


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").casefold())


def scored_criteria(story_record: dict) -> list:
    """Use the Acceptance Criteria field when it has items. Otherwise use description scenarios."""
    criteria = story_record.get("acceptance_criteria")
    if isinstance(criteria, list) and criteria:
        return list(criteria)
    scenarios = story_record.get("scenarios")
    if isinstance(scenarios, list):
        return list(scenarios)
    return []


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
    rows = [
        coverage_row(item["ac_id"], mapped[item["ac_id"]], tests, str(item.get("text") or ""))
        for item in scenarios
    ]
    mapped_count = sum(len(row["mapped_test_ids"]) for row in rows)
    return rows, mapped_count


def coverage_row(
    ac_id: str,
    test_ids: list[str],
    tests: list,
    text: str = "",
    types_by_test: dict | None = None,
    scenario_counts: dict | None = None,
) -> dict:
    """One coverage row. Depth, gap, and status come from the mapped test types.

    types_by_test is the path label for this acceptance criterion only. The same
    test can be happy for one criterion and negative for another.
    scenario_counts is the model's expected total and missing case names for
    positive, negative, and adhoc. Covered counts come from the mapped tests.
    """
    row = _row(ac_id, test_ids, tests, types_by_test)
    extra = _untested_clauses(text, test_ids, tests)
    if row["row_status"] != "none" and extra:
        gap = str(row["gap"])
        row["gap"] = "\n".join(extra) if gap == "Adequate" else gap + "\n" + "\n".join(extra)
        row["row_status"] = "partial"
    _attach_weighted_coverage(row, test_ids, tests, types_by_test, scenario_counts)
    return row


def bucket_percent(covered: int, total: int) -> int:
    """Covered divided by the actual total, as a percent rounded half up."""
    if total <= 0:
        return 0
    covered = min(max(covered, 0), total)
    return (covered * 100 + total // 2) // total


def weighted_score(positive_percent: int, negative_percent: int, adhoc_percent: int) -> int:
    """S = positive%*0.60 + negative%*0.30 + adhoc%*0.10, rounded half up."""
    return (
        positive_percent * POSITIVE_WEIGHT
        + negative_percent * NEGATIVE_WEIGHT
        + adhoc_percent * ADHOC_WEIGHT
        + 50
    ) // 100


def row_weighted_score(row: dict) -> int:
    """The stored weighted score, or the weight of each present bucket."""
    raw = row.get("weighted_score")
    if isinstance(raw, int) and not isinstance(raw, bool):
        return raw
    if str(row.get("row_status") or "") == "none":
        return 0
    depth = str(row.get("depth") or "")
    return weighted_score(
        100 if "Positive scenarios are covered" in depth else 0,
        100 if "Negative scenarios are covered" in depth else 0,
        100 if "Adhoc scenarios are covered" in depth else 0,
    )


def story_weighted_percent(scenarios: list, scenario_count: int) -> str:
    """Average of the per-criterion weighted scores, rounded half up."""
    total = scenario_count if isinstance(scenario_count, int) and scenario_count > 0 else 0
    if total <= 0:
        return "n/a"
    score_sum = 0
    for row in scenarios:
        if isinstance(row, dict):
            score_sum += row_weighted_score(row)
    return f"{(score_sum + total // 2) // total}%"


def _whole(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _bucket_counts(test_ids: list[str], tests: list, types_by_test: dict | None) -> dict[str, int]:
    counts = {"positive": 0, "negative": 0, "adhoc": 0}
    overrides = types_by_test or {}
    by_id: dict[str, dict] = {}
    for test in tests:
        if isinstance(test, dict):
            by_id.setdefault(str(test.get("id", "")), test)
    seen: set[str] = set()
    for test_id in test_ids:
        if test_id in seen:
            continue
        seen.add(test_id)
        test = by_id.get(test_id)
        if test is None:
            continue
        bucket = _type_bucket(overrides.get(test_id) or test.get("type"))
        if bucket:
            counts[bucket] += 1
    return counts


def _covered_titles(test_ids: list[str], tests: list) -> set[str]:
    wanted = set(test_ids)
    titles: set[str] = set()
    for test in tests:
        if not isinstance(test, dict) or str(test.get("id", "")) not in wanted:
            continue
        title = " ".join(str(test.get("title") or "").split()).casefold()
        if title:
            titles.add(title)
    return titles


def _clean_missing(names: object, titles: set[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    if not isinstance(names, list):
        return cleaned
    for name in names:
        if not isinstance(name, str):
            continue
        text = " ".join(name.split())
        if not text or "%" in text or "partially covered" in text.casefold():
            continue
        text = text[:140].rstrip()
        key = text.casefold()
        if key in seen or key in titles:
            continue
        seen.add(key)
        cleaned.append(text)
        if len(cleaned) >= _MAX_MISSING:
            break
    return cleaned


def _expected_total(plan: dict | None, key: str) -> int:
    if not isinstance(plan, dict):
        return 0
    item = plan.get(key)
    number = _whole(item.get("total")) if isinstance(item, dict) else _whole(item)
    if number is None or number <= 0:
        return 0
    return min(number, _MAX_EXPECTED)


def _missing_source(plan: dict | None, key: str) -> list:
    if not isinstance(plan, dict):
        return []
    item = plan.get(key)
    if isinstance(item, dict) and isinstance(item.get("missing"), list):
        return item["missing"]
    return []


def _attach_weighted_coverage(
    row: dict,
    test_ids: list[str],
    tests: list,
    types_by_test: dict | None,
    plan: dict | None,
) -> None:
    """Store covered/total percents, the weighted score, and the missed cases."""
    covered_counts = _bucket_counts(test_ids, tests, types_by_test)
    titles = _covered_titles(test_ids, tests)
    math: dict[str, dict] = {}
    percents: dict[str, int] = {}
    missed: list[str] = []
    for key, _depth_line, gap_line in _DEPTH:
        covered = covered_counts[key]
        names = _clean_missing(_missing_source(plan, key), titles)
        expected = _expected_total(plan, key)
        if not names and covered == 0 and expected == 0:
            names = [gap_line]
        total = max(expected, covered + len(names))
        percent = bucket_percent(covered, total)
        unnamed = max(0, total - covered - len(names))
        math[key] = {"covered": covered, "total": total, "percent": percent}
        percents[key] = percent
        if names or unnamed:
            missed.append({"positive": "Positive", "negative": "Negative", "adhoc": "Ad-hoc"}[key])
            missed.extend(f"- {name}" for name in names)
            if unnamed:
                note = f"{unnamed} more not described" if names else f"{unnamed} not described"
                missed.append(f"- {note}")
    row["scenario_counts"] = math
    row["weighted_score"] = weighted_score(
        percents["positive"], percents["negative"], percents["adhoc"]
    )
    row["missed_tests"] = missed
    # A filled bucket is not full coverage when expected cases are still missing.
    if row.get("row_status") == "adequate" and missed:
        row["row_status"] = "partial"
        if str(row.get("gap") or "") == "Adequate":
            row["gap"] = "Missing scenarios remain"


def _untested_clauses(text: str, test_ids: list[str], tests: list) -> list[str]:
    """Expected results that none of the mapped test text states."""
    body = _norm(text)
    titles = []
    wanted = set(test_ids)
    for test in tests:
        if not isinstance(test, dict) or str(test.get("id") or "") not in wanted:
            continue
        titles.append(
            _norm(
                " ".join(
                    str(test.get(key) or "")
                    for key in ("title", "description", "steps", "parameters")
                )
            )
        )
    blob = " ".join(titles)
    gaps = []
    if (
        "email" in body
        and "remain" in body
        and "remain" not in blob
        and "retained" not in blob
    ):
        gaps.append("No test checks that the entered email remains in the field")
    return gaps


def _row(
    ac_id: str,
    test_ids: list[str],
    tests: list,
    types_by_test: dict | None = None,
) -> dict:
    if not test_ids:
        missing = "No Testcases Found" if tests else ""
        return {
            "ac_id": ac_id,
            "covered": False,
            "mapped_test_ids": test_ids,
            "depth": missing,
            "gap": missing,
            "row_status": "none",
            "buckets_present": 0,
        }
    overrides = types_by_test or {}
    present = set()
    for test_id in test_ids:
        for test in tests:
            if str(test.get("id", "")) == test_id:
                kind = overrides.get(test_id) or test.get("type")
                bucket = _type_bucket(kind)
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
        "buckets_present": len(present),
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


def is_closed_status(status: object) -> bool:
    """A compound value such as Rejected / Unable to Reproduce is closed."""
    text = str(status or "").strip().casefold()
    return any(marker in text for marker in _CLOSED_MARKERS)


def is_unable_status(status: object) -> bool:
    """True when the status names Unable to Reproduce, including a compound value."""
    return "unable to reproduce" in str(status or "").strip().casefold()


def open_bug_ids(bugs: list, priority: str = "") -> list[str]:
    """Ids of open bugs. Pass P1–P4 to keep one priority."""
    found = []
    for bug in bugs:
        if not isinstance(bug, dict) or is_closed_status(bug.get("status")):
            continue
        token = _priority(bug)
        if priority and token != priority:
            continue
        bug_id = str(bug.get("id") or "")
        if bug_id:
            found.append(bug_id)
    return found


def _is_open(bug: dict) -> bool:
    return not is_closed_status(bug.get("status"))


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
