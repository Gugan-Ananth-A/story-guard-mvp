"""Model-assisted live review of one story at a time.

The live path deliberately keeps the model's context small: one acceptance
criterion is compared with one bounded test-suite batch at a time. The batches
are combined in code, then the deterministic scorer calculates the final AC
status, coverage depth, and story health. Existing ``mapped_ac_ids`` values are
not used as a shortcut for live analysis.
"""

import json
import re
import time
from collections.abc import Callable

from story_guard.narrative import (
    ATTEMPTS,
    NarrativeError,
    _check_cap,
    _elapsed_ms,
    _load_response_json,
    _token_count,
    ollama_chat,
)
from story_guard.score import (
    coverage_row,
    is_closed_status,
    open_bug_ids,
    score_health,
    scored_criteria,
)

_PAIR_PREDICT = 2048
_PAIR_PREDICT_MIN = 512
_SUITE_BATCH_CHARS = 12000
_TEST_TEXT_CHARS = 1200
_CRITERION_TEXT_CHARS = 4000
_ANALYSIS_CHARS = 4000
_FINDING_CHARS = 400
_QUALITY_ISSUE_CHARS = 240
_ID_TOKEN = re.compile(r"\bAC-\d+\b|\b\d{5,}\b", re.IGNORECASE)
_PRIORITY = re.compile(r"\bP([1-4])\b", re.IGNORECASE)
_QUALITY_LEVELS = {"good", "needs_improvement", "poor"}
_COVERAGE_STATUSES = {"adequate", "partial", "none"}
_TEST_TYPES = {"happy", "negative", "edge", "security", "adhoc"}
_PROMPT = """You review one acceptance criterion against the test cases in one suite batch. Each request contains one acceptance criterion and one suite batch; the caller repeats this for every suite. The user message is the only source of facts.

Return one JSON object and nothing else. Do not use a Markdown fence. Do not call tools.
{
  "ac_id": "the id copied from the acceptance criterion",
  "mapped_test_ids": ["test ids copied from this suite"],
  "test_types": {"test id": "scenario type"},
  "coverage_status": "adequate",
  "quality": {
    "status": "good",
    "testable": true,
    "issues": ["short issue, or [] when clear"]
  },
  "finding": "one sentence on what the named tests check and what is still missing"
}

How to judge coverage. This call is one acceptance criterion and one suite batch.
- Read that criterion's text, including the expected result.
- A test may be listed only when its title checks the same behavior and the same expected result. Sharing a word such as "login" is not enough.
- The test type field is a hint. An empty type does not block a match; classify a matched test rather than treating the empty field as evidence of a match.
- For every mapped test whose type is empty, classify it in test_types from its title and steps. Do not change a non-empty source type.
- Existing source links are intentionally not supplied. Decide the mapping from the criterion and the test evidence in this message.
- When no test checks this criterion, mapped_test_ids is empty. The finding says that no listed test checks it.
- coverage_status is your assessment of this batch only. It must be adequate, partial, or none. Use adequate only when the named tests check the behavior and expected result; use partial when they check only part; use none when no test matches.
- Assess AC quality independently of test coverage. quality.status must be good, needs_improvement, or poor. Use good when the behavior and observable expected result are clear and pass/fail testable. Use needs_improvement for ambiguity or an incomplete expected result. Use poor when the criterion is not meaningfully testable. Keep issues short.
- Use the ac_id exactly as written. Do not invent a test id. Do not name a test id in the finding unless it is also in mapped_test_ids.
- Do not use a percent sign.
- Do not write the phrase "partially covered".
- Coverage does not change health. Do not set story health in this answer.
"""

Progress = Callable[[str], None]


def _notify(progress: Progress | None, message: str) -> None:
    """Send CLI progress without allowing display code to affect analysis."""
    if progress is None:
        return
    try:
        progress(message)
    except Exception:
        # Progress is best-effort. A broken output stream must not change the
        # model result or leave a partially generated report.
        return


def analyze_live(record: dict, progress: Progress | None = None) -> dict:
    """Review every criterion against every test suite, then combine the results."""
    if not isinstance(record, dict):
        raise NarrativeError("story record is not an object")
    criteria = _criteria_to_judge(record)
    suites = _test_suite_batches(record)
    _notify(
        progress,
        f"live review started: {len(criteria)} acceptance criteria across {len(suites)} suite batches",
    )
    reviews, findings, token_count, latency_ms = _judge_criteria(
        record, criteria, 0, progress, suites
    )
    result = result_from_judgment(
        record,
        _combined_judgment(record, reviews, findings),
        token_count=token_count,
        narrative_latency_ms=latency_ms,
    )
    _notify(progress, "live review complete: model links checked and score calculated")
    return result


