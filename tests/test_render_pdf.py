"""Validate ReportLab output from a deterministic hand-built score."""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from story_guard.render import RenderError, render_markdown, render_pdf

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_SCORE = PROJECT_ROOT / "tests" / "data" / "sample_score.json"
TEMPLATE = PROJECT_ROOT / "templates" / "health_report.md"


def load_sample_score() -> dict:
    return json.loads(SAMPLE_SCORE.read_text(encoding="utf-8"))


def hand_built_score() -> dict:
    return {
        "story_id": "SAMPLE-121213",
        "title": "Hand-built login report",
        "source": "fixture",
        "ac_field": "empty",
        "scenario_count": 8,
        "scenarios": [
            {
                "ac_id": f"AC-{index}",
                "text": f"Scenario {index}",
                "covered": False,
                "mapped_test_ids": [],
                "depth": "None",
                "gap": "No coverage",
                "row_status": "none",
            }
            for index in range(1, 9)
        ],
        "test_count": 18,
        "mapped_count": 0,
        "bug_count": 0,
        "open_bug_count": 0,
        "escaped_bug_count": 0,
        "adequate_count": 0,
        "partial_count": 0,
        "none_count": 8,
        "bugs": [],
        "coverage_by_type": {
            "happy": 0,
            "negative": 0,
            "edge": 0,
            "security": 0,
            "adhoc": 0,
            "unset": 18,
        },
        "rag": "Red",
        "health": "No open bugs",
        "health_band": "No open bugs",
        "rule_ids": ["SR-1", "SR-2", "SR-3"],
    }


def test_render_pdf_uses_score_and_contains_eight_sections(tmp_path: Path) -> None:
    output_path = tmp_path / "sample-health-report.pdf"
    markdown_path = tmp_path / "sample-health-report.md"
    score = hand_built_score()

    render_pdf(score, TEMPLATE, output_path)
    render_markdown(score, {}, TEMPLATE, markdown_path)

    assert output_path.is_file()
    pdf_bytes = output_path.read_bytes()
    assert len(pdf_bytes) > 100
    assert pdf_bytes.startswith(b"%PDF-")
    assert pdf_bytes.rstrip().endswith(b"%%EOF")
    assert len(re.findall(rb"/Type\s*/Page\b", pdf_bytes)) == 2
    headings = [
        "Title block",
        "Overall RAG",
        "AC review",
        "AC ↔ test mapping",
        "Coverage by type",
        "Bugs",
        "Recommended actions",
        "Appendix",
    ]
    for heading in headings:
        if heading != "AC ↔ test mapping":
            assert heading.encode("utf-8") in pdf_bytes
    markdown_headings = [
        line[3:]
        for line in markdown_path.read_text(encoding="utf-8").splitlines()
        if line.startswith("## ")
    ]
    assert markdown_headings == headings
    assert b"AC " in pdf_bytes and b"test mapping" in pdf_bytes
    assert pdf_bytes.count(b"AC review") == 1
    pdf_heading_anchors = [
        b"(Title block)",
        b"(Overall RAG)",
        b"(AC review)",
        b"(AC ) Tj",
        b"(Coverage by type)",
        b"(Bugs)",
        b"(Recommended actions)",
        b"(Appendix)",
    ]
    heading_positions = [pdf_bytes.find(anchor) for anchor in pdf_heading_anchors]
    assert all(position >= 0 for position in heading_positions)
    assert heading_positions == sorted(heading_positions)
    assert b"The AC field is empty." in pdf_bytes
    assert b"Scenarios: 8" in pdf_bytes
    assert b"Total tests: 18" in pdf_bytes
    assert b"Mapped ACs: 0" in pdf_bytes
    assert b"Bugs: 0" in pdf_bytes
    assert b"Total tests: 18 | Mapped ACs: 0 | Bugs: 0" in pdf_bytes
    assert b"&nbsp;" not in pdf_bytes
    assert b"Red" in pdf_bytes
    assert b"SR-1, SR-2, SR-3" in pdf_bytes
    assert b"Adequate: 0; Partial: 0; None: 8" in pdf_bytes
    assert b"Test coverage: 66%" not in pdf_bytes
    assert b"SCENARIOS" in pdf_bytes
    assert b"TESTS" in pdf_bytes
    assert b"COVERAGE RAG" in pdf_bytes
    assert b"STORY HEALTH" in pdf_bytes
    assert b"AC ID" in pdf_bytes
    assert b"Explicit test IDs" in pdf_bytes
    assert b"Gap" in pdf_bytes
    assert b"Found in Env" in pdf_bytes
    assert b"Page 1" in pdf_bytes
    assert b"#203b5d" not in pdf_bytes


def test_render_pdf_values_follow_the_passed_score(tmp_path: Path) -> None:
    score = hand_built_score()
    score["test_count"] = 27
    output_path = tmp_path / "changed-score.pdf"

    render_pdf(score, TEMPLATE, output_path)

    pdf_bytes = output_path.read_bytes()
    assert b"Total tests: 27" in pdf_bytes
    assert b"Total tests: 18" not in pdf_bytes


def test_missing_template_exits_nonzero_and_creates_no_pdf(tmp_path: Path) -> None:
    missing_template = tmp_path / "missing-health-report.md"
    output_path = tmp_path / "must-not-exist.pdf"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "story_guard.render",
            "--score",
            str(SAMPLE_SCORE),
            "--template",
            str(missing_template),
            "--output",
            str(output_path),
        ],
        capture_output=True,
        check=False,
        text=True,
        cwd=PROJECT_ROOT,
    )

    assert result.returncode != 0
    assert "template" in result.stderr.lower()
    assert "is missing" in result.stderr.lower()
    assert not output_path.exists()


def test_render_pdf_missing_template_leaves_no_partial_output(tmp_path: Path) -> None:
    output_path = tmp_path / "must-not-exist.pdf"
    with pytest.raises(RenderError, match="template .* is missing"):
        render_pdf(hand_built_score(), tmp_path / "missing.md", output_path)
    assert not output_path.exists()
    assert not output_path.with_suffix(".pdf.tmp").exists()
