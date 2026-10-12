"""Render score-derived report content to Markdown and PDF."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import SimpleDocTemplate

from story_guard.score import scored_criteria

_PLACEHOLDER = re.compile(r"{{\s*([a-z_]+)\s*}}")


def _id_list(values: list[str] | None) -> str:
    return ", ".join(values) if values else "None recorded"


def _format_acceptance_criteria(score: dict[str, Any]) -> str:
    criteria = score.get("acceptance_criteria")
    if criteria is None:
        return "Acceptance criteria unavailable in the score object."
    if not criteria:
        return "No acceptance criteria recorded."

    lines = [f"{len(criteria)} acceptance criteria are present."]
    for criterion in criteria:
        flags = ", ".join(criterion.get("flags", [])) or "none"
        testable = "yes" if criterion.get("testable") else "no"
        lines.append(
            f"{criterion['id']}: {criterion['text']} "
            f"(testable: {testable}; flags: {flags})"
        )
    return "\n".join(lines)


def _format_test_mappings(score: dict[str, Any]) -> str:
    criteria = score.get("acceptance_criteria")
    mappings = score.get("test_mappings")
    if criteria is None or mappings is None:
        return "AC-to-test mapping unavailable in the score object."

    mapping_by_ac = {mapping["ac_id"]: mapping["test_ids"] for mapping in mappings}
    lines = [
        f"Explicitly mapped ACs: {score['coverage']['mapped_ac_count']}; "
        f"uncovered ACs: {score['coverage']['uncovered_ac_count']}."
    ]
    for criterion in criteria:
        ac_id = criterion["id"]
        if ac_id not in mapping_by_ac:
            lines.append(f"{ac_id}: mapping unavailable in the score object.")
            continue

        test_ids = mapping_by_ac[ac_id]
        if test_ids:
            lines.append(f"{ac_id}: explicitly linked tests: {_id_list(test_ids)}.")
        else:
            lines.append(f"{ac_id}: no explicit test link; uncovered.")
    return "\n".join(lines)


def _format_coverage(score: dict[str, Any]) -> str:
    coverage = score.get("coverage")
    if coverage is None:
        return "Coverage information unavailable in the score object."

    percentage = coverage.get("test_coverage_percent")
    percentage_text = (
        f"{percentage}% (provided by the score object)"
        if percentage is not None
        else "unavailable in the score object"
    )
    counts = ", ".join(
        f"{coverage_type}: {count}"
        for coverage_type, count in coverage["by_type"].items()
    )
    return "\n".join(
        [
            f"Total tests: {coverage['total_tests']}",
            f"Test coverage: {percentage_text}",
            f"Coverage by type: {counts}",
        ]
    )

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
_EIGHT_SECTION_FIELDS = {
    "story_id",
    "title",
    "generated_at",
    "source",
    "overall_rag",
    "headline",
    "ac_review",
    "ac_test_mapping",
    "coverage_by_type",
    "bugs",
    "recommended_actions",
    "raw_story_ids",
    "raw_ac_ids",
    "raw_test_ids",
    "raw_bug_ids",
}
_REQUIRED_HEADINGS = (
    "Title block",
    "Overall RAG",
    "AC review",
    "AC ↔ test mapping",
    "Coverage by type",
    "Bugs",
    "Recommended actions",
    "Appendix",
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
    """Fill the frozen report template and atomically write Markdown."""
    if not isinstance(score, dict):
        raise RenderError("score is not an object")
    if not isinstance(narrative, dict):
        raise RenderError("narrative is not an object")
    path = Path(template_path)
    out = Path(out_path)
    text = _rendered_markdown(score, path, narrative, record, generated_at)
    text = "\n".join(line.rstrip() for line in text.splitlines())
    if text:
        text += "\n"
    out.parent.mkdir(parents=True, exist_ok=True)
    temporary = out.with_suffix(out.suffix + ".tmp")
    try:
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(out)
    finally:
        temporary.unlink(missing_ok=True)
    return out


def _rendered_markdown(
    score: dict,
    template_path: Path,
    narrative: dict | None,
    record: dict | None,
    generated_at: str | None = None,
) -> str:
    template = validate_template(template_path)
    values = _template_values(score, narrative, record, generated_at)
    return _fill_template(template, values)


def validate_template(template_path: str | Path) -> str:
    """Validate and return the required report template without fallback behavior."""
    path = Path(template_path)
    if not path.is_file():
        raise RenderError(f"template {path} is missing")
    try:
        template = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise RenderError(f"template {path} cannot be read: {error}") from error
    headings = tuple(heading.strip() for heading in _HEADING.findall(template))
    if headings != tuple(f"## {heading}" for heading in _REQUIRED_HEADINGS):
        raise RenderError("template does not have the required eight headings in order")
    fields = set(_PLACEHOLDER.findall(template))
    if fields != _EIGHT_SECTION_FIELDS:
        missing = sorted(_EIGHT_SECTION_FIELDS - fields)
        extra = sorted(fields - _EIGHT_SECTION_FIELDS)
        raise RenderError(f"template fields mismatch; missing={missing}, extra={extra}")
    return template


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


def _format_bugs(score: dict[str, Any]) -> str:
    bugs = score.get("bugs")
    if bugs is None:
        return "Bug information unavailable in the score object."

    lines = [f"Open bugs: {bugs['open_count']}"]
    for bug in bugs["items"]:
        lines.append(
            f"{bug['id']}: {bug['title']} - {bug['severity']}, {bug['status']}, "
            f"age {bug['age_days']} days, linked test {bug['linked_tc_id']}, "
            f"found in {bug['found_in_env']}."
        )
    return "\n".join(lines)


def _format_actions(score: dict[str, Any]) -> str:
    actions = score.get("recommended_actions")
    if actions is None:
        return "Recommended actions unavailable in the score object."
    return "\n".join(
        f"{action['owner_role']}: {action['text']}" for action in actions
    )


def _template_values(
    score: dict[str, Any],
    narrative: dict | None = None,
    record: dict | None = None,
    generated_at: str | None = None,
) -> dict[str, str]:
    narrative = narrative if isinstance(narrative, dict) else {}
    if "story" in score:
        story = score.get("story") or {}
        appendix = score.get("appendix") or {}
        coverage = score.get("coverage") or {}
        story_id = story.get("id", "")
        title = story.get("title", "")
        scenario_count = len(score.get("acceptance_criteria") or [])
        test_count = coverage.get("total_tests", 0)
        mapped_count = coverage.get("mapped_ac_count", 0)
        bug_count = (score.get("bugs") or {}).get("open_count", 0)
        coverage_by_type = coverage.get("by_type", {})
        rag = score.get("rag", "Unavailable in the score object.")
        health = rag
        rule_ids = score.get("rule_ids", [])
        ac_field = "present" if score.get("acceptance_criteria") else "empty"
        scenario_rows = score.get("acceptance_criteria") or []
        tests = score.get("test_ids") or []
        bugs = (score.get("bugs") or {}).get("items", [])
        ac_ids = appendix.get("ac_ids", [])
        test_ids = appendix.get("test_ids", tests)
        bug_ids = appendix.get("bug_ids", [])
    else:
        story_id = score.get("story_id", "")
        title = score.get("title", "")
        scenario_count = score.get("scenario_count", len(score.get("scenarios") or []))
        test_count = score.get("test_count", 0)
        mapped_count = score.get("mapped_count", 0)
        bug_count = score.get("bug_count", 0)
        coverage_by_type = score.get("coverage_by_type", {})
        rag = score.get("rag", "Unavailable in the score object.")
        health = score.get("health", rag)
        rule_ids = score.get("rule_ids", [])
        ac_field = score.get("ac_field", "unavailable")
        scenario_rows = score.get("scenarios", [])
        tests = (record or {}).get("tests", [])
        bugs = score.get("bugs", [])
        ac_ids = [row.get("ac_id", "") for row in scenario_rows if isinstance(row, dict)]
        test_ids = [row.get("id", "") for row in tests if isinstance(row, dict)]
        bug_ids = [row.get("id", "") for row in bugs if isinstance(row, dict)]

    if generated_at is None:
        generated_at = str(
            score.get("generated_at")
            or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        )
    scored_scenarios = score.get("scenarios", scenario_rows)
    if "story" not in score and isinstance(record, dict):
        display_scenarios = scored_criteria(record)
        ac_ids = [
            str(row.get("ac_id", ""))
            for row in display_scenarios
            if isinstance(row, dict) and row.get("ac_id")
        ]
    else:
        display_scenarios = scenario_rows
    mapping_lines = [f"Mapped ACs: {mapped_count}"]
    for row in scored_scenarios if isinstance(scored_scenarios, list) else []:
        if not isinstance(row, dict):
            continue
        ac_id = row.get("ac_id", "")
        links = row.get("mapped_test_ids", row.get("mapped_ac_ids", []))
        mapping_lines.append(
            f"{ac_id}: linked tests {', '.join(map(str, links)) if links else 'None'}"
        )
    coverage_lines = [
        f"{scenario_count} acceptance criteria | {score.get('adequate_count', 0)} adequately covered | {score.get('partial_count', 0)} with gaps | {score.get('none_count', 0)} not covered",
        f"Total tests: {test_count}",
        f"Tests: {test_count}. Mapped: {mapped_count}. Bugs: {bug_count}.",
        f"Coverage by type: {', '.join(f'{key}: {value}' for key, value in coverage_by_type.items())}",
        f"Adequate: {score.get('adequate_count', 0)}; Partial: {score.get('partial_count', 0)}; None: {score.get('none_count', 0)}",
        "Color key: Adequate, Partial, None.",
    ]
    ac_lines = [f"The AC field is {ac_field}.", f"Scenarios: {scenario_count}"]
    for row in display_scenarios if isinstance(display_scenarios, list) else []:
        if isinstance(row, dict):
            ac_lines.append(f"{row.get('ac_id', '')}: {row.get('text', row.get('depth', ''))}")
    if isinstance(coverage_by_type, dict):
        coverage_lines.append(
            f"Test count: {test_count}; mapped AC count: {mapped_count}; bug count: {bug_count}"
        )
    bug_lines = [
        " | ".join(name for name, _key in _BUG_COLUMNS),
        f"Bugs: {bug_count}",
    ]
    for bug in bugs if isinstance(bugs, list) else []:
        if isinstance(bug, dict):
            bug_lines.append(
                f"{bug.get('id', '')}: {bug.get('title', '')}, {bug.get('severity', '')}, "
                f"{bug.get('status', '')}, age {bug.get('age', bug.get('age_days', ''))}, "
                f"linked test {bug.get('linked_tc_id', '')}, found in {bug.get('found_in', bug.get('found_in_env', ''))}"
            )
    if not bugs:
        bug_lines.append("No bugs.")
    actions = narrative.get("actions", score.get("recommended_actions", []))
    action_lines = [
        f"{action.get('owner', action.get('owner_role', ''))}: {action.get('text', '')}"
        for action in actions if isinstance(actions, list) and isinstance(action, dict)
    ]
    headline = narrative.get("headline", score.get("headline", ""))
    narrative_prose = _section_prose(narrative)
    rule_text = ", ".join(map(str, rule_ids)) if rule_ids else "Unavailable in the score object."
    source = score.get("source", "fixture")
    if source == "fixture":
        source = "dummy fixture"
    return {
        "report_title": "Story Health Report",
        "story_id": str(story_id),
        "title": str(title),
        "generated_at": generated_at,
        "source": str(source),
        "overall_rag": f"{rag}\nStory health: {health}\nRules: {rule_text}\n{narrative_prose}",
        "headline": str(headline),
        "ac_review": "\n".join(ac_lines),
        "ac_test_mapping": "\n".join(mapping_lines),
        "coverage_by_type": "\n".join(coverage_lines),
        "bugs": "\n".join(bug_lines),
        "recommended_actions": "\n".join(action_lines),
        "raw_story_ids": _id_list([str(story_id)]),
        "raw_ac_ids": _id_list([str(item) for item in ac_ids]),
        "raw_test_ids": _id_list([str(item) for item in test_ids]),
        "raw_bug_ids": _id_list([str(item) for item in bug_ids]),
    }


def _fill_template(template: str, values: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            raise ValueError(f"No score value is available for template field {key!r}.")
        return escape(values[key], quote=False)

    rendered = _PLACEHOLDER.sub(replace, template)
    unresolved = _PLACEHOLDER.search(rendered)
    if unresolved:
        raise ValueError(f"Unresolved template field {unresolved.group(1)!r}.")
    return rendered


class _NumberedCanvas(Canvas):
    """Uncompressed canvas that draws Page X of Y after the pages are known."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs["pageCompression"] = 0
        kwargs["invariant"] = 1
        super().__init__(*args, **kwargs)
        self._saved_page_states: list[dict] = []

    def showPage(self) -> None:
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        page_count = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_footer(page_count)
            Canvas.showPage(self)
        Canvas.save(self)

    def _draw_footer(self, page_count: int) -> None:
        page_width, _page_height = self._pagesize
        self.saveState()
        self.setStrokeColor(colors.HexColor("#d5dbe3"))
        self.setLineWidth(0.4)
        self.line(0.42 * inch, 0.36 * inch, page_width - 0.42 * inch, 0.36 * inch)
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#6b7280"))
        self.drawString(0.42 * inch, 0.2 * inch, "Story Guard  |  Story Health Report")
        self.drawRightString(
            page_width - 0.42 * inch,
            0.2 * inch,
            f"Page {self._pageNumber} of {page_count}",
        )
        self.restoreState()


