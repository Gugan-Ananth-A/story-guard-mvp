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
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

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
    display_scenarios = (record or {}).get("scenarios", scenario_rows)
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


def _paragraph_text(text: str) -> str:
    markup = escape(text, quote=False)
    return markup.replace("\n", "<br/>").replace("↔", '<font name="Symbol">&#x2194;</font>')


def _uncompressed_canvas(*args: Any, **kwargs: Any) -> Canvas:
    kwargs["pageCompression"] = 0
    kwargs["invariant"] = 1
    return Canvas(*args, **kwargs)


def _page_footer(canvas: Canvas, document: SimpleDocTemplate) -> None:
    canvas.saveState()
    width, _height = letter
    canvas.setStrokeColor(colors.HexColor("#cbd2dc"))
    canvas.setLineWidth(0.5)
    canvas.line(0.65 * inch, 0.38 * inch, width - 0.65 * inch, 0.38 * inch)
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(colors.HexColor("#687587"))
    canvas.drawString(0.65 * inch, 0.23 * inch, "Story Health Report | Fixture analysis")
    canvas.drawRightString(width - 0.65 * inch, 0.23 * inch, f"Page {document.page}")
    canvas.restoreState()


def _styled_report_flowables(
    score: dict[str, Any], narrative: dict | None, record: dict | None
) -> list[Any]:
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ReportTitle", parent=styles["Title"], fontName="Helvetica-Bold",
        fontSize=21, leading=24, textColor=colors.white, alignment=0, spaceAfter=0,
    )
    section_style = ParagraphStyle(
        "ReportSection", parent=styles["Heading2"], fontName="Helvetica-Bold",
        fontSize=11, leading=13, textColor=colors.HexColor("#263d5b"),
        spaceBefore=5, spaceAfter=3, keepWithNext=True,
    )
    body_style = ParagraphStyle(
        "ReportBody", parent=styles["BodyText"], fontName="Helvetica",
        fontSize=7.8, leading=9.2, textColor=colors.HexColor("#263746"), spaceAfter=2,
    )
    small_style = ParagraphStyle(
        "ReportSmall", parent=body_style, fontSize=7, leading=8.5,
    )
    label_style = ParagraphStyle(
        "ReportLabel", parent=small_style, alignment=1, textColor=colors.HexColor("#4b5665"),
    )
    metric_style = ParagraphStyle(
        "ReportMetric", parent=styles["BodyText"], fontName="Helvetica-Bold",
        fontSize=15, leading=17, alignment=1, textColor=colors.HexColor("#263d5b"),
    )
    heading = lambda text: Paragraph(escape(text), section_style)
    body = lambda text: Paragraph(_paragraph_text(str(text)), body_style)
    small = lambda text: Paragraph(_paragraph_text(str(text)), small_style)

    values = _template_values(score, narrative, record)
    story_id = values["story_id"]
    title = values["title"]
    source = values["source"]
    generated_at = values["generated_at"]
    rag = str(score.get("rag", "Unavailable"))
    health = str(score.get("health", "Unavailable"))
    rag_color = {
        "red": colors.HexColor("#d94745"),
        "amber": colors.HexColor("#e4a332"),
        "green": colors.HexColor("#399b62"),
    }.get(rag.casefold(), colors.HexColor("#64748b"))

    meta = Paragraph(
        f"<b>{escape(str(title))}</b><br/>Story {escape(str(story_id))} &nbsp;|&nbsp; "
        f"{escape(source)}<br/>{escape(generated_at)}",
        ParagraphStyle(
            "ReportMeta", parent=small_style, textColor=colors.white,
            alignment=2, leading=10,
        ),
    )
    title_band = Table(
        [[Paragraph("Story Health Report", title_style), meta]],
        colWidths=[3.75 * inch, 3.1 * inch],
    )
    title_band.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#203b5d")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (0, 0), 10),
        ("RIGHTPADDING", (0, 0), (0, 0), 6),
        ("LEFTPADDING", (1, 0), (1, 0), 4),
        ("RIGHTPADDING", (1, 0), (1, 0), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))

    count_values = [
        ("SCENARIOS", score.get("scenario_count", 0), colors.HexColor("#5388b8")),
        ("TESTS", score.get("test_count", 0), colors.HexColor("#357a8a")),
        ("MAPPED", score.get("mapped_count", 0), colors.HexColor("#d99a28")),
        ("BUGS", score.get("bug_count", 0), colors.HexColor("#d9544d")),
        ("COVERAGE RAG", rag, rag_color),
        ("STORY HEALTH", health, colors.HexColor("#399b62") if health == "No open bugs" else colors.HexColor("#d9544d")),
    ]
    metrics = Table(
        [[Paragraph(str(value), metric_style) for _label, value, _color in count_values],
         [Paragraph(label, label_style) for label, _value, _color in count_values]],
        colWidths=[1.14 * inch] * len(count_values),
    )
    metric_style_colors = [
        ("LINEABOVE", (index, 0), (index, 0), 2.2, color)
        for index, (_label, _value, color) in enumerate(count_values)
    ]
    metrics.setStyle(TableStyle([
        *metric_style_colors,
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f2f4f7")),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#d3d8df")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, 0), 6),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 5),
    ]))

    flowables: list[Any] = [
        title_band,
        Spacer(1, 5),
        body("User story health, test coverage, and defect status."),
        metrics,
        heading("Title block"),
        body(f"Project: {_cell((record or {}).get('area')) or 'Not provided'}"),
        heading("Overall RAG"),
    ]
    rag_panel = Table(
        [[Paragraph(f"<b>{escape(rag)}</b>", ParagraphStyle(
            "RagValue", parent=body_style, fontName="Helvetica-Bold", fontSize=13,
            textColor=colors.white,
        )), Paragraph(
            f"<b>Story health:</b> {escape(health)} &nbsp;&nbsp; "
            f"<b>Rules:</b> {escape(', '.join(map(str, score.get('rule_ids', []))))}<br/>"
            f"{escape(values['headline'])}", body_style,
        )]],
        colWidths=[0.95 * inch, 5.9 * inch],
    )
    rag_panel.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), rag_color),
        ("BACKGROUND", (1, 0), (1, 0), colors.HexColor("#f2f4f7")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd2dc")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    flowables.append(rag_panel)
    narrative_text = _section_prose(narrative or {})
    if narrative_text:
        flowables.append(body(narrative_text))
    if score.get("note"):
        flowables.extend([Spacer(1, 4), small(f"Fixture note: {score['note']}")])

    flowables.extend([heading("AC review"), body(values["ac_review"])])
    ac_rows = [[small("AC ID"), small("Acceptance scenario"), small("Testable")]]
    source_scenarios = (record or {}).get("scenarios", score.get("scenarios", []))
    for scenario, score_row in zip(source_scenarios, score.get("scenarios", [])):
        ac_rows.append([
            small(scenario.get("ac_id", score_row.get("ac_id", ""))),
            small(scenario.get("text", "")),
            small("Yes" if scenario.get("testable") else "No"),
        ])
    flowables.append(_data_table(ac_rows, [0.7 * inch, 5.65 * inch, 0.5 * inch], header=True))
    flowables.extend([heading("AC ↔ test mapping")])
    mapping_rows = [[small("AC ID"), small("Explicit test IDs"), small("Gap")]]
    scored_rows = score.get("scenarios", [])
    for scenario in scored_rows:
        mapping_rows.append([
            small(scenario.get("ac_id", "")),
            small(", ".join(scenario.get("mapped_test_ids", [])) or "None"),
            small(scenario.get("gap", "No coverage")),
        ])
    flowables.append(_data_table(mapping_rows, [0.7 * inch, 2.15 * inch, 4.0 * inch], header=True))

    flowables.extend([
        heading("Coverage by type"),
        body(
            f"Total tests: {score.get('test_count', 0)} | "
            f"Mapped ACs: {score.get('mapped_count', 0)} | "
            f"Bugs: {score.get('bug_count', 0)}"
        ),
    ])
    coverage_counts = score.get("coverage_by_type", {})
    coverage_rows = [[small("Type"), small("Count")]] + [
        [small(label.replace("happy", "Positive").title()), small(count)]
        for label, count in coverage_counts.items()
    ]
    coverage_table = _data_table(coverage_rows, [3.1 * inch, 1.2 * inch], header=True)
    summary = Table(
        [[coverage_table, Paragraph(
            f"<b>{score.get('scenario_count', 0)} acceptance criteria</b><br/>"
            f"{score.get('adequate_count', 0)} adequately covered<br/>"
            f"{score.get('partial_count', 0)} with gaps<br/>"
            f"{score.get('none_count', 0)} not covered<br/><br/>"
            f"Adequate: {score.get('adequate_count', 0)}; "
            f"Partial: {score.get('partial_count', 0)}; "
            f"None: {score.get('none_count', 0)}<br/>"
            "Color key: Adequate, Partial, None.",
            ParagraphStyle("CoverageSummary", parent=body_style, leading=14),
        )]],
        colWidths=[4.55 * inch, 2.3 * inch],
    )
    summary.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (1, 0), (1, 0), colors.HexColor("#f2f4f7")),
        ("BOX", (1, 0), (1, 0), 0.5, colors.HexColor("#cbd2dc")),
        ("LEFTPADDING", (1, 0), (1, 0), 10),
        ("TOPPADDING", (1, 0), (1, 0), 8),
    ]))
    flowables.append(summary)
    flowables.extend([heading("Bugs")])
    bug_columns = ("Bug ID", "Title", "State", "Story ID", "TC ID", "Priority", "Severity", "Assigned To", "Found in Env", "Application", "Created")
    bug_rows = [[small(column) for column in bug_columns]]
    bugs = score.get("bugs", [])
    for bug in sorted(bugs, key=_bug_sort):
        bug_rows.append([small(bug.get(key, "")) for key in (
            "id", "title", "status", "linked_story_id", "linked_tc_id", "priority",
            "severity", "assigned_to", "found_in", "application", "created",
        )])
    if not bugs:
        bug_rows.append([small("No bugs.")] + [small("") for _ in bug_columns[1:]])
    flowables.append(_data_table(
        bug_rows,
        [0.55 * inch, 1.6 * inch, 0.62 * inch, 0.63 * inch, 0.5 * inch, 0.48 * inch,
         0.62 * inch, 0.75 * inch, 0.72 * inch, 0.67 * inch, 0.55 * inch],
        header=True,
        compact=True,
    ))
    flowables.extend([heading("Recommended actions")])
    action_rows = [[small("Owner"), small("Action")]]
    actions = (narrative or {}).get("actions", [])
    action_rows.extend([
        [small(action.get("owner", action.get("owner_role", ""))), small(action.get("text", ""))]
        for action in actions if isinstance(action, dict)
    ])
    flowables.append(_data_table(action_rows, [0.8 * inch, 6.05 * inch], header=True))
    flowables.extend([heading("Appendix")])
    appendix_rows = [
        [small("Story IDs"), small(values["raw_story_ids"])],
        [small("AC IDs"), small(values["raw_ac_ids"])],
        [small("Test IDs"), small(values["raw_test_ids"])],
        [small("Bug IDs"), small(values["raw_bug_ids"])],
    ]
    flowables.append(_data_table(appendix_rows, [0.9 * inch, 5.95 * inch], header=False, compact=True))
    return flowables


