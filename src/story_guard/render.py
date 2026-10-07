"""Fill the six-section health report template and write markdown."""

import re
from datetime import datetime, timezone
from pathlib import Path

_HEADING = re.compile(r"(?m)^#+ .+$")
_CLOSED = {"resolved", "closed", "rejected", "unable to reproduce"}
_BUG_COLUMNS = (
    ("Bug ID", "id"),
    ("Title", "title"),
    ("State", "status"),
    ("Story ID", "linked_story_id"),
    ("TC ID", "linked_tc_id"),
    ("Priority", "priority"),
    ("Severity", "severity"),
    ("Assigned To", "assigned_to"),
    ("Found in Env", "found_in"),
    ("Application", "application"),
    ("Created", "created"),
)
_SLOTS = (
    "title_block",
    "story_health",
    "coverage",
    "bugs",
    "actions",
    "appendix",
)


class RenderError(Exception):
    """The report template could not be filled. The caller writes no file."""


def render_markdown(
    score: dict,
    narrative: dict,
    template_path: Path | str,
    out_path: Path | str,
    record: dict | None = None,
    generated_at: str | None = None,
) -> Path:
    """Fill templates/health_report.md and write markdown. A missing template writes nothing."""
    if not isinstance(score, dict):
        raise RenderError("score is not an object")
    if not isinstance(narrative, dict):
        raise RenderError("narrative is not an object")
    path = Path(template_path)
    out = Path(out_path)
    if not path.is_file():
        raise RenderError(f"template {path} is missing")
    template = path.read_text(encoding="utf-8")
    if len(_HEADING.findall(template)) != 6:
        raise RenderError("template does not have six headings")
    if generated_at is None:
        generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    values = {
        "title_block": _title_block(score, record, narrative, generated_at),
        "story_health": _story_health(score, narrative),
        "coverage": _coverage(score),
        "bugs": _bugs(score),
        "actions": _actions(narrative),
        "appendix": _appendix(score, record),
    }
    text = template
    for key in _SLOTS:
        token = "{{" + key + "}}"
        if token not in text:
            raise RenderError(f"template misses {token}")
        text = text.replace(token, values[key])
    if "{{" in text:
        raise RenderError("template has an unfilled placeholder")
    out.parent.mkdir(parents=True, exist_ok=True)
    temporary = out.with_suffix(out.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(out)
    return out


def _title_block(score: dict, record: dict | None, narrative: dict, generated_at: str) -> str:
    project = ""
    if isinstance(record, dict):
        project = _cell(record.get("area"))
    source = score.get("source")
    source_label = "dummy fixture" if source == "fixture" else _cell(source)
    lines = [
        "Story Health Report",
        f"Story id: {_cell(score.get('story_id'))}",
        f"Title: {_cell(score.get('title'))}",
        f"Project: {project}",
        f"Generated at: {generated_at}",
        f"Source: {source_label}",
        "User story health, test coverage, and defect status.",
    ]
    headline = _plain(narrative.get("headline"))
    if headline:
        lines.append(headline)
    return "\n".join(lines)


def _story_health(score: dict, narrative: dict) -> str:
    counts = score.get("open_bugs_by_priority")
    if not isinstance(counts, dict):
        counts = {}
    rules = score.get("rule_ids")
    if not isinstance(rules, list):
        rules = []
    lines = [
        f"Story health: {_cell(score.get('health'))}",
        f"Band: {_cell(score.get('health_band'))}",
        "Rules: " + ", ".join(str(rule) for rule in rules),
        f"Open P1: {_count(counts.get('P1'))}",
        f"Open P2: {_count(counts.get('P2'))}",
        f"Open P3: {_count(counts.get('P3'))}",
        f"Open P4: {_count(counts.get('P4'))}",
        f"Escaped: {_count(score.get('escaped_bug_count'))}",
        (
            f"Tests: {_count(score.get('test_count'))}. "
            f"Mapped: {_count(score.get('mapped_count'))}. "
            f"Bugs: {_count(score.get('bug_count'))}."
        ),
    ]
    note = score.get("note")
    if isinstance(note, str) and note.strip():
        lines.append(_plain(note))
    prose = _section_prose(narrative)
    if prose:
        lines.append(prose)
    return "\n".join(lines)


def _coverage(score: dict) -> str:
    ac_field = score.get("ac_field")
    if ac_field == "empty":
        ac_line = "The AC field is empty."
    else:
        ac_line = f"The AC field is {_cell(ac_field)}."
    count_line = (
        f"{_count(score.get('scenario_count'))} acceptance criteria | "
        f"{_count(score.get('adequate_count'))} adequately covered | "
        f"{_count(score.get('partial_count'))} with gaps | "
        f"{_count(score.get('none_count'))} not covered"
    )
    rows = [
        "| AC ID | Coverage depth | Coverage gap |",
        "| --- | --- | --- |",
    ]
    scenarios = score.get("scenarios")
    if isinstance(scenarios, list):
        for row in scenarios:
            if not isinstance(row, dict):
                continue
            rows.append(
                "| "
                + " | ".join(
                    (
                        _cell(row.get("ac_id")),
                        _cell(row.get("depth")),
                        _cell(row.get("gap")),
                    )
                )
                + " |"
            )
    rows.append("")
    rows.append("Color key: Adequate, Partial, None.")
    return "\n".join([ac_line, count_line, "", *rows])


def _bugs(score: dict) -> str:
    header = "| " + " | ".join(name for name, _key in _BUG_COLUMNS) + " |"
    rule = "| " + " | ".join("---" for _name, _key in _BUG_COLUMNS) + " |"
    bugs = score.get("bugs")
    rows = [bug for bug in bugs if isinstance(bug, dict)] if isinstance(bugs, list) else []
    rows.sort(key=_bug_sort)
    lines = [header, rule]
    if not rows:
        lines.append("")
        lines.append("No bugs.")
        return "\n".join(lines)
    for bug in rows:
        cells = []
        for _name, key in _BUG_COLUMNS:
            text = _cell(bug.get(key))
            if key == "status" and _closed(bug):
                text = (text + " not open").strip()
            if key == "found_in" and _escaped(bug):
                text = (text + " escaped").strip()
            cells.append(text)
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _actions(narrative: dict) -> str:
    actions = narrative.get("actions")
    if not isinstance(actions, list):
        return ""
    lines = []
    for action in actions:
        if not isinstance(action, dict):
            continue
        owner = action.get("owner", action.get("owner_role"))
        text = action.get("text", action.get("action"))
        lines.append(f"- {_cell(owner)}: {_plain(text)}")
    return "\n".join(lines)


def _appendix(score: dict, record: dict | None) -> str:
    ac_ids = _ids(score.get("scenarios"), "ac_id")
    bug_ids = _ids(score.get("bugs"), "id")
    test_ids: list[str] = []
    if isinstance(record, dict):
        test_ids = _ids(record.get("tests"), "id")
    return "\n".join(
        [
            f"Story id: {_cell(score.get('story_id'))}",
            "AC ids: " + (", ".join(ac_ids) if ac_ids else "(none)"),
            "Test ids: " + (", ".join(test_ids) if test_ids else "(none)"),
            "Bug ids: " + (", ".join(bug_ids) if bug_ids else "(none)"),
        ]
    )


def _section_prose(narrative: dict) -> str:
    sections = narrative.get("sections")
    if not isinstance(sections, list):
        return ""
    blocks = []
    for section in sections:
        if isinstance(section, str):
            text = _plain(section)
        elif isinstance(section, dict):
            name = _plain(section.get("name") or section.get("heading"))
            prose = _plain(section.get("prose") or section.get("text"))
            if name and prose:
                text = f"{name}: {prose}"
            else:
                text = prose or name
        else:
            text = ""
        if text:
            blocks.append(text)
    return "\n\n".join(blocks)


def _ids(items: object, key: str) -> list[str]:
    if not isinstance(items, list):
        return []
    found = []
    for item in items:
        if isinstance(item, dict) and item.get(key) not in (None, ""):
            found.append(str(item[key]))
    return found


def _bug_sort(bug: dict) -> tuple:
    text = str(bug.get("priority") or "").upper()
    for index, label in enumerate(("P1", "P2", "P3", "P4")):
        if label in text:
            return (index, text)
    return (9, text)


def _closed(bug: dict) -> bool:
    return str(bug.get("status") or "").strip().lower() in _CLOSED


def _escaped(bug: dict) -> bool:
    found = str(bug.get("found_in") or "").lower()
    return "uat" in found or "prod" in found


def _count(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value


def _cell(value: object) -> str:
    if value is None:
        return ""
    return str(value).replace("\n", " ").replace("|", "/").strip()


def _plain(value: object) -> str:
    if value is None:
        return ""
    kept = []
    for line in str(value).splitlines():
        stripped = line.strip()
        while stripped.startswith("#"):
            stripped = stripped[1:].strip()
        kept.append(stripped)
    return "\n".join(kept).strip()
