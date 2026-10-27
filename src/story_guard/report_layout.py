"""Landscape story-health report in the shape of the example PDF.

The example is a portfolio. This agent scores one story, so the same
header, tiles, and four sections are filled from that story's score.
"""

from __future__ import annotations

import re
from datetime import datetime
from html import escape
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import CondPageBreak, KeepTogether, Paragraph, Spacer, Table, TableStyle

from story_guard.score import (
    ADHOC_WEIGHT,
    HEALTHY_COVERAGE_HIGH,
    HEALTHY_COVERAGE_LOW,
    NEGATIVE_WEIGHT,
    POSITIVE_WEIGHT,
    is_closed_status,
    is_unable_status,
    row_weighted_score,
    story_weighted_percent,
)

PAGE_SIZE = landscape(A4)
MARGIN_X = 0.42 * inch
# These match the SimpleDocTemplate margins in render.py. The frame also
# keeps ReportLab's default 6pt padding, so a flowable sees less than the
# margin box. The summary table is one row and cannot split, so its height
# has to stay inside that inner frame.
PAGE_TOP = 0.34 * inch
PAGE_BOTTOM = 0.5 * inch
FRAME_PAD = 6
CONTENT_WIDTH = PAGE_SIZE[0] - (2 * MARGIN_X)
_PORTFOLIO_HEADING = "1. Portfolio Summary"

NAVY = colors.HexColor("#1b365d")
BANNER = colors.HexColor("#16324f")
INK = colors.HexColor("#243140")
MUTED = colors.HexColor("#5c6b7a")
LINE = colors.HexColor("#d5dce3")
ZEBRA = colors.HexColor("#f4f7fb")
PANEL = colors.HexColor("#f7f9fb")
GREEN = colors.HexColor("#1f8a4c")
GREEN_BG = colors.HexColor("#e3f6e8")
AMBER = colors.HexColor("#c8891e")
AMBER_BG = colors.HexColor("#fff3d6")
RED = colors.HexColor("#d64545")
RED_BG = colors.HexColor("#fde8ea")
ORANGE = colors.HexColor("#e67e22")
YELLOW = colors.HexColor("#f1c40f")
BLUE = colors.HexColor("#2f6fed")
CLOSED_BG = colors.HexColor("#eceff3")

_LAYOUT_MARKERS = (
    "Portfolio Summary",
    "Story Health Overview",
    "Acceptance Criteria vs Test Case Coverage",
    "Bug Details",
    "Key Observations",
    "Gap colour key",
    "User Stories Assessed",
    "Story Guard",
    "Page 1 of",
)


def layout_errors(pdf_bytes: bytes) -> list[str]:
    """Names of example-report markers missing from an uncompressed PDF."""
    return [marker for marker in _LAYOUT_MARKERS if marker.encode("utf-8") not in pdf_bytes]


def example_flowables(
    score: dict[str, Any],
    narrative: dict | None,
    record: dict | None,
) -> list[Any]:
    """Build the example report from the score. The model only supplies prose."""
    facts = _facts(score, record)
    styles = _styles()
    story: list[Any] = [
        _banner(facts, styles),
        Spacer(1, 6),
        Paragraph(
            "PM / DM / Lead quick check: user story health, test coverage and defect status",
            styles["subtitle"],
        ),
        Spacer(1, 4),
        _kpi_row(facts, styles),
        Spacer(1, 8),
        Paragraph(_PORTFOLIO_HEADING, styles["section"]),
        *_summary_flowables(facts, narrative, styles),
        Paragraph(
            "Note: Bugs with status other than Resolved, Closed, Rejected / Unable to Reproduce are considered open bugs.",
            styles["note"],
        ),
        Spacer(1, 6),
        Paragraph("2. Story Health Overview", styles["section"]),
        _overview_table(facts, styles),
        Spacer(1, 8),
        CondPageBreak(3.1 * inch),
        KeepTogether([
            Paragraph("3. Acceptance Criteria vs Test Case Coverage", styles["section"]),
            Paragraph(
                "Coverage depth shows which scenario types are present. "
                f"Score weights positive coverage at {POSITIVE_WEIGHT}%, negative at {NEGATIVE_WEIGHT}%, "
                f"and adhoc at {ADHOC_WEIGHT}%. "
                "Missed test cases are the cases still not written for that criterion. "
                f"A score from {HEALTHY_COVERAGE_LOW}% to {HEALTHY_COVERAGE_HIGH}% is healthy.",
                styles["intro"],
            ),
            Spacer(1, 3),
            Paragraph("Gap colour key:", styles["label"]),
            _gap_key(styles),
            Spacer(1, 6),
            Paragraph(f"{facts['story_id']} - {facts['title']}", styles["story"]),
            _count_line(facts, styles),
            *(
                [Paragraph("The AC field is empty.", styles["body"])]
                if facts["ac_field"] == "empty"
                else []
            ),
            *(
                [Paragraph("No tests available.", styles["body"])]
                if facts["test_count"] == 0
                else []
            ),
            *(
                [Paragraph(f"Fixture note: {facts['note']}", styles["note"])]
                if facts["note"]
                else []
            ),
        ]),
    ]
    story.extend(
        [
            Spacer(1, 3),
            KeepTogether([_coverage_table(facts, styles)]),
            Spacer(1, 8),
            KeepTogether([
                Paragraph("4. Bug Details", styles["section"]),
                Paragraph(
                    f"{_display_count(facts['bug_count'])} bugs listed, sorted by priority (P1 first) and severity irrespective of user story. "
                    "Rows shaded grey are not open (Resolved / Closed / Rejected). "
                    "Bold environment = escaped defect (Production / UAT).",
                    styles["intro"],
                ),
                *(
                    [Paragraph("No open bugs", styles["body"])]
                    if facts["open_bug_count"] == 0
                    else []
                ),
                *(
                    [Paragraph("Open bug count unavailable.", styles["body"])]
                    if facts["open_bug_count"] is None
                    else []
                ),
                Spacer(1, 3),
                _bug_table(facts, styles),
            ]),
        ]
    )
    return story


