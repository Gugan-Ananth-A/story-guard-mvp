"""One local-model review of a live story. Counts stay on the fetched record."""

import json
import re
import time

from story_guard.narrative import (
    ATTEMPTS,
    MAX_TOKENS,
    NarrativeError,
    _check_cap,
    _elapsed_ms,
    _load_json_object,
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

_HEALTH = {
    "Critical": "At Risk",
    "High": "At Risk",
    "Medium": "Healthy",
    "Low": "Healthy",
    "No open bugs": "No open bugs",
}
_OWNERS = {"QA", "Dev", "PO"}
_PREDICT_BASE = 3072
_PREDICT_PER_CRITERION = 384
_ANALYSIS_CHARS = 4000
_ID_TOKEN = re.compile(r"\bAC-\d+\b|\b\d{5,}\b", re.IGNORECASE)
_TASK = (
    "Evaluate every acceptance criterion that still needs a review. "
    "The facts already decide health and the linked coverage rows. "
    "Think through the open bugs and any criterion that still needs a review. "
    "Then return one JSON object.\n"
)
_PROMPT = """You evaluate one user story for a QA health report. The next message is JSON fetched from Azure DevOps. It is the only source of facts. Compare the text of each acceptance criterion with the titles of the tests. Then set story health from the bugs.

Return one JSON object and nothing else. Do not use a Markdown fence. Do not call tools.
{
  "headline": "one sentence naming the main risk",
  "health": "Critical" | "High" | "Medium" | "Low" | "No open bugs",
  "analysis": "six to ten sentences",
  "reviews": [
    {
      "ac_id": "the id copied from acceptance_criteria",
      "row_status": "adequate" | "partial" | "none",
      "depth": "what the named tests actually check",
      "gap": "what is still missing",
      "mapped_test_ids": ["test ids copied from tests"]
    }
  ],
  "actions": [
    {"owner": "QA" | "Dev" | "PO", "text": "one concrete action"}
  ]
}

How to judge coverage. Return one review for every acceptance criterion that the user message still asks you to judge. When the user message says reviews must be [], return an empty reviews list.
- Read that criterion's text, including the expected result.
- A test may be listed on that criterion only when its title checks the same behavior and the same expected result. Sharing a word such as "login" is not enough.
- The test type field is a hint. An empty type does not block a match, and it does not create one.
- When a test lists mapped_ac_ids, those links are already decided. Put that test on each listed criterion and on no other criterion. A review cannot clear a listed link.
- none: no listed test checks that criterion. mapped_test_ids is empty. depth is "None". gap says that no listed test checks it.
- partial: one or more listed tests check part of the criterion, and a behavior or expected result in the text is still untested. Name only the tests that do check it. gap names the missing part.
- adequate: the named tests check the criterion's behavior and its expected result. When the criterion describes a failure or a rejection, an adequate review also names a test that checks that failure.
- If tests is empty, every review is none.
- Use each ac_id exactly as written. Do not add a review for an id that is not in acceptance_criteria. Do not skip a criterion.
- Do not put the same test on a criterion it does not check.

How to judge health. Coverage does not change health.
- Copy the health value from the facts. Do not choose a different one.
- Use only bugs whose open field is true. Ignore bugs whose open field is false.
- Among those open bugs, read priority. P1 is the most severe, then P2, then P3, then P4.
- An open P1 sets health to Critical.
- Otherwise an open P2 sets health to High.
- Otherwise an open P3 sets health to Medium.
- Otherwise an open P4 sets health to Low.
- If an open bug has no P1, P2, P3, or P4 priority, set health to High.
- If no bug is open, health is No open bugs.
- Do not use the words Red, Amber, or Green for health.

How to write the analysis:
- Write six to ten sentences. Use the room. A two-sentence answer is incomplete.
- Name every open bug id that sets health, not only the first one. When several open bugs share that priority, name each id and what it breaks.
- Name a closed bug only to say it does not set health. Include a Rejected or Unable to Reproduce bug when one is in the facts.
- Name the criteria whose gap changes the story: a missing Positive, Negative, or Adhoc bucket, and any expected result that no test title states. Give the criterion id and the missing part.
- Do not restate the total counts. The report prints those counts.
- Do not use a percent sign.
- Do not write the phrase "partially covered". The row_status value partial is the allowed word for a gap.
- Do not invent a test id, a bug id, or an acceptance-criterion id.
- Each depth and each gap is at most eight words.

How to write the headline and the actions:
- The headline is one sentence. Name the highest open bug, or the largest coverage gap when no bug is open.
- Return 3 to 7 actions.
- owner is exactly QA, Dev, or PO.
- Dev actions name an open bug id to fix.
- QA actions name a criterion id that is partial or none and the test that should be added or mapped.
- PO actions name a criterion id whose text has no expected result.
- Every action uses an id copied from the input.
"""


def analyze_live(record: dict) -> dict:
    """Ask the local model to judge this story, then build the report score from that judgment."""
    if not isinstance(record, dict):
        raise NarrativeError("story record is not an object")
    unlinked = _unlinked_ids(record)
    facts_message = _TASK + _output_limit(unlinked) + _facts_for_request(record, unlinked)
    budget = _predict_budget(len(unlinked))
    last_error: NarrativeError | None = None
    correction: str | None = None
    latency_ms = 0
    for _attempt in range(ATTEMPTS):
        messages = [
            {"role": "system", "content": _PROMPT},
            {"role": "user", "content": facts_message},
        ]
        if correction:
            messages.append({"role": "user", "content": correction})
        started = time.perf_counter()
        try:
            response = ollama_chat(messages, num_predict=budget)
            _check_cap(response)
            judgment = _load_json_object(_message_text(response))
            _require_judgment(judgment)
        except NarrativeError as exc:
            latency_ms += _elapsed_ms(started)
            last_error = exc
            text = str(exc)
            if "seconds of generation" in text:
                budget = max(1024, budget // 2)
                correction = (
                    "The previous answer was too long and was rejected. "
                    "Return one complete JSON object. analysis is six to ten sentences. "
                    + (
                        "reviews must be []."
                        if not unlinked
                        else "Keep each review to one line."
                    )
                )
            else:
                correction = (
                    "The previous JSON was rejected: "
                    + text
                    + " Judge coverage and health again from the same facts. "
                    "Return one JSON object that satisfies every rule."
                )
            continue
        latency_ms += _elapsed_ms(started)
        return result_from_judgment(
            record,
            judgment,
            token_count=_token_count(response),
            narrative_latency_ms=latency_ms,
        )
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


def _output_limit(unlinked: list[str]) -> str:
    if not unlinked:
        return (
            "Every acceptance criterion already has mapped_ac_ids. "
            "reviews must be []. analysis is six to ten sentences. "
            "Name every open bug that sets health and every criterion gap that changes the story.\n"
        )
    return (
        "Return one review only for these ac ids: "
        + ", ".join(unlinked)
        + ". Each depth and each gap is at most eight words. "
        "analysis is six to ten sentences.\n"
    )


def _predict_budget(unlinked_count: int) -> int:
    """Leave room for the model to think, then emit the JSON."""
    return min(MAX_TOKENS, _PREDICT_BASE + _PREDICT_PER_CRITERION * unlinked_count)


def _unlinked_ids(record: dict) -> list[str]:
    linked = _links_by_ac(record)
    unlinked = []
    for item in scored_criteria(record):
        if not isinstance(item, dict):
            continue
        ac_id = str(item.get("ac_id") or "")
        if ac_id and ac_id not in linked:
            unlinked.append(ac_id)
    return unlinked


def _links_by_ac(record: dict) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for test in record.get("tests") or []:
        if not isinstance(test, dict):
            continue
        test_id = str(test.get("id") or "")
        links = test.get("mapped_ac_ids")
        if not isinstance(links, list):
            continue
        for ac_id in links:
            key = str(ac_id)
            bucket = found.setdefault(key, [])
            if test_id and test_id not in bucket:
                bucket.append(test_id)
    return found


def _facts_for_request(record: dict, unlinked: list[str]) -> str:
    if unlinked:
        return _facts(record)
    rows = []
    for row in score_health(record).get("scenarios") or []:
        if not isinstance(row, dict):
            continue
        rows.append(
            {
                "ac_id": str(row.get("ac_id") or ""),
                "row_status": str(row.get("row_status") or ""),
                "gap": str(row.get("gap") or ""),
                "mapped_test_ids": [str(item) for item in row.get("mapped_test_ids") or []],
            }
        )
    decided = score_health(record)
    return json.dumps(
        {
            "story_id": str(record.get("id") or ""),
            "title": str(record.get("title") or ""),
            "health": str(decided.get("health") or ""),
            "coverage": rows,
            "bugs": _bug_facts(record),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _facts(record: dict) -> str:
    criteria = []
    for item in scored_criteria(record):
        if not isinstance(item, dict):
            continue
        criteria.append(
            {
                "ac_id": str(item.get("ac_id") or ""),
                "text": str(item.get("text") or ""),
            }
        )
    tests = []
    for test in record.get("tests") or []:
        if not isinstance(test, dict):
            continue
        links = test.get("mapped_ac_ids")
        tests.append(
            {
                "id": str(test.get("id") or ""),
                "title": str(test.get("title") or ""),
                "type": str(test.get("type") or ""),
                "mapped_ac_ids": (
                    [str(item) for item in links if str(item).strip()]
                    if isinstance(links, list)
                    else []
                ),
            }
        )
    decided = score_health(record)
    return json.dumps(
        {
            "story_id": str(record.get("id") or ""),
            "title": str(record.get("title") or ""),
            "state": str(record.get("state") or ""),
            "health": str(decided.get("health") or ""),
            "acceptance_criteria": criteria,
            "tests": tests,
            "bugs": _bug_facts(record),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _bug_facts(record: dict) -> list[dict]:
    bugs = []
    for bug in record.get("bugs") or []:
        if not isinstance(bug, dict):
            continue
        status = str(bug.get("status") or "")
        bugs.append(
            {
                "id": str(bug.get("id") or ""),
                "title": str(bug.get("title") or ""),
                "status": status,
                "open": not is_closed_status(status),
                "priority": str(bug.get("priority") or ""),
                "severity": str(bug.get("severity") or ""),
                "found_in": str(bug.get("found_in") or ""),
            }
        )
    return bugs


def _message_text(response: dict) -> str:
    message = response.get("message")
    if not isinstance(message, dict):
        raise NarrativeError("ollama response has no message")
    content = message.get("content")
    if not isinstance(content, str):
        raise NarrativeError("ollama message content is not text")
    return content


def _require_judgment(body: dict) -> None:
    if not isinstance(body, dict):
        raise NarrativeError("analysis is not an object")
    health = body.get("health")
    if not isinstance(health, str) or health.strip() not in _HEALTH:
        raise NarrativeError(
            "analysis health must be Critical, High, Medium, Low, or No open bugs"
        )
    body["health"] = health.strip()
    headline = body.get("headline")
    if not isinstance(headline, str) or not headline.strip():
        raise NarrativeError("analysis JSON misses headline")
    if not isinstance(body.get("analysis"), str):
        raise NarrativeError("analysis JSON misses analysis")
    if not isinstance(body.get("reviews"), list):
        raise NarrativeError("analysis JSON misses reviews")
    actions = body.get("actions")
    if not isinstance(actions, list) or not 3 <= len(actions) <= 7:
        raise NarrativeError("analysis JSON misses actions")
    for action in actions:
        if not isinstance(action, dict):
            raise NarrativeError("analysis action is not an object")
        owner = action.get("owner")
        text = action.get("text")
        if not isinstance(owner, str) or owner.strip() not in _OWNERS:
            raise NarrativeError("analysis action owner must be QA, Dev, or PO")
        if not isinstance(text, str) or not text.strip():
            raise NarrativeError("analysis action misses text")


def _score_from_judgment(record: dict, judgment: dict) -> dict:
    known_tests = set()
    for test in record.get("tests") or []:
        if isinstance(test, dict):
            known_tests.add(str(test.get("id") or ""))
    factual = score_health(record)
    reviews = _reviews_by_id(judgment.get("reviews"), known_tests)
    deterministic = {
        str(row.get("ac_id") or ""): row
        for row in factual.get("scenarios") or []
        if isinstance(row, dict)
    }
    rows = []
    for criterion in scored_criteria(record):
        if not isinstance(criterion, dict):
            continue
        ac_id = str(criterion.get("ac_id") or "")
        existing = deterministic.get(ac_id)
        if isinstance(existing, dict) and existing.get("mapped_test_ids"):
            rows.append(existing)
            continue
        review = reviews.get(ac_id)
        ids = list(review.get("mapped_test_ids") or []) if isinstance(review, dict) else []
        rows.append(
            coverage_row(ac_id, ids, list(record.get("tests") or []), str(criterion.get("text") or ""))
        )
    factual["scenarios"] = rows
    factual["scenario_count"] = len(rows)
    factual["adequate_count"] = sum(1 for row in rows if row["row_status"] == "adequate")
    factual["partial_count"] = sum(1 for row in rows if row["row_status"] == "partial")
    factual["none_count"] = sum(1 for row in rows if row["row_status"] == "none")
    factual["mapped_count"] = sum(len(row["mapped_test_ids"]) for row in rows)
    factual["rag"] = _rag(rows)
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
        found[ac_id] = {**review, "mapped_test_ids": ids}
    return found


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