def _judge_criteria(
    record: dict,
    criteria: list[dict],
    index: int,
    progress: Progress | None = None,
    suites: list[tuple[str, str, list[dict]]] | None = None,
) -> tuple[list[dict], list[str], int, int]:
    """Judge each criterion in sequence without growing the model context."""
    reviews: list[dict] = []
    findings: list[str] = []
    tokens = 0
    latency = 0
    suites = suites if suites is not None else _test_suite_batches(record)
    for criterion in criteria[index:]:
        review, criterion_findings, criterion_tokens, criterion_latency = _judge_suites(
            record, criterion, suites, progress
        )
        reviews.append(review)
        findings.extend(criterion_findings)
        tokens += criterion_tokens
        latency += criterion_latency
        _notify(
            progress,
            f"completed {criterion.get('ac_id', 'AC')}: {len(review.get('mapped_test_ids') or [])} predicted test links",
        )
    return reviews, findings, tokens, latency


def _judge_suites(
    record: dict,
    criterion: dict,
    suites: list[tuple[str, str, list[dict]]],
    progress: Progress | None = None,
) -> tuple[dict, list[str], int, int]:
    """Judge this criterion against every suite batch and merge the evidence."""
    ac_id = str(criterion.get("ac_id") or "")
    ids: list[str] = []
    findings: list[str] = []
    quality: dict | None = None
    test_types: dict[str, str] = {}
    tokens = 0
    latency = 0
    statuses: list[str] = []
    for batch_index, (suite_id, suite_name, tests) in enumerate(suites, 1):
        _notify(
            progress,
            f"reviewing {ac_id} against {suite_name} ({batch_index}/{len(suites)}, {len(tests)} tests)",
        )
        pair, call_tokens, call_latency = _judge_pair(
            record, criterion, suite_id, suite_name, tests, progress
        )
        for test_id in pair["mapped_test_ids"]:
            if test_id not in ids:
                ids.append(test_id)
        if pair.get("finding"):
            findings.append(str(pair["finding"]))
        for test_id, test_type in (pair.get("test_types") or {}).items():
            if test_id not in test_types:
                test_types[test_id] = test_type
        pair_quality = pair.get("quality")
        if isinstance(pair_quality, dict):
            quality = (
                pair_quality
                if quality is None
                else _merge_quality(quality, pair_quality)
            )
        status = str(pair.get("coverage_status") or "").strip().lower()
        if status in _COVERAGE_STATUSES:
            statuses.append(status)
        tokens += call_tokens
        latency += call_latency
    if not findings:
        findings = [_default_finding(ac_id, ids)]
    return (
        {
            "ac_id": ac_id,
            "mapped_test_ids": ids,
            "test_types": test_types,
            "coverage_status": _combined_status(ids, statuses),
            "quality": quality or _default_quality(criterion),
        },
        findings,
        tokens,
        latency,
    )