def _styles() -> dict[str, ParagraphStyle]:
    base = dict(fontName="Helvetica", textColor=INK, alignment=TA_LEFT)
    return {
        "banner_title": ParagraphStyle(
            "BannerTitle", fontName="Helvetica-Bold", fontSize=20, leading=24,
            textColor=colors.white, alignment=TA_LEFT,
        ),
        "banner_meta": ParagraphStyle(
            "BannerMeta", fontName="Helvetica", fontSize=8, leading=11,
            textColor=colors.white, alignment=TA_RIGHT,
        ),
        "subtitle": ParagraphStyle(
            "Subtitle", fontName="Helvetica", fontSize=8, leading=10, textColor=MUTED,
        ),
        "section": ParagraphStyle(
            "SectionHead", fontName="Helvetica-Bold", fontSize=12.5, leading=15,
            textColor=NAVY, spaceBefore=2, spaceAfter=4, keepWithNext=True,
        ),
        "body": ParagraphStyle("Body", **base, fontSize=8, leading=10.5, spaceAfter=2),
        "intro": ParagraphStyle(
            "Intro", fontName="Helvetica", alignment=TA_LEFT, fontSize=7.5, leading=9.5, textColor=MUTED,
        ),
        "note": ParagraphStyle(
            "Note", fontName="Helvetica", alignment=TA_LEFT, fontSize=7, leading=9,
            textColor=MUTED, spaceBefore=2,
        ),
        "label": ParagraphStyle("Label", **base, fontSize=8, leading=10),
        "story": ParagraphStyle(
            "StoryHead", fontName="Helvetica-Bold", fontSize=9, leading=12,
            textColor=INK, spaceBefore=2, keepWithNext=True,
        ),
        "obs_head": ParagraphStyle(
            "ObsHead", fontName="Helvetica-Bold", fontSize=10, leading=13,
            textColor=NAVY, spaceAfter=3,
        ),
        "bullet": ParagraphStyle("Bullet", **base, fontSize=8, leading=10.5, leftIndent=2, spaceAfter=2),
        "kpi_value": ParagraphStyle(
            "KpiValue", fontName="Helvetica-Bold", fontSize=16, leading=18, alignment=TA_CENTER,
        ),
        "kpi_label": ParagraphStyle(
            "KpiLabel", fontName="Helvetica", fontSize=6.4, leading=8,
            alignment=TA_CENTER, textColor=MUTED,
        ),
        "th": ParagraphStyle(
            "Th", fontName="Helvetica-Bold", fontSize=6.6, leading=8,
            textColor=colors.white, alignment=TA_CENTER,
        ),
        "td": ParagraphStyle("Td", **base, fontSize=7, leading=8.6),
        "td_center": ParagraphStyle(
            "TdCenter", fontName="Helvetica", fontSize=7, leading=8.6,
            alignment=TA_CENTER, textColor=INK,
        ),
        "small_head": ParagraphStyle(
            "SmallHead", fontName="Helvetica-Bold", fontSize=8, leading=10,
            textColor=NAVY, spaceBefore=6, spaceAfter=2,
        ),
    }


