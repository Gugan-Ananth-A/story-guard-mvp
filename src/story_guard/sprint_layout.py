"""Rollup flowables for a deterministic multi-story PDF."""

from __future__ import annotations

from html import escape
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

from story_guard.report_layout import CONTENT_WIDTH, LINE, MUTED, NAVY, _int_or_none, coverage_summary
from story_guard.score import is_closed_status


def rollup_flowables(entries: list[dict[str, Any]]) -> list[Any]:
    """Build a run-local rollup table; skipped inputs remain visible without detail pages."""
    title_style = ParagraphStyle(
        "SprintRollupTitle",
        fontName="Helvetica-Bold",
        fontSize=17,
        leading=21,
        textColor=NAVY,
        spaceAfter=4,
    )
    intro_style = ParagraphStyle(
        "SprintRollupIntro",
        fontName="Helvetica",
        fontSize=8,
        leading=10,
        textColor=MUTED,
        spaceAfter=8,
    )
    header_style = ParagraphStyle(
        "SprintRollupHeader",
        fontName="Helvetica-Bold",
        fontSize=7,
        leading=8.5,
        textColor=colors.white,
        alignment=TA_LEFT,
    )
    cell_style = ParagraphStyle(
        "SprintRollupCell",
        fontName="Helvetica",
        fontSize=7.5,
        leading=9,
        textColor=colors.HexColor("#243140"),
    )
    headers = (
        "Story ID",
        "Story title",
        "Health status",
        "Open bugs",
        "Coverage",
        "Coverage classification",
        "Run status",
    )
    rows = [[Paragraph(name, header_style) for name in headers]]
    for entry in entries:
        score = entry.get("score")
        if not isinstance(score, dict):
            values = (
                entry.get("story_id") or entry.get("source_label") or "Unknown",
                entry.get("title") or "Story details unavailable",
                "Unavailable",
                "Unavailable",
                "Unavailable",
                "Unavailable",
                f"Skipped: {entry.get('skip_reason') or 'not processed'}",
            )
        else:
            scenarios = score.get("scenarios")
            scenarios = scenarios if isinstance(scenarios, list) else []
            scenario_count = _int_or_none(score.get("scenario_count"))
            if scenario_count is None and isinstance(score.get("scenarios"), list):
                scenario_count = len(scenarios)
            coverage, classification = coverage_summary(scenarios, scenario_count or 0)
            open_bugs = _open_bug_count(score)
            values = (
                score.get("story_id") or "Unavailable",
                score.get("title") or "Untitled story",
                score.get("health") or "Unavailable",
                str(open_bugs) if open_bugs is not None else "Unavailable",
                coverage,
                classification,
                "Included",
            )
        rows.append([Paragraph(escape(str(value)), cell_style) for value in values])

    widths = [70, 160, 90, 54, 62, 114, CONTENT_WIDTH - 550]
    table = Table(rows, colWidths=widths, repeatRows=1, hAlign="LEFT")
    commands: list[tuple] = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("GRID", (0, 0), (-1, -1), 0.35, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]
    for row_index in range(1, len(rows)):
        if row_index % 2 == 0:
            commands.append(("BACKGROUND", (0, row_index), (-1, row_index), colors.HexColor("#f4f7fb")))
    table.setStyle(TableStyle(commands))
    return [
        Paragraph("Sprint Rollup", title_style),
        Paragraph(f"Stories in this run: {len(entries)}", intro_style),
        Spacer(1, 4),
        table,
    ]


def _open_bug_count(score: dict[str, Any]) -> int | None:
    count = _int_or_none(score.get("open_bug_count"))
    if count is not None:
        return count
    bugs = score.get("bugs")
    if isinstance(bugs, list):
        return sum(
            1
            for bug in bugs
            if isinstance(bug, dict) and not is_closed_status(bug.get("status"))
        )
    return None