def render_pdf(
    score: dict[str, Any],
    template_path: str | Path,
    out_path: str | Path,
    narrative: dict | None = None,
    record: dict | None = None,
) -> Path:
    """Render the provided score using the supplied eight-section template."""
    template_file = Path(template_path)
    try:
        rendered_markdown = _rendered_markdown(score, template_file, narrative, record)
    except (OSError, ValueError, KeyError, TypeError, RenderError) as error:
        raise RenderError(str(error)) from error

    output_file = Path(out_path)
    temporary = output_file.with_suffix(output_file.suffix + ".tmp")

    from story_guard.report_layout import MARGIN_X, PAGE_SIZE, example_flowables, layout_errors

    flowables = example_flowables(score, narrative, record)

    output_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        document = SimpleDocTemplate(
            str(temporary),
            pagesize=PAGE_SIZE,
            leftMargin=MARGIN_X,
            rightMargin=MARGIN_X,
            topMargin=0.34 * inch,
            bottomMargin=0.5 * inch,
            title=str(score.get("title") or (score.get("story") or {}).get("title", "Story Health Report")),
        )
        document.build(flowables, canvasmaker=_NumberedCanvas)
        if not temporary.is_file() or temporary.stat().st_size == 0:
            raise RenderError("PDF renderer produced an empty artifact")
        pdf_bytes = temporary.read_bytes()
        missing = layout_errors(pdf_bytes)
        if missing:
            raise RenderError(
                "PDF layout does not match the example report: " + ", ".join(missing)
            )
        temporary.replace(output_file)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return output_file


def main(argv: Sequence[str] | None = None) -> int:
    project_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Render a score JSON to PDF.")
    parser.add_argument(
        "--score",
        type=Path,
        default=project_root / "tests" / "data" / "sample_score.json",
    )
    parser.add_argument(
        "--template",
        type=Path,
        default=project_root / "templates" / "health_report.md",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=project_root / "artifacts" / "sample_health_report.pdf",
    )
    args = parser.parse_args(argv)

    try:
        score = json.loads(args.score.read_text(encoding="utf-8"))
        if not isinstance(score, dict):
            raise ValueError("The score JSON must contain an object at the top level.")
        output = render_pdf(score, args.template, args.output)
    except (OSError, ValueError, KeyError, TypeError, RenderError) as error:
        print(f"PDF render failed: {error}", file=sys.stderr)
        return 1

    print(f"PDF written to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
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