def _facts(score: dict[str, Any], record: dict | None) -> dict[str, Any]:
    """Normalize the flat score and the older nested sample score."""
    if "story" in score and "story_id" not in score:
        story = score.get("story") or {}
        coverage = score.get("coverage") or {}
        bugs_obj = score.get("bugs") or {}
        raw_items = bugs_obj.get("items") if isinstance(bugs_obj, dict) else None
        bugs_available = isinstance(raw_items, list)
        items = [bug for bug in raw_items if isinstance(bug, dict)] if bugs_available else []
        raw_criteria = score.get("acceptance_criteria")
        criteria_available = isinstance(raw_criteria, list)
        criteria = raw_criteria if criteria_available else []
        mappings = {
            row.get("ac_id"): list(row.get("test_ids") or [])
            for row in score.get("test_mappings") or []
            if isinstance(row, dict)
        }
        scenarios = []
        for criterion in criteria:
            if not isinstance(criterion, dict):
                continue
            ac_id = str(criterion.get("id") or criterion.get("ac_id") or "")
            links = mappings.get(ac_id, [])
            scenarios.append(
                {
                    "ac_id": ac_id,
                    "depth": "None" if not links else "Mapped tests listed",
                    "gap": "No coverage" if not links else "Coverage depth is not on the score",
                    "row_status": "none" if not links else "partial",
                }
            )
        open_bugs = _int_or_none(bugs_obj.get("open_count")) if isinstance(bugs_obj, dict) else None
        if open_bugs is None and bugs_available:
            open_bugs = sum(1 for bug in items if not is_closed_status(bug.get("status")))
        test_count = _int_or_none(coverage.get("total_tests"))
        mapped_count = _int_or_none(coverage.get("mapped_ac_count"))
        bug_count = _int_or_none(bugs_obj.get("total_count")) if isinstance(bugs_obj, dict) else None
        if bug_count is None and bugs_available:
            bug_count = len(items)
        priorities = _priorities(items) if bugs_available else None
        reopened = _status_count(items, "reopened") if bugs_available else None
        unable = _unable_count(items) if bugs_available else None
        health = str(score.get("health") or "Unavailable")
        title = str(story.get("title") or "").strip()
        story_id = str(story.get("id") or "").strip()
        return {
            "story_id": story_id,
            "title": title or (f"Story {story_id}" if story_id else "Untitled story"),
            "project": str(score.get("source") or "Not provided"),
            "generated_on": _display_date(str(score.get("generated_at") or "")),
            "scenario_count": len(scenarios),
            "criteria_available": criteria_available,
            "scenarios": scenarios,
            "test_count": test_count,
            "mapped_count": mapped_count,
            "bug_count": bug_count,
            "bugs_available": bugs_available,
            "open_bug_count": open_bugs,
            "bugs": items,
            "open_bugs_by_priority": priorities,
            "reopened": reopened,
            "unable": unable,
            "adequate_count": 0,
            "partial_count": sum(1 for row in scenarios if row["row_status"] == "partial"),
            "none_count": sum(1 for row in scenarios if row["row_status"] == "none"),
            "health": health,
            "health_band": str(score.get("health_band") or ""),
            "coverage_label": _coverage_label(scenarios, len(scenarios)) if test_count is not None else "Unavailable",
            "ac_field": "",
            "note": "",
            "at_risk": _portfolio_flags(health, str(score.get("health_band") or ""))[0],
            "healthy": _portfolio_flags(health, str(score.get("health_band") or ""))[1],
        }

    raw_bugs = score.get("bugs")
    bugs_available = isinstance(raw_bugs, list)
    bugs = [bug for bug in raw_bugs if isinstance(bug, dict)] if bugs_available else []
    raw_scenarios = score.get("scenarios")
    criteria_available = isinstance(raw_scenarios, list)
    scenarios = [row for row in raw_scenarios if isinstance(row, dict)] if criteria_available else []
    health = str(score.get("health") or "Unavailable")
    band = str(score.get("health_band") or "")
    at_risk, healthy = _portfolio_flags(health, band)
    project = ""
    if isinstance(record, dict):
        project = str(record.get("area") or "").strip()
    generated = score.get("generated_at")
    if not isinstance(generated, str) or not generated.strip():
        generated = datetime.now().strftime("%Y-%m-%d %H:%M UTC")
    story_id = str(score.get("story_id") or "").strip()
    title = str(score.get("title") or "").strip()
    scenario_count = _int_or_none(score.get("scenario_count"))
    if scenario_count is None and criteria_available:
        scenario_count = len(scenarios)
    test_count = _int_or_none(score.get("test_count"))
    if test_count is None and isinstance(record, dict) and isinstance(record.get("tests"), list):
        test_count = len(record["tests"])
    bug_count = _int_or_none(score.get("bug_count"))
    if bug_count is None and bugs_available:
        bug_count = len(bugs)
    open_bug_count = _int_or_none(score.get("open_bug_count"))
    if open_bug_count is None and bugs_available:
        open_bug_count = sum(1 for bug in bugs if not is_closed_status(bug.get("status")))
    priorities = score.get("open_bugs_by_priority")
    if not isinstance(priorities, dict):
        priorities = _priorities(bugs) if bugs_available else None
    return {
        "story_id": story_id,
        "title": title or (f"Story {story_id}" if story_id else "Untitled story"),
        "project": project or "Not provided",
        "generated_on": _display_date(generated),
        "scenario_count": scenario_count,
        "criteria_available": criteria_available,
        "scenarios": scenarios,
        "test_count": test_count,
        "mapped_count": _int_or_none(score.get("mapped_count")),
        "bug_count": bug_count,
        "bugs_available": bugs_available,
        "open_bug_count": open_bug_count,
        "bugs": bugs,
        "open_bugs_by_priority": priorities,
        "reopened": _status_count(bugs, "reopened") if bugs_available else None,
        "unable": _unable_count(bugs) if bugs_available else None,
        "adequate_count": int(score.get("adequate_count") or 0),
        "partial_count": int(score.get("partial_count") or 0),
        "none_count": int(score.get("none_count") or 0),
        "health": health,
        "health_band": band,
        "coverage_label": _coverage_label(
            scenarios, scenario_count
        ),
        "ac_field": str(score.get("ac_field") or ""),
        "note": str(score.get("note") or "").strip(),
        "at_risk": at_risk,
        "healthy": healthy,
    }


def _banner(facts: dict[str, Any], styles: dict[str, ParagraphStyle]) -> Table:
    meta = Paragraph(
        f"Project: {escape(facts['project'])}<br/>"
        f"Generated on: {escape(facts['generated_on'])}<br/>"
        "Stories assessed: 1",
        styles["banner_meta"],
    )
    table = Table(
        [[Paragraph("Story Health Report", styles["banner_title"]), meta]],
        colWidths=[CONTENT_WIDTH * 0.58, CONTENT_WIDTH * 0.42],
    )
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BANNER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (0, 0), 12),
        ("RIGHTPADDING", (1, 0), (1, 0), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    return table


def _kpi_row(facts: dict[str, Any], styles: dict[str, ParagraphStyle]) -> Table:
    tiles = [
        (str(1), "User Stories Assessed", BLUE),
        (str(facts["at_risk"]), "Stories At Risk", RED),
        (str(facts["healthy"]), "Stories Healthy", GREEN),
        (facts["coverage_label"], "Avg Test Case Coverage", _coverage_color(facts["coverage_label"])),
        (_display_count(facts["open_bug_count"]), "Total Open Bugs", ORANGE),
        (_display_count(facts["reopened"]), "Reopened Bugs", RED),
        (_display_count(facts["unable"]), "Rejected / Unable to Reproduce", RED),
    ]
    width = CONTENT_WIDTH / len(tiles)
    values = []
    labels = []
    for value, label, color in tiles:
        value_style = ParagraphStyle(
            f"Kpi{label}", parent=styles["kpi_value"], textColor=color,
            fontSize=13 if value == "n/a" else 16,
        )
        values.append(Paragraph(escape(value), value_style))
        labels.append(Paragraph(escape(label), styles["kpi_label"]))
    table = Table([values, labels], colWidths=[width] * len(tiles))
    commands: list[tuple] = [
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("BOX", (0, 0), (-1, -1), 0.4, LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, 0), 6),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]
    for index, (_value, _label, color) in enumerate(tiles):
        commands.append(("LINEABOVE", (index, 0), (index, 0), 3, color))
    table.setStyle(TableStyle(commands))
    return table


