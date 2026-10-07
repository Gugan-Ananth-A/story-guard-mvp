"""Validate ReportLab rendering from the static synthetic score."""

import json
import subprocess
import sys
from pathlib import Path

from story_guard.render import render_pdf

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_SCORE = PROJECT_ROOT / "tests" / "data" / "sample_score.json"
TEMPLATE = PROJECT_ROOT / "templates" / "health_report.md"


def load_sample_score() -> dict:
    return json.loads(SAMPLE_SCORE.read_text(encoding="utf-8"))


def test_render_pdf_includes_sample_counts_as_text(tmp_path: Path) -> None:
    output_path = tmp_path / "sample-health-report.pdf"

    render_pdf(load_sample_score(), TEMPLATE, output_path)

    assert output_path.is_file()
    pdf_bytes = output_path.read_bytes()
    assert pdf_bytes
    assert b"4 acceptance criteria" in pdf_bytes
    assert b"Explicitly mapped ACs: 1; uncovered ACs: 3." in pdf_bytes
    assert b"Test coverage: 66%" in pdf_bytes
    assert b"Total tests: 17" in pdf_bytes
    assert b"Open bugs: 1" in pdf_bytes
    assert b"AC " in pdf_bytes
    assert b"test mapping" in pdf_bytes


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
    assert "report template not found" in result.stderr.lower()
    assert not output_path.exists()
