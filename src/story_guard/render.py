"""Render a score object through the frozen Markdown template into PDF."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from html import escape
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

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


def _template_values(score: dict[str, Any]) -> dict[str, str]:
    story = score["story"]
    appendix = score["appendix"]
    rag = score.get("rag")
    headline = score.get("headline")

    return {
        "story_id": str(story["id"]),
        "title": str(story["title"]),
        "generated_at": str(score["generated_at"]),
        "source": str(score["source"]),
        "overall_rag": str(rag) if rag is not None else "Unavailable in the score object.",
        "headline": str(headline) if headline is not None else "Headline unavailable in the score object.",
        "ac_review": _format_acceptance_criteria(score),
        "ac_test_mapping": _format_test_mappings(score),
        "coverage_by_type": _format_coverage(score),
        "bugs": _format_bugs(score),
        "recommended_actions": _format_actions(score),
        "raw_story_ids": _id_list(appendix.get("story_ids")),
        "raw_ac_ids": _id_list(appendix.get("ac_ids")),
        "raw_test_ids": _id_list(appendix.get("test_ids")),
        "raw_bug_ids": _id_list(appendix.get("bug_ids")),
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
    return markup.replace("↔", '<font name="Symbol">&#x2194;</font>')


def _uncompressed_canvas(*args: Any, **kwargs: Any) -> Canvas:
    kwargs["pageCompression"] = 0
    kwargs["invariant"] = 1
    return Canvas(*args, **kwargs)


def render_pdf(
    score: dict[str, Any],
    template_path: str | Path,
    out_path: str | Path,
) -> Path:
    """Render the provided score using the supplied Markdown template."""
    template_file = Path(template_path)
    if not template_file.is_file():
        raise FileNotFoundError(f"Report template not found: {template_file}")

    template = template_file.read_text(encoding="utf-8")
    rendered_markdown = _fill_template(template, _template_values(score))

    output_file = Path(out_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    styles = getSampleStyleSheet()
    heading_style = ParagraphStyle(
        "ReportSectionHeading",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=17,
        textColor=colors.HexColor("#263746"),
        spaceBefore=10,
        spaceAfter=5,
        keepWithNext=True,
    )
    body_style = ParagraphStyle(
        "ReportBody",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#263746"),
        spaceAfter=4,
    )

    flowables: list[Any] = []
    for line in rendered_markdown.splitlines():
        if not line.strip():
            flowables.append(Spacer(1, 4))
        elif line.startswith("## "):
            flowables.append(Paragraph(_paragraph_text(line[3:]), heading_style))
        else:
            flowables.append(Paragraph(_paragraph_text(line), body_style))

    document = SimpleDocTemplate(
        str(output_file),
        pagesize=letter,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.65 * inch,
        bottomMargin=0.65 * inch,
        title=str(score["story"]["title"]),
    )
    document.build(flowables, canvasmaker=_uncompressed_canvas)
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
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"PDF render failed: {error}", file=sys.stderr)
        return 1

    print(f"PDF written to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