_PANEL_OBSERVATION_LIMIT = 8
_BUG_DETAIL = re.compile(r"^Bug \d+ (?:description|repro steps)\b")


def _observations_after(lines: list[str], kept: list[str]) -> list[str]:
    """Lines that did not stay in the side panel, in their original order."""
    pending = list(kept)
    rest = []
    for line in lines:
        if pending and line == pending[0]:
            pending.pop(0)
            continue
        rest.append(line)
    return rest


def _split_observations(lines: list[str]) -> tuple[list[str], list[str]]:
    """Keep the summary panel to a page. Longer notes flow after it."""
    panel: list[str] = []
    notes: list[str] = []
    for line in lines:
        if (
            _BUG_DETAIL.match(line)
            or len(line) > 240
            or len(panel) >= _PANEL_OBSERVATION_LIMIT
        ):
            notes.append(line)
        else:
            panel.append(line)
    return panel, notes


def _inner_frame_height() -> float:
    """Height a flowable can use on an empty page, after frame padding."""
    return PAGE_SIZE[1] - PAGE_TOP - PAGE_BOTTOM - (2 * FRAME_PAD)


def _summary_height_limit(styles: dict[str, ParagraphStyle]) -> float:
    """Tallest summary row that still fits on a page with its section heading.

    ReportLab keeps the heading with the next flowable. The summary is one
    table row, so a row taller than the frame raises LayoutError.
    """
    heading = Paragraph(_PORTFOLIO_HEADING, styles["section"])
    _width, heading_height = heading.wrap(CONTENT_WIDTH, _inner_frame_height())
    return _inner_frame_height() - heading_height - heading.getSpaceAfter() - 2


def _summary_is_within(block: Table, limit: float) -> bool:
    _width, height = block.wrap(CONTENT_WIDTH, _inner_frame_height() * 4)
    return height <= limit


def _pack_summary_side(
    facts: dict[str, Any],
    styles: dict[str, ParagraphStyle],
    observations: list[str],
    actions: list[tuple[str, str]],
) -> tuple[list[str], list[tuple[str, str]]]:
    """Keep a prefix of the side panel that still fits in one frame."""
    limit = _summary_height_limit(styles)
    kept_observations: list[str] = []
    for index in range(1, len(observations) + 1):
        trial = observations[:index]
        if not _summary_is_within(_summary_block(facts, None, styles, trial, []), limit):
            break
        kept_observations = trial
    kept_actions: list[tuple[str, str]] = []
    for index in range(1, len(actions) + 1):
        trial = actions[:index]
        block = _summary_block(facts, None, styles, kept_observations, trial)
        if not _summary_is_within(block, limit):
            break
        kept_actions = trial
    return kept_observations, kept_actions


def _summary_flowables(
    facts: dict[str, Any],
    narrative: dict | None,
    styles: dict[str, ParagraphStyle],
) -> list[Any]:
    """The metric panel, then any review text that would not fit beside it."""
    observations = _observations(narrative, facts)
    actions = _actions(narrative)
    short, _long_notes = _split_observations(observations)
    panel, panel_actions = _pack_summary_side(facts, styles, short, actions)
    notes = _observations_after(observations, panel)
    flow: list[Any] = [
        _summary_block(facts, narrative, styles, panel, panel_actions)
    ]
    extra_actions = actions[len(panel_actions):]
    if extra_actions:
        flow.append(Paragraph("Recommended actions", styles["small_head"]))
        for owner, text in extra_actions:
            flow.append(_bullet(f"{owner}: {text}", styles["bullet"]))
    if not notes:
        return flow
    flow.append(Spacer(1, 6))
    flow.append(Paragraph("Review notes", styles["section"]))
    flow.append(
        Paragraph(
            "Bug descriptions, repro steps, and the acceptance-criteria review.",
            styles["intro"],
        )
    )
    for line in notes:
        flow.append(_bullet(line, styles["bullet"]))
    return flow