def _judge_pair(
    record: dict,
    criterion: dict,
    suite_id: str,
    suite_name: str,
    tests: list[dict],
    progress: Progress | None = None,
) -> tuple[dict, int, int]:
    """One model call. A rejected body is tried again until the attempt budget is spent."""
    ac_id = str(criterion.get("ac_id") or "")
    facts = _pair_facts(record, criterion, suite_id, suite_name, tests)
    budget = _PAIR_PREDICT
    last_error: NarrativeError | None = None
    correction: str | None = None
    latency_ms = 0
    for attempt in range(1, ATTEMPTS + 1):
        messages = [
            {"role": "system", "content": _PROMPT},
            {"role": "user", "content": facts},
        ]
        if correction:
            messages.append({"role": "user", "content": correction})
        started = time.perf_counter()
        try:
            response = ollama_chat(messages, num_predict=budget)
            _check_cap(response)
            body = _load_response_json(response, "analysis")
            pair = _require_pair(body, criterion, tests)
        except NarrativeError as exc:
            latency_ms += _elapsed_ms(started)
            last_error = exc
            _notify(
                progress,
                f"{ac_id} / {suite_name}: retry {attempt}/{ATTEMPTS} ({exc})",
            )
            text = str(exc)
            if "seconds of generation" in text or "exceeded 8192 tokens" in text:
                budget = max(_PAIR_PREDICT_MIN, budget // 2)
                correction = (
                    "The previous answer was too long and was rejected. "
                    "Return one JSON object with ac_id, mapped_test_ids, test_types, coverage_status, quality, and finding."
                )
            else:
                correction = (
                    "The previous JSON was rejected: "
                    + text
                    + " Judge this acceptance criterion against this suite batch again. "
                    "Return one JSON object with ac_id, mapped_test_ids, test_types, coverage_status, quality, and finding."
                )
            continue
        latency_ms += _elapsed_ms(started)
        return pair, _token_count(response), latency_ms
    raise NarrativeError(f"analysis failed after {ATTEMPTS} attempts: {last_error}")


def result_from_judgment(
    record: dict,
    judgment: dict,
    token_count: int = 0,
    narrative_latency_ms: int = 0,
) -> dict:
    """Merge a model judgment onto the fetched story. Fetched counts are not replaced."""
    score = _score_from_judgment(record, judgment)
    return {
        "score": score,
        "narrative": _narrative(score, judgment),
        "token_count": token_count,
        "narrative_latency_ms": narrative_latency_ms,
    }


def _criteria_to_judge(record: dict) -> list[dict]:
    """Return every criterion, including criteria with source-side links."""
    chosen: list[dict] = []
    for item in scored_criteria(record):
        if not isinstance(item, dict):
            continue
        ac_id = str(item.get("ac_id") or "")
        if ac_id:
            chosen.append(item)
    return chosen


def _test_suites(record: dict) -> list[tuple[str, str, list[dict]]]:
    """Tests grouped by suite, in the order the suites first appear."""
    groups: dict[str, list[dict]] = {}
    order: list[tuple[str, str]] = []
    for test in record.get("tests") or []:
        if not isinstance(test, dict):
            continue
        suite_id = str(test.get("suite_id") or "").strip()
        suite_name = str(test.get("suite_name") or "").strip()
        key = suite_id or suite_name or "tests"
        name = suite_name or suite_id or "tests"
        if key not in groups:
            groups[key] = []
            order.append((key, name))
        groups[key].append(test)
    return [(key, name, groups[key]) for key, name in order]

def _test_suite_batches(record: dict) -> list[tuple[str, str, list[dict]]]:
    """Split unusually large suites so a small local model sees bounded context."""
    batches: list[tuple[str, str, list[dict]]] = []
    for suite_id, suite_name, tests in _test_suites(record):
        current: list[dict] = []
        current_chars = 0
        for test in tests:
            prompt_row = _test_prompt_row(test)
            size = len(prompt_row.get("title", "")) + len(prompt_row.get("steps", "")) + 120
            if current and current_chars + size > _SUITE_BATCH_CHARS:
                batches.append((suite_id, suite_name, current))
                current = []
                current_chars = 0
            current.append(test)
            current_chars += size
        if current:
            batches.append((suite_id, suite_name, current))
    if not batches:
        # A missing test pack still gets an AC-quality review. The empty suite
        # makes the absence of coverage explicit without inventing a case.
        return [("tests", "No test suite", [])]
    return batches


def _pair_facts(
    record: dict,
    criterion: dict,
    suite_id: str,
    suite_name: str,
    tests: list[dict],
) -> str:
    rows = [_test_prompt_row(test) for test in tests]
    payload = {
        "story_id": str(record.get("id") or ""),
        "acceptance_criterion": {
            "ac_id": str(criterion.get("ac_id") or ""),
            "text": str(criterion.get("text") or "")[:_CRITERION_TEXT_CHARS],
        },
        "suite": {"id": suite_id, "name": suite_name},
        "tests": rows,
    }
    return (
        "Judge this one acceptance criterion against every test in this one suite batch. "
        "Return one JSON object.\n"
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    )


def _test_prompt_row(test: dict) -> dict:
    """Expose only evidence needed for matching; source AC links stay out."""
    row = {
        "id": str(test.get("id") or ""),
        "title": str(test.get("title") or "")[:_TEST_TEXT_CHARS],
        "type": str(test.get("type") or ""),
    }
    steps = str(test.get("steps") or "").strip()
    if steps:
        row["steps"] = steps[:_TEST_TEXT_CHARS]
    return row


def _require_pair(body: dict, criterion: dict, tests: list[dict]) -> dict:
    ac_id = str(criterion.get("ac_id") or "")
    if not isinstance(body, dict):
        raise NarrativeError("analysis is not an object")
    got = str(body.get("ac_id") or "").strip()
    if got and got != ac_id:
        raise NarrativeError(f"analysis ac_id {got} does not match {ac_id}")
    named = body.get("mapped_test_ids")
    if not isinstance(named, list):
        raise NarrativeError("analysis JSON misses mapped_test_ids")
    known = {str(test.get("id") or "") for test in tests}
    ids = []
    for item in named:
        key = str(item)
        if key in known and key not in ids:
            ids.append(key)
    test_types: dict[str, str] = {}
    raw_types = body.get("test_types")
    if isinstance(raw_types, dict):
        for raw_id, raw_type in raw_types.items():
            test_id = str(raw_id)
            test_type = str(raw_type or "").strip().lower()
            if test_type == "positive":
                test_type = "happy"
            if test_id in known and test_type in _TEST_TYPES:
                test_types[test_id] = test_type
    coverage_status = str(body.get("coverage_status") or "").strip().lower().replace(" ", "_")
    if coverage_status not in _COVERAGE_STATUSES:
        coverage_status = _fallback_status(ids, tests)
    quality = _quality_from_body(body.get("quality"), criterion)
    finding = body.get("finding")
    if not isinstance(finding, str) or not finding.strip():
        finding = _default_finding(ac_id, ids)
    else:
        finding = _safe_finding(finding, ac_id, ids)
    return {
        "ac_id": ac_id,
        "mapped_test_ids": ids,
        "test_types": test_types,
        "coverage_status": coverage_status,
        "quality": quality,
        "finding": finding,
    }


def _fallback_status(ids: list[str], tests: list[dict]) -> str:
    """Derive a safe fallback when a small model omits its status field."""
    if not ids:
        return "none"
    titles = {str(test.get("id") or "") for test in tests}
    return "partial" if any(test_id in titles for test_id in ids) else "none"


def _default_quality(criterion: dict) -> dict:
    """Conservative quality baseline used only when no valid model quality exists."""
    text = str(criterion.get("text") or "").strip()
    if not text:
        return {
            "status": "poor",
            "testable": False,
            "issues": ["The acceptance criterion has no text."],
        }
    lowered = text.casefold()
    expected_markers = (
        " should ",
        " must ",
        " remains",
        " stays ",
        " is ",
        " are ",
        " displays",
        " shows",
        " redirected",
        " error",
    )
    if any(marker in f" {lowered} " for marker in expected_markers):
        return {"status": "good", "testable": True, "issues": []}
    return {
        "status": "needs_improvement",
        "testable": True,
        "issues": ["The expected result is not explicit."],
    }


def _quality_from_body(value: object, criterion: dict) -> dict:
    fallback = _default_quality(criterion)
    if not isinstance(value, dict):
        return fallback
    status = str(value.get("status") or "").strip().lower().replace(" ", "_").replace("-", "_")
    if status not in _QUALITY_LEVELS:
        return fallback
    testable = value.get("testable")
    if not isinstance(testable, bool):
        testable = status != "poor"
    raw_issues = value.get("issues")
    issues: list[str] = []
    if isinstance(raw_issues, list):
        for item in raw_issues:
            if not isinstance(item, str) or not item.strip():
                continue
            issue = " ".join(item.split())[:_QUALITY_ISSUE_CHARS].rstrip()
            if issue and issue not in issues:
                issues.append(issue)
    if status == "good":
        issues = []
    return {"status": status, "testable": testable, "issues": issues}


def _merge_quality(left: dict, right: dict) -> dict:
    """Keep the strictest quality result across batches and deduplicate issues."""
    rank = {"good": 0, "needs_improvement": 1, "poor": 2}
    left_status = str(left.get("status") or "needs_improvement")
    right_status = str(right.get("status") or "needs_improvement")
    status = right_status if rank.get(right_status, 1) > rank.get(left_status, 1) else left_status
    issues: list[str] = []
    for source in (left, right):
        for issue in source.get("issues") or []:
            if isinstance(issue, str) and issue not in issues:
                issues.append(issue)
    return {
        "status": status,
        "testable": bool(left.get("testable", True) and right.get("testable", True)),
        "issues": issues[:4],
    }


def _combined_status(ids: list[str], statuses: list[str]) -> str:
    """Use the model's batch claims as a check, but make final status evidence-based."""
    if not ids:
        return "none"
    if statuses and all(status == "adequate" for status in statuses):
        return "adequate"
    if any(status in {"adequate", "partial"} for status in statuses):
        return "partial"
    return "partial"


def _default_finding(ac_id: str, ids: list[str]) -> str:
    if not ids:
        return f"No listed test checks {ac_id}."
    return f"{ac_id} is checked by " + ", ".join(ids) + "."


def _safe_finding(finding: str, ac_id: str, ids: list[str]) -> str:
    text = " ".join(finding.split())
    if len(text) > _FINDING_CHARS:
        text = text[:_FINDING_CHARS].rstrip()
    if "%" in text or "partially covered" in text.casefold():
        return _default_finding(ac_id, ids)
    known = {ac_id, *ids}
    for token in _ID_TOKEN.findall(text):
        if token.upper().startswith("AC-"):
            if token.upper() != ac_id.upper():
                return _default_finding(ac_id, ids)
        elif token not in known:
            return _default_finding(ac_id, ids)
    return text


def _combined_judgment(record: dict, reviews: list[dict], findings: list[str]) -> dict:
    """Health and the headline come from the full record. Reviews are the per-criterion scores."""
    decided = score_health(record)
    return {
        "headline": _headline(record),
        "health": str(decided.get("health") or ""),
        "analysis": _combined_analysis(record, findings),
        "reviews": reviews,
    }


def _headline(record: dict) -> str:
    bugs = _open_bugs(record)
    if not bugs:
        return "No open bugs."
    best = min(_priority_rank(bug) for bug in bugs)
    top = [bug for bug in bugs if _priority_rank(bug) == best]
    label = f"P{best}" if best <= 4 else "unset priority"
    parts = []
    for bug in top:
        bug_id = str(bug.get("id") or "")
        title = str(bug.get("title") or "").strip()
        if bug_id and title:
            parts.append(f"{bug_id}: {title}")
        elif bug_id or title:
            parts.append(bug_id or title)
    if len(parts) == 1:
        return f"Open {label} bug {parts[0]}."
    if parts:
        return f"Open {label} bugs " + "; ".join(parts) + "."
    return f"Open {label} bug."


def _combined_analysis(record: dict, findings: list[str]) -> str:
    parts = _bug_sentences(record) + [item for item in findings if item.strip()]
    if not parts:
        parts.append("No open bug sets health.")
    return " ".join(parts)


def _bug_sentences(record: dict) -> list[str]:
    sentences = []
    for bug in record.get("bugs") or []:
        if not isinstance(bug, dict):
            continue
        bug_id = str(bug.get("id") or "")
        title = str(bug.get("title") or "").strip()
        if is_closed_status(bug.get("status")):
            if bug_id:
                sentences.append(f"Bug {bug_id} is closed and does not set health.")
            continue
        priority = str(bug.get("priority") or "").strip() or "unset priority"
        text = f"Open bug {bug_id} ({priority}) remains" if bug_id else f"Open bug ({priority}) remains"
        if title:
            text += f": {title}"
        sentences.append(text + ".")
    return sentences


def _open_bugs(record: dict) -> list[dict]:
    return [
        bug
        for bug in record.get("bugs") or []
        if isinstance(bug, dict) and not is_closed_status(bug.get("status"))
    ]


def _priority_rank(bug: dict) -> int:
    match = _PRIORITY.search(str(bug.get("priority") or ""))
    if not match:
        return 9
    return int(match.group(1))


def _score_from_judgment(record: dict, judgment: dict) -> dict:
    known_tests = set()
    for test in record.get("tests") or []:
        if isinstance(test, dict):
            known_tests.add(str(test.get("id") or ""))
    factual = score_health(record)
    reviews = _reviews_by_id(judgment.get("reviews"), known_tests)
    scored_tests = _tests_with_predicted_types(record, reviews)
    factual["coverage_by_type"] = _coverage_by_type(scored_tests)
    rows = []
    for criterion in scored_criteria(record):
        if not isinstance(criterion, dict):
            continue
        ac_id = str(criterion.get("ac_id") or "")
        review = reviews.get(ac_id)
        ids = list(review.get("mapped_test_ids") or []) if isinstance(review, dict) else []
        row = coverage_row(
            ac_id,
            ids,
            scored_tests,
            str(criterion.get("text") or ""),
        )
        if isinstance(review, dict):
            row["model_coverage_status"] = str(review.get("coverage_status") or "")
            row["model_status_agrees"] = (
                row["row_status"] == row["model_coverage_status"]
                if row["model_coverage_status"] in _COVERAGE_STATUSES
                else None
            )
            row["ac_quality"] = _quality_from_body(review.get("quality"), criterion)
        else:
            row["model_coverage_status"] = ""
            row["model_status_agrees"] = None
            row["ac_quality"] = _default_quality(criterion)
        rows.append(row)
    factual["scenarios"] = rows
    factual["scenario_count"] = len(rows)
    factual["adequate_count"] = sum(1 for row in rows if row["row_status"] == "adequate")
    factual["partial_count"] = sum(1 for row in rows if row["row_status"] == "partial")
    factual["none_count"] = sum(1 for row in rows if row["row_status"] == "none")
    factual["mapped_count"] = sum(len(row["mapped_test_ids"]) for row in rows)
    factual["rag"] = _rag(rows)
    factual["quality_good_count"] = sum(
        1 for row in rows if row.get("ac_quality", {}).get("status") == "good"
    )
    factual["quality_needs_review_count"] = sum(
        1
        for row in rows
        if row.get("ac_quality", {}).get("status") in {"needs_improvement", "poor"}
    )
    return factual


def _reviews_by_id(reviews: object, known_tests: set[str]) -> dict[str, dict]:
    found = {}
    if not isinstance(reviews, list):
        return found
    for review in reviews:
        if not isinstance(review, dict):
            continue
        ac_id = str(review.get("ac_id") or "").strip()
        if ac_id == "" or ac_id in found:
            continue
        named = review.get("mapped_test_ids")
        ids = []
        if isinstance(named, list):
            for item in named:
                key = str(item)
                if key in known_tests and key not in ids:
                    ids.append(key)
        test_types: dict[str, str] = {}
        raw_types = review.get("test_types")
        if isinstance(raw_types, dict):
            for raw_id, raw_type in raw_types.items():
                test_id = str(raw_id)
                test_type = str(raw_type or "").strip().lower()
                if test_type == "positive":
                    test_type = "happy"
                if test_id in known_tests and test_type in _TEST_TYPES:
                    test_types[test_id] = test_type
        found[ac_id] = {
            **review,
            "mapped_test_ids": ids,
            "test_types": test_types,
        }
    return found


def _tests_with_predicted_types(record: dict, reviews: dict[str, dict]) -> list[dict]:
    """Apply only model classifications for tests whose source type is empty."""
    predicted: dict[str, str] = {}
    for review in reviews.values():
        mapped = {str(test_id) for test_id in review.get("mapped_test_ids") or []}
        for test_id, test_type in (review.get("test_types") or {}).items():
            if test_id not in mapped:
                continue
            if test_id not in predicted:
                predicted[test_id] = test_type
    tests: list[dict] = []
    for test in record.get("tests") or []:
        if not isinstance(test, dict):
            continue
        row = dict(test)
        if not str(row.get("type") or "").strip():
            test_type = predicted.get(str(row.get("id") or ""))
            if test_type in _TEST_TYPES:
                row["type"] = test_type
        tests.append(row)
    return tests


def _coverage_by_type(tests: list[dict]) -> dict[str, int]:
    counts = {
        "happy": 0,
        "negative": 0,
        "edge": 0,
        "security": 0,
        "adhoc": 0,
        "unset": 0,
    }
    for test in tests:
        kind = str(test.get("type") or "").strip().lower()
        if kind == "positive":
            kind = "happy"
        if kind in counts and kind != "unset":
            counts[kind] += 1
        else:
            counts["unset"] += 1
    return counts


def _rag(rows: list[dict]) -> str:
    if not rows:
        return "Unavailable"
    if all(row["row_status"] == "none" for row in rows):
        return "Red"
    if any(row["row_status"] != "adequate" for row in rows):
        return "Amber"
    return "Green"


def _narrative(score: dict, judgment: dict) -> dict:
    health = score.get("health")
    observations = [
        f"Story health - {health}",
        (
            f"{score.get('scenario_count')} acceptance criteria, "
            f"{score.get('adequate_count')} adequately covered, "
            f"{score.get('partial_count')} with gaps, "
            f"{score.get('none_count')} not covered."
        ),
        f"{score.get('test_count')} tests and {score.get('mapped_count')} mapped.",
        f"{score.get('bug_count')} bugs, with {score.get('open_bug_count')} open.",
    ]
    p1_ids = open_bug_ids(list(score.get("bugs") or []), "P1")
    if p1_ids:
        observations.append("Open P1 bugs: " + ", ".join(p1_ids) + ".")
    gapped = [
        str(row.get("ac_id") or "")
        for row in score.get("scenarios") or []
        if isinstance(row, dict) and row.get("row_status") in ("partial", "none") and row.get("ac_id")
    ]
    if gapped:
        observations.append("Criteria with gaps: " + ", ".join(gapped) + ".")
    quality_gaps = [
        str(row.get("ac_id") or "")
        for row in score.get("scenarios") or []
        if isinstance(row, dict)
        and isinstance(row.get("ac_quality"), dict)
        and row["ac_quality"].get("status") in {"needs_improvement", "poor"}
        and row.get("ac_id")
    ]
    if quality_gaps:
        observations.append("Criteria needing AC-quality review: " + ", ".join(quality_gaps) + ".")
    sections = []
    analysis = judgment.get("analysis")
    if isinstance(analysis, str) and analysis.strip():
        text = _analysis_text(analysis, score)
        if text:
            observations.extend(_sentences(text))
            sections.append({"name": "Analysis", "prose": text})
    coverage = []
    for row in score.get("scenarios") or []:
        if isinstance(row, dict):
            coverage.append(f"{row.get('ac_id')}: {row.get('row_status')}. {row.get('gap')}")
    if coverage:
        sections.append({"name": "Coverage", "prose": " ".join(coverage)})
    return {
        "headline": str(judgment.get("headline") or "").strip(),
        "observations": observations,
        "sections": sections,
        "actions": _actions_from_score(score),
    }


def _actions_from_score(score: dict) -> list[dict]:
    """One Dev action per open bug, and one QA action per criterion that is not adequate."""
    actions = []
    for bug in score.get("bugs") or []:
        if not isinstance(bug, dict) or is_closed_status(bug.get("status")):
            continue
        bug_id = str(bug.get("id") or "")
        if not bug_id:
            continue
        title = str(bug.get("title") or "").strip()
        text = f"Fix open bug {bug_id}"
        if title:
            text += f": {title}"
        actions.append({"owner": "Dev", "text": text + "."})
    for row in score.get("scenarios") or []:
        if not isinstance(row, dict) or row.get("row_status") not in ("partial", "none"):
            continue
        ac_id = str(row.get("ac_id") or "")
        if not ac_id:
            continue
        gap = str(row.get("gap") or "").replace("\n", "; ")
        actions.append({"owner": "QA", "text": f"Close the coverage gap on {ac_id}. {gap}."})
    for row in score.get("scenarios") or []:
        if not isinstance(row, dict):
            continue
        quality = row.get("ac_quality")
        if not isinstance(quality, dict) or quality.get("status") not in {"needs_improvement", "poor"}:
            continue
        ac_id = str(row.get("ac_id") or "")
        if not ac_id:
            continue
        issues = "; ".join(str(item) for item in quality.get("issues") or [] if str(item).strip())
        text = f"Improve the quality of {ac_id} before using it as a test oracle"
        if issues:
            text += f": {issues}"
        actions.append({"owner": "PO", "text": text + "."})
    if not actions:
        actions.append(
            {
                "owner": "QA",
                "text": (
                    "No open bugs and every acceptance criterion has "
                    "positive, negative, and adhoc coverage."
                ),
            }
        )
    return actions


def _analysis_text(analysis: str, score: dict) -> str:
    """Keep the model's sentences when every id they name is on the score."""
    text = analysis.strip()[:_ANALYSIS_CHARS]
    known = {str(score.get("story_id") or "")}
    for bug in score.get("bugs") or []:
        if isinstance(bug, dict):
            known.add(str(bug.get("id") or ""))
    for row in score.get("scenarios") or []:
        if not isinstance(row, dict):
            continue
        known.add(str(row.get("ac_id") or ""))
        for test_id in row.get("mapped_test_ids") or []:
            known.add(str(test_id))
    for token in _ID_TOKEN.findall(text):
        if token.upper().startswith("AC-"):
            if token.upper() not in {item.upper() for item in known}:
                return ""
        elif token not in known:
            return ""
    return text


def _sentences(text: str) -> list[str]:
    """One observation bullet per sentence, so a long analysis stays readable."""
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [part.strip() for part in parts if part.strip()]