def _data_table(
    rows: list[list[Any]],
    widths: list[float],
    *,
    header: bool,
    compact: bool = False,
) -> Table:
    if header and rows:
        header_style = ParagraphStyle(
            "ReportTableHeader",
            parent=getSampleStyleSheet()["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=6.7 if compact else 7.2,
            leading=8,
            textColor=colors.white,
        )
        rows = [list(row) for row in rows]
        rows[0] = [
            Paragraph(cell.text, header_style) if isinstance(cell, Paragraph) else cell
            for cell in rows[0]
        ]
    table = Table(rows, colWidths=widths, repeatRows=1 if header else 0, hAlign="LEFT")
    style = [
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#cbd2dc")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3 if compact else 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3 if compact else 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2 if compact else 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2 if compact else 3),
    ]
    if header:
        style.extend([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#294765")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ])
        for row_index in range(1, len(rows)):
            if row_index % 2 == 0:
                style.append(("BACKGROUND", (0, row_index), (-1, row_index), colors.HexColor("#f1f4f7")))
    table.setStyle(TableStyle(style))
    return table


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

    flowables = _styled_report_flowables(score, narrative, record)

    output_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        document = SimpleDocTemplate(
            str(temporary),
            pagesize=letter,
            leftMargin=0.65 * inch,
            rightMargin=0.65 * inch,
            topMargin=0.48 * inch,
            bottomMargin=0.55 * inch,
            title=str(score.get("title") or (score.get("story") or {}).get("title", "Story Health Report")),
        )
        document.build(
            flowables,
            onFirstPage=_page_footer,
            onLaterPages=_page_footer,
            canvasmaker=_uncompressed_canvas,
        )
        if not temporary.is_file() or temporary.stat().st_size == 0:
            raise RenderError("PDF renderer produced an empty artifact")
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