def _summary_block(
    facts: dict[str, Any],
    narrative: dict | None,
    styles: dict[str, ParagraphStyle],
    observation_lines: list[str] | None = None,
    action_lines: list[tuple[str, str]] | None = None,
) -> Table:
    priorities = facts["open_bugs_by_priority"]
    def priority_value(key: str) -> int | str:
        return _count(priorities.get(key)) if isinstance(priorities, dict) else "Unavailable"
    rows = [
        (_p("Metric", styles["th"]), _p("Value", styles["th"])),
        (_p("User Stories Assessed"), _p("1")),
        (_p("Healthy (User Stories count based on bugs Priority)"), _p(facts["healthy"])),
        (_p("At Risk (User Stories count based on bugs Priority)"), _p(facts["at_risk"])),
        (_p("Avg Test Case Coverage %"), _p(facts["coverage_label"])),
        (_p("Open Critical Bugs - P1"), _p(priority_value("P1"))),
        (_p("Open High Bugs - P2"), _p(priority_value("P2"))),
        (_p("Open Medium Bugs - P3"), _p(priority_value("P3"))),
        (_p("Open Low Bugs - P4"), _p(priority_value("P4"))),
        (_p("Reopened Bugs"), _p(_display_count(facts["reopened"]))),
        (_p("Rejected / Unable to Reproduce"), _p(_display_count(facts["unable"]))),
    ]
    left = Table(rows, colWidths=[268, 78])
    left_style: list[tuple] = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.3, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEBEFORE", (0, 5), (0, 5), 3.5, RED),
        ("LINEBEFORE", (0, 6), (0, 6), 3.5, ORANGE),
        ("LINEBEFORE", (0, 7), (0, 7), 3.5, YELLOW),
        ("LINEBEFORE", (0, 8), (0, 8), 3.5, GREEN),
    ]
    for index in range(1, len(rows)):
        if index % 2 == 0:
            left_style.append(("BACKGROUND", (0, index), (-1, index), ZEBRA))
    left.setStyle(TableStyle(left_style))

    right_bits: list[Any] = [Paragraph("Key Observations", styles["obs_head"])]
    lines = (
        observation_lines
        if observation_lines is not None
        else _observations(narrative, facts)
    )
    for line in lines:
        right_bits.append(_bullet(line, styles["bullet"]))
    actions = action_lines if action_lines is not None else _actions(narrative)
    if actions:
        right_bits.append(Paragraph("Recommended actions", styles["small_head"]))
        for owner, text in actions:
            right_bits.append(_bullet(f"{owner}: {text}", styles["bullet"]))
    right_bits.append(Paragraph("Health status", styles["small_head"]))
    right_bits.append(_legend(styles))
    right_bits.append(Paragraph("Coverage weightage", styles["small_head"]))
    right_bits.append(_weightage(styles))
    right = right_bits
    block = Table(
        [[left, right]],
        colWidths=[356, CONTENT_WIDTH - 356],
    )
    block.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (0, 0), 0),
        ("RIGHTPADDING", (0, 0), (0, 0), 8),
        ("LEFTPADDING", (1, 0), (1, 0), 10),
        ("RIGHTPADDING", (1, 0), (1, 0), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return block


def _legend(styles: dict[str, ParagraphStyle]) -> Table:
    items = [
        ("Critical", RED, colors.white, "Open P1 bug present (At Risk)"),
        ("High", ORANGE, colors.white, "Open P2 bug present (At Risk)"),
        ("Medium", YELLOW, colors.HexColor("#1f2933"), "Open P3 bug present (Healthy)"),
        ("Low", GREEN, colors.white, "Open P4 bug present (Healthy)"),
    ]
    label = ParagraphStyle("LegendLabel", parent=styles["td_center"], fontName="Helvetica-Bold", fontSize=7)
    rule = ParagraphStyle("LegendRule", parent=styles["td"], fontSize=7.5)
    rows = []
    colors_for_rows = []
    inks = []
    for name, fill, ink, description in items:
        named = ParagraphStyle(f"Legend{name}", parent=label, textColor=ink)
        rows.append([Paragraph(name, named), Paragraph(description, rule)])
        colors_for_rows.append(fill)
        inks.append(ink)
    table = Table(rows, colWidths=[68, 250])
    commands: list[tuple] = [
        ("GRID", (0, 0), (-1, -1), 0.3, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("BACKGROUND", (0, 0), (1, -1), PANEL),
    ]
    for index, fill in enumerate(colors_for_rows):
        commands.append(("BACKGROUND", (0, index), (0, index), fill))
    table.setStyle(TableStyle(commands))
    return table


def _weightage(styles: dict[str, ParagraphStyle]) -> Table:
    """Weights used by the average test-case score, in the same shape as health status."""
    items = [
        ("Positive", f"{POSITIVE_WEIGHT}%", BLUE, colors.white, "Weight of positive scenario coverage"),
        ("Negative", f"{NEGATIVE_WEIGHT}%", ORANGE, colors.white, "Weight of negative scenario coverage"),
        ("Adhoc", f"{ADHOC_WEIGHT}%", colors.HexColor("#5c6b7a"), colors.white, "Weight of adhoc scenario coverage"),
        (
            "Healthy",
            f"{HEALTHY_COVERAGE_LOW}% to {HEALTHY_COVERAGE_HIGH}%",
            GREEN,
            colors.white,
            "Weighted score in this range",
        ),
    ]
    label = ParagraphStyle(
        "WeightLabel", parent=styles["td_center"], fontName="Helvetica-Bold", fontSize=7,
    )
    rule = ParagraphStyle("WeightRule", parent=styles["td"], fontSize=7.5)
    rows = []
    fills = []
    for name, value, fill, ink, description in items:
        named = ParagraphStyle(f"Weight{name}", parent=label, textColor=ink)
        rows.append([
            Paragraph(f"{name} {value}", named),
            Paragraph(description, rule),
        ])
        fills.append(fill)
    table = Table(rows, colWidths=[118, 200])
    commands: list[tuple] = [
        ("GRID", (0, 0), (-1, -1), 0.3, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("BACKGROUND", (0, 0), (1, -1), PANEL),
    ]
    for index, fill in enumerate(fills):
        commands.append(("BACKGROUND", (0, index), (0, index), fill))
    table.setStyle(TableStyle(commands))
    return table


def _coverage_color(label: str) -> colors.Color:
    """Green inside the healthy band, amber below it, blue above it."""
    if not isinstance(label, str) or not label.endswith("%"):
        return BLUE
    try:
        value = int(label[:-1])
    except ValueError:
        return BLUE
    if HEALTHY_COVERAGE_LOW <= value <= HEALTHY_COVERAGE_HIGH:
        return GREEN
    if value < HEALTHY_COVERAGE_LOW:
        return AMBER
    return BLUE


def _overview_table(facts: dict[str, Any], styles: dict[str, ParagraphStyle]) -> Table:
    priorities = facts["open_bugs_by_priority"] if isinstance(facts["open_bugs_by_priority"], dict) else {}
    header = [
        "User Story ID", "Story Title", "Total TC", "Total Bugs",
        "Open Bugs (Based on Priority)", "", "", "",
        "Reopened Bugs", "Rejected / Unable to Reproduce", "Test Case Coverage %", "User Story Health",
    ]
    sub = ["", "", "", "", "P1", "P2", "P3", "P4", "", "", "", ""]
    fill, ink = _health_colors(facts["health"])
    health_style = ParagraphStyle(
        "OverviewHealth", parent=styles["td_center"], textColor=ink, fontName="Helvetica-Bold",
    )
    data_row = [
        facts["story_id"],
        facts["title"],
        _display_count(facts["test_count"]),
        _display_count(facts["bug_count"]),
        str(_count(priorities.get("P1"))) if isinstance(priorities, dict) else "Unavailable",
        str(_count(priorities.get("P2"))) if isinstance(priorities, dict) else "Unavailable",
        str(_count(priorities.get("P3"))) if isinstance(priorities, dict) else "Unavailable",
        str(_count(priorities.get("P4"))) if isinstance(priorities, dict) else "Unavailable",
        _display_count(facts["reopened"]),
        _display_count(facts["unable"]),
        facts["coverage_label"],
        facts["health"],
    ]
    rows = [
        [_p(text, styles["th"]) for text in header],
        [_p(text, styles["th"]) for text in sub],
        [
            _p(data_row[0], styles["td_center"]),
            _p(data_row[1], styles["td"]),
            *[_p(value, styles["td_center"]) for value in data_row[2:11]],
            Paragraph(escape(data_row[11]), health_style),
        ],
    ]
    widths = [72, 148, 46, 46, 32, 32, 32, 32, 62, 78, 78, CONTENT_WIDTH - 658]
    table = Table(rows, colWidths=widths, repeatRows=2)
    commands: list[tuple] = [
        ("BACKGROUND", (0, 0), (-1, 1), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 1), colors.white),
        ("SPAN", (0, 0), (0, 1)),
        ("SPAN", (1, 0), (1, 1)),
        ("SPAN", (2, 0), (2, 1)),
        ("SPAN", (3, 0), (3, 1)),
        ("SPAN", (4, 0), (7, 0)),
        ("SPAN", (8, 0), (8, 1)),
        ("SPAN", (9, 0), (9, 1)),
        ("SPAN", (10, 0), (10, 1)),
        ("SPAN", (11, 0), (11, 1)),
        ("BACKGROUND", (11, 2), (11, 2), fill),
        ("GRID", (0, 0), (-1, -1), 0.3, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("BACKGROUND", (0, 2), (10, 2), colors.white),
    ]
    table.setStyle(TableStyle(commands))
    return table


def _coverage_table(facts: dict[str, Any], styles: dict[str, ParagraphStyle]) -> Table:
    rows = [[
        _p("AC ID", styles["th"]),
        _p("Coverage Depth (AI)", styles["th"]),
        _p("Coverage Gap (AI)", styles["th"]),
        _p("Score", styles["th"]),
        _p("Missed test cases", styles["th"]),
    ]]
    paints: list[tuple[int, colors.Color, int | None]] = []
    if not facts["scenarios"]:
        empty_text = (
            "No acceptance criteria provided."
            if facts["criteria_available"] and facts["scenario_count"] == 0
            else "Acceptance criteria unavailable."
        )
        rows.append([_p(empty_text, styles["td"]), "", "", "", ""])
    for scenario in facts["scenarios"]:
        depth, gap, status = _depth_and_gap(scenario)
        score = row_weighted_score(scenario) if isinstance(scenario, dict) else None
        rows.append([
            _p(scenario.get("ac_id", ""), styles["td_center"]),
            _p(depth, styles["td"]),
            _p(gap, styles["td"]),
            _p(_score_text(scenario), styles["td"]),
            _p(_missed_text(scenario), styles["td"]),
        ])
        paints.append((len(rows) - 1, _gap_color(status), score))
    ac_width = 64
    score_width = 96
    depth_width = 136
    gap_width = 128
    missed_width = CONTENT_WIDTH - (ac_width + depth_width + gap_width + score_width)
    table = Table(
        rows,
        colWidths=[ac_width, depth_width, gap_width, score_width, missed_width],
        repeatRows=1,
    )
    commands: list[tuple] = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("GRID", (0, 0), (-1, -1), 0.3, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    if not facts["scenarios"]:
        commands.append(("SPAN", (0, 1), (-1, 1)))
    for index, color, score in paints:
        commands.append(("BACKGROUND", (1, index), (2, index), color))
        if isinstance(score, int) and HEALTHY_COVERAGE_LOW <= score <= HEALTHY_COVERAGE_HIGH:
            commands.append(("BACKGROUND", (3, index), (3, index), GREEN_BG))
    table.setStyle(TableStyle(commands))
    return table


def _score_text(row: dict) -> str:
    """Weighted score, then each scenario count on its own line."""
    score = row_weighted_score(row)
    counts = row.get("scenario_counts") if isinstance(row.get("scenario_counts"), dict) else {}
    lines = [f"{score}%"]
    for key, label in (("positive", "Positive"), ("negative", "Negative"), ("adhoc", "Ad-hoc")):
        item = counts.get(key) if isinstance(counts, dict) else None
        if not isinstance(item, dict):
            continue
        lines.append(f"{label} {item.get('covered', 0)}/{item.get('total', 0)}")
    return "\n".join(lines)


def _missed_text(row: dict) -> str:
    """One line per missed case, with a blank line between scenario types."""
    missed = row.get("missed_tests")
    if isinstance(missed, list):
        lines = [str(item).strip() for item in missed if str(item).strip()]
        if not lines:
            return "None"
        blocks: list[list[str]] = []
        current: list[str] = []
        for line in lines:
            if line.startswith("- "):
                current.append(line)
                continue
            if current:
                blocks.append(current)
            current = [line]
        if current:
            blocks.append(current)
        return "\n\n".join("\n".join(block) for block in blocks)
    status = str(row.get("row_status") or "")
    gap = str(row.get("gap") or "").strip()
    if status == "none":
        return "No coverage"
    if not gap or gap == "Adequate":
        return "None"
    return gap


def _bug_table(facts: dict[str, Any], styles: dict[str, ParagraphStyle]) -> Table:
    headers = [
        "Bug ID", "Title", "State", "Story ID", "TC ID", "Priority",
        "Severity", "Assigned To", "Found in Env.", "Application", "Created",
    ]
    rows: list[list[Any]] = [[_p(header, styles["th"]) for header in headers]]
    bugs = sorted(facts["bugs"], key=_bug_rank)
    chip_rows: list[tuple[int, colors.Color, colors.Color]] = []
    closed_rows: list[int] = []
    if not facts["bugs_available"] and facts["bug_count"] != 0:
        rows.append([_p("Bug information unavailable.", styles["td"])] + [_p("", styles["td"]) for _ in headers[1:]])
    elif not bugs:
        rows.append([_p("No bugs.", styles["td"])] + [_p("", styles["td"]) for _ in headers[1:]])
    for bug in bugs:
        priority = _priority_label(bug)
        fill, ink = _priority_colors(priority)
        priority_style = ParagraphStyle(
            f"Pri{len(rows)}", parent=styles["td_center"], textColor=ink, fontName="Helvetica-Bold",
        )
        found = str(bug.get("found_in") or bug.get("found_in_env") or "")
        rows.append([
            _p(bug.get("id", ""), styles["td_center"]),
            _p(bug.get("title", ""), styles["td"]),
            _p(bug.get("status", ""), styles["td_center"]),
            _p(bug.get("linked_story_id", ""), styles["td_center"]),
            _p(bug.get("linked_tc_id", ""), styles["td_center"]),
            Paragraph(escape(priority), priority_style),
            _p(bug.get("severity", ""), styles["td_center"]),
            _p(bug.get("assigned_to", ""), styles["td"]),
            _env_cell(found, styles["td_center"]),
            _p(bug.get("application", ""), styles["td"]),
            _p(bug.get("created", ""), styles["td_center"]),
        ])
        if priority:
            chip_rows.append((len(rows) - 1, fill, ink))
        if _is_closed(bug):
            closed_rows.append(len(rows) - 1)
    widths = [52, 168, 58, 78, 62, 48, 52, 78, 62, 62, CONTENT_WIDTH - 720]
    table = Table(rows, colWidths=widths, repeatRows=1)
    commands: list[tuple] = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("GRID", (0, 0), (-1, -1), 0.25, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]
    if (not facts["bugs_available"] and facts["bug_count"] != 0) or not bugs:
        commands.append(("SPAN", (0, 1), (-1, 1)))
    for index in closed_rows:
        commands.append(("BACKGROUND", (0, index), (-1, index), CLOSED_BG))
    for index, fill, _ink in chip_rows:
        commands.append(("BACKGROUND", (5, index), (5, index), fill))
    table.setStyle(TableStyle(commands))
    return table


def _count_line(facts: dict[str, Any], styles: dict[str, ParagraphStyle]) -> Paragraph:
    return Paragraph(
        f"{_display_count(facts['scenario_count'])} acceptance criteria | "
        f'<font color="#1f8a4c">{facts["adequate_count"]} adequately covered</font> | '
        f'<font color="#c8891e">{facts["partial_count"]} with gaps</font> | '
        f'<font color="#d64545">{facts["none_count"]} not covered</font>',
        styles["body"],
    )
def _display_count(value: object) -> str:
    count = _int_or_none(value)
    return str(count) if count is not None else "Unavailable"


def _gap_key(styles: dict[str, ParagraphStyle]) -> Table:
    label = ParagraphStyle("KeyLabel", parent=styles["label"], fontSize=7.5)
    table = Table(
        [[
            _swatch(GREEN_BG), Paragraph("Adequate", label),
            _swatch(AMBER_BG), Paragraph("Partial / missing scenarios", label),
            _swatch(RED_BG), Paragraph("No coverage at all", label),
        ]],
        colWidths=[14, 78, 14, 160, 14, 130],
    )
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))
    return table


def _swatch(color: colors.Color) -> Table:
    box = Table([[""]], colWidths=[9], rowHeights=[9])
    box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), color),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return box


_HEALTH_PREFIX = re.compile(r"(?i)^story health\s*(?:is|:|-)\s*[^.!\n]*[.!]?\s*")


def _observations(narrative: dict | None, facts: dict[str, Any]) -> list[str]:
    """Key observations always lead with the story health status."""
    health = str(facts.get("health") or "Unavailable").strip() or "Unavailable"
    lines = _narrative_lines(narrative)
    if not lines:
        lines = [
            (
                f"{_display_count(facts['scenario_count'])} acceptance criteria, "
                f"{facts['adequate_count']} adequately covered, "
                f"{facts['partial_count']} with gaps, {facts['none_count']} not covered."
            ),
            f"{_display_count(facts['test_count'])} tests and {_display_count(facts['mapped_count'])} mapped.",
            f"{_display_count(facts['bug_count'])} bugs, with {_display_count(facts['open_bug_count'])} open.",
        ]
    kept = []
    for line in lines:
        remainder = _HEALTH_PREFIX.sub("", line).strip()
        if remainder:
            kept.append(remainder)
    return [f"Story health - {health}", *kept]


def _narrative_lines(narrative: dict | None) -> list[str]:
    if not isinstance(narrative, dict):
        return []
    supplied = narrative.get("observations")
    if isinstance(supplied, list):
        lines = [item.strip() for item in supplied if isinstance(item, str) and item.strip()]
        if lines:
            return lines
    sections = narrative.get("sections")
    if not isinstance(sections, list):
        return []
    prose = []
    for section in sections:
        if isinstance(section, str) and section.strip():
            prose.append(section.strip())
        elif isinstance(section, dict):
            text = str(section.get("prose") or section.get("text") or "").strip()
            if text:
                prose.append(text)
    return prose


def _actions(narrative: dict | None) -> list[tuple[str, str]]:
    if not isinstance(narrative, dict) or not isinstance(narrative.get("actions"), list):
        return []
    found = []
    for action in narrative["actions"]:
        if not isinstance(action, dict):
            continue
        owner = str(action.get("owner") or action.get("owner_role") or "").strip()
        text = str(action.get("text") or action.get("action") or "").strip()
        if owner and text:
            found.append((owner, text))
    return found


def _depth_and_gap(row: dict) -> tuple[str, str, str]:
    """Paint coverage depth and the remaining gap. The score column carries the counts."""
    status = str(row.get("row_status") or "")
    gap = str(row.get("gap") or "")
    depth = str(row.get("depth") or "")
    if status == "none":
        return "None", "No coverage", "none"
    if status == "adequate":
        return _numbered(depth), "Adequate", "adequate"
    return _numbered(depth), _numbered(gap), "partial"


def _numbered(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ""
    numbered = []
    for index, line in enumerate(lines, start=1):
        if line[0].isdigit():
            numbered.append(line)
        else:
            numbered.append(f"{index}.{line}")
    return "\n".join(numbered)


def _gap_color(status: str) -> colors.Color:
    if status == "adequate":
        return GREEN_BG
    if status == "partial":
        return AMBER_BG
    return RED_BG


def _bullet(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(f'<font name="ZapfDingbats" size="5">l</font>  {escape(text)}', style)


def _p(text: object, style: ParagraphStyle | None = None) -> Paragraph:
    if style is None:
        style = ParagraphStyle("Plain", fontName="Helvetica", fontSize=7.5, leading=9.5, textColor=INK)
    raw = "" if text is None else str(text)
    return Paragraph(escape(raw).replace("\n", "<br/>"), style)


def _env_cell(value: str, style: ParagraphStyle) -> Paragraph:
    safe = escape(value)
    lowered = value.casefold()
    if "uat" in lowered or "prod" in lowered:
        safe = f"<b>{safe}</b>"
    return Paragraph(safe, style)


def _portfolio_flags(health: str, band: str) -> tuple[int, int]:
    label = health.strip().casefold()
    band_label = band.strip().casefold()
    if label in {"critical", "high"} or band_label == "at risk":
        return 1, 0
    if label in {"medium", "low"} or band_label == "healthy":
        return 0, 1
    return 0, 0


def _health_colors(health: str) -> tuple[colors.Color, colors.Color]:
    label = health.strip().casefold()
    if label == "critical":
        return RED, colors.white
    if label == "high":
        return ORANGE, colors.white
    if label == "medium":
        return YELLOW, colors.HexColor("#1f2933")
    if label in {"low", "no open bugs"}:
        return GREEN, colors.white
    return colors.HexColor("#64748b"), colors.white


def _priority_colors(priority: str) -> tuple[colors.Color, colors.Color]:
    if priority == "P1":
        return RED, colors.white
    if priority == "P2":
        return ORANGE, colors.white
    if priority == "P3":
        return YELLOW, colors.HexColor("#1f2933")
    if priority == "P4":
        return GREEN, colors.white
    return colors.white, INK


def _priority_label(bug: dict) -> str:
    for key in ("priority", "severity"):
        text = str(bug.get(key) or "").upper()
        for label in ("P1", "P2", "P3", "P4"):
            if label in text:
                return label
    return ""


def _bug_rank(bug: dict) -> tuple:
    order = {"P1": 0, "P2": 1, "P3": 2, "P4": 3}
    severity = str(bug.get("severity") or "").strip().casefold()
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(severity, 9)
    return (order.get(_priority_label(bug), 9), severity_order, str(bug.get("id") or ""))


def _priorities(bugs: list) -> dict[str, int]:
    counts = {"P1": 0, "P2": 0, "P3": 0, "P4": 0}
    for bug in bugs:
        if not isinstance(bug, dict) or is_closed_status(bug.get("status")):
            continue
        label = _priority_label(bug)
        if label:
            counts[label] += 1
    return counts


def _unable_count(bugs: list) -> int:
    return sum(
        1
        for bug in bugs
        if isinstance(bug, dict) and is_unable_status(bug.get("status"))
    )


def _status_count(bugs: list, status: str) -> int:
    return sum(
        1
        for bug in bugs
        if isinstance(bug, dict) and str(bug.get("status") or "").strip().casefold() == status
    )


def _is_closed(bug: dict) -> bool:
    return is_closed_status(bug.get("status"))


def _count(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value


_BUCKET_LINES = (
    "Positive scenarios are covered",
    "Negative scenarios are covered",
    "Adhoc scenarios are covered",
)


def _coverage_label(scenarios: list, scenario_count: int) -> str:
    """Average of the per-criterion weighted scores."""
    percentage, _classification = coverage_summary(scenarios, scenario_count)
    return percentage


def coverage_summary(scenarios: list, scenario_count: int) -> tuple[str, str]:
    """Return the weighted coverage percent and the bucket classification."""
    total = scenario_count if isinstance(scenario_count, int) and scenario_count > 0 else 0
    if total <= 0:
        return "n/a", "none"
    points = 0
    for row in scenarios:
        if not isinstance(row, dict):
            continue
        raw = row.get("buckets_present")
        if isinstance(raw, int) and not isinstance(raw, bool):
            points += raw
            continue
        depth = str(row.get("depth") or "")
        points += sum(1 for line in _BUCKET_LINES if line in depth)
    denom = total * 3
    percentage = story_weighted_percent(scenarios, total)
    if points == 0:
        classification = "none"
    elif points >= denom:
        classification = "adequate"
    else:
        classification = "partial"
    return percentage, classification


def _int_or_none(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def _display_date(value: str) -> str:
    text = value.strip()
    if not text:
        return datetime.now().strftime("%d %b %Y")
    for fmt in ("%Y-%m-%d %H:%M UTC", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).strftime("%d %b %Y")
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).strftime("%d %b %Y")
    except ValueError:
        return text
