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
LIVE_MAPPER_PROMPT = PROJECT_ROOT / "prompts" / "live_map_v1.md"
SYNTHETIC_STORY = PROJECT_ROOT / "tests" / "data" / "synthetic_story.json"


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
    assert len(re.findall(rb"/Type\s*/Page\b", pdf_bytes)) >= 1
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
    markdown_headings = [
        line[3:]
        for line in markdown_path.read_text(encoding="utf-8").splitlines()
        if line.startswith("## ")
    ]
    assert markdown_headings == headings
    pdf_markers = [
        b"Portfolio Summary",
        b"Story Health Overview",
        b"Acceptance Criteria vs Test Case Coverage",
        b"Bug Details",
        b"Key Observations",
        b"Gap colour key",
        b"User Stories Assessed",
        b"No coverage",
        b"No coverage at all",
        b"The AC field is empty.",
        b"8 acceptance criteria",
        b"0 adequately covered",
        b"8 not covered",
        b"No bugs.",
        b"Story Guard",
        b"Page 1 of",
    ]
    positions = [pdf_bytes.find(marker) for marker in pdf_markers]
    assert all(position >= 0 for position in positions)
    assert pdf_bytes.find(b"1. Portfolio Summary") < pdf_bytes.find(b"2. Story Health Overview")
    assert pdf_bytes.find(b"2. Story Health Overview") < pdf_bytes.find(
        b"3. Acceptance Criteria vs Test Case Coverage"
    )
    assert pdf_bytes.find(b"3. Acceptance Criteria vs Test Case Coverage") < pdf_bytes.find(
        b"4. Bug Details"
    )
    assert b"&nbsp;" not in pdf_bytes
    assert b"Test coverage: 66%" not in pdf_bytes
    assert b"Found in Env" in pdf_bytes
    assert b"#203b5d" not in pdf_bytes


def test_render_pdf_values_follow_the_passed_score(tmp_path: Path) -> None:
    score = hand_built_score()
    score["test_count"] = 27
    output_path = tmp_path / "changed-score.pdf"

    render_pdf(score, TEMPLATE, output_path)

    pdf_bytes = output_path.read_bytes()
    assert b"27 tests and 0 mapped." in pdf_bytes
    assert b"18 tests and 0 mapped." not in pdf_bytes


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


def _pdf_page_texts(pdf_bytes: bytes) -> list[str]:
    """Literal strings on each page of an uncompressed ReportLab PDF, in page order."""
    kids = re.search(rb"/Kids\s*\[([^\]]+)\]", pdf_bytes)
    assert kids is not None
    page_ids = [int(number) for number in re.findall(rb"(\d+)\s+0\s+R", kids.group(1))]
    pages = []
    for page_id in page_ids:
        page = re.search(rf"{page_id} 0 obj\s*<<(.*?)>>\s*endobj".encode(), pdf_bytes, re.S)
        assert page is not None
        contents = re.search(rb"/Contents\s+(\d+)\s+0\s+R", page.group(1))
        assert contents is not None
        stream_id = contents.group(1).decode()
        stream = re.search(
            rf"{stream_id} 0 obj\s*<<.*?>>\s*stream\r?\n(.*?)endstream".encode(),
            pdf_bytes,
            re.S,
        )
        assert stream is not None
        parts = []
        for raw in re.findall(rb"\((?:\\.|[^\\)])*\)", stream.group(1)):
            text = raw[1:-1].replace(rb"\(", b"(").replace(rb"\)", b")").replace(rb"\\", b"\\")
            parts.append(text.decode("latin1"))
        pages.append("\n".join(parts))
    return pages


def _live_like_record() -> dict:
    """12 scored criteria and the 18-case suite that overflowed page 2 of artifacts/121213.pdf."""
    record = json.loads((PROJECT_ROOT / "fixtures" / "FIX-121213.json").read_text(encoding="utf-8"))
    record["acceptance_criteria"] = [
        {"ac_id": f"AC-{index:02d}", "text": f"Criterion {index}"} for index in range(1, 13)
    ]
    record["acceptance_criteria_raw"] = "present"
    record["note"] = ""
    for test in record["tests"]:
        test["suite_id"] = "121215"
        test["suite_name"] = "Story Guard - AI Agent"
        test["suite_type"] = "staticTestSuite"
        test["plan_id"] = "121214"
    from story_guard.score import apply_explicit_links

    record["tests"] = apply_explicit_links(record["tests"])
    return record


def test_report_omits_the_test_suite_and_covers_ac_11(tmp_path: Path) -> None:
    from story_guard.score import score_health

    record = _live_like_record()
    output_path = tmp_path / "no-suite.pdf"
    render_pdf(score_health(record), TEMPLATE, output_path, narrative={}, record=record)

    pages = _pdf_page_texts(output_path.read_bytes())
    text = "\n".join(pages)
    assert "Test suite" not in text
    assert "Suite 121215" not in text
    assert "Story health - No open bugs" in text
    assert "50%" in text
    assert "Coverage weightage" in text
    assert "Missed test cases" in text
    assert "Rejected / Unable to Reproduce" in text
    assert "AC-11" in text
    assert "No Positive scenarios Covered" in text
    bug_pages = [index for index, text in enumerate(pages) if "4. Bug Details" in text]
    assert len(bug_pages) == 1
    assert "No bugs." in pages[bug_pages[0]]


def test_short_story_has_no_test_suite_section(tmp_path: Path) -> None:
    from story_guard.score import score_health

    record = {
        "id": "121213",
        "title": "SNAP Login Screen",
        "area": "Ecom MVP",
        "acceptance_criteria_raw": "present",
        "acceptance_criteria": [{"ac_id": "AC-01", "text": "Successful login"}],
        "scenarios": [],
        "note": "",
        "bugs": [],
        "tests": [
            {
                "id": "121216",
                "title": "Valid login",
                "type": "",
                "mapped_ac_ids": [],
                "suite_id": "121215",
                "suite_name": "Story Guard - AI Agent",
                "suite_type": "staticTestSuite",
                "plan_id": "121214",
            },
            {
                "id": "121217",
                "title": "Empty email",
                "type": "",
                "mapped_ac_ids": [],
                "suite_id": "121215",
                "suite_name": "Story Guard - AI Agent",
                "suite_type": "staticTestSuite",
                "plan_id": "121214",
            },
        ],
    }
    output_path = tmp_path / "short-suite.pdf"
    render_pdf(score_health(record), TEMPLATE, output_path, narrative={}, record=record)

    text = "\n".join(_pdf_page_texts(output_path.read_bytes()))
    assert "Test suite" not in text
    assert "Suite 121215" not in text
    assert "AC-01" in text
    assert "4. Bug Details" in text


def test_render_pdf_missing_template_leaves_no_partial_output(tmp_path: Path) -> None:
    output_path = tmp_path / "must-not-exist.pdf"
    with pytest.raises(RenderError, match="template .* is missing"):
        render_pdf(hand_built_score(), tmp_path / "missing.md", output_path)
    assert not output_path.exists()
    assert not output_path.with_suffix(".pdf.tmp").exists()


def test_live_mapper_prompt_has_no_story_specific_content() -> None:
    prompt = LIVE_MAPPER_PROMPT.read_text(encoding="utf-8")
    # The prompt tells the model not to emit this phrase. That instruction is allowed.
    without_coverage_ban = re.sub(
        r'do not write the phrase "partially covered"',
        "",
        prompt,
        flags=re.IGNORECASE,
    )
    prohibited_patterns = {
        "SNAP identifier": re.compile(r"\bSNAP\b", re.IGNORECASE),
        "test or suite ID": re.compile(r"\b\d{5,}\b"),
        "sample mapping": re.compile(
            r"\bAC-\d+\b|\b\d{5,}\b|"
            r'"mapped_test_ids"\s*:\s*\[\s*["\'][^"\']+["\']'
        ),
        "percent sign": re.compile(r"%"),
        "story-health labels": re.compile(
            r"\b(?:story health|health band|no open bugs|critical|high|medium|low|"
            r"at risk|healthy|green|amber|red)\b",
            re.IGNORECASE,
        ),
        "prohibited coverage phrase": re.compile(r"partially covered", re.IGNORECASE),
    }
    for description, pattern in prohibited_patterns.items():
        scanned = without_coverage_ban if description == "prohibited coverage phrase" else prompt
        assert pattern.search(scanned) is None, f"live mapper prompt contains prohibited {description}"


def test_live_mapper_prompt_preserves_generic_output_contract() -> None:
    prompt = LIVE_MAPPER_PROMPT.read_text(encoding="utf-8")
    for field in (
        '"ac_id"',
        '"mapped_test_ids"',
        '"test_types"',
        '"coverage_status"',
        '"quality"',
        '"finding"',
        '"depth"',
        '"gap"',
        '"scenario_counts"',
    ):
        assert field in prompt
    assert "as happy, negative, or adhoc" in prompt
    assert "exactly one finding sentence" in prompt
    assert "A shared word between a criterion and a test is not evidence" in prompt


def test_pdf_empty_states_are_explicit_and_valid(tmp_path: Path) -> None:
    from story_guard.score import score_health

    base_record = json.loads(SYNTHETIC_STORY.read_text(encoding="utf-8"))
    cases = (
        ("no-criteria", lambda record: record.update(acceptance_criteria=[], acceptance_criteria_raw=""), "No acceptance criteria provided."),
        ("no-tests", lambda record: record.update(tests=[]), "No tests available."),
        ("no-bugs", lambda record: record.update(bugs=[]), "No bugs."),
        (
            "no-open-bugs",
            lambda record: record["bugs"][0].update(status="Closed"),
            "No open bugs",
        ),
    )
    for case_name, change_record, expected_text in cases:
        record = json.loads(json.dumps(base_record))
        change_record(record)
        score = score_health(record)
        score["generated_at"] = record["generated_at"]
        output_path = tmp_path / f"{case_name}.pdf"

        render_pdf(score, TEMPLATE, output_path, narrative={}, record=record)

        pdf_bytes = output_path.read_bytes()
        text = "\n".join(_pdf_page_texts(pdf_bytes))
        assert pdf_bytes.startswith(b"%PDF-")
        assert pdf_bytes.rstrip().endswith(b"%%EOF")
        assert expected_text in text
        assert "Test suite" not in text
        assert "1. Portfolio Summary" in text
        assert "2. Story Health Overview" in text
        assert "3. Acceptance Criteria vs Test Case Coverage" in text
        assert "4. Bug Details" in text
        if case_name == "no-tests":
            assert "0 tests and 0 mapped." in text
        if case_name == "no-bugs":
            assert "0 bugs, with 0 open." in text
        if case_name == "no-open-bugs":
            assert "1 bugs, with 0 open." in text


def test_synthetic_story_uses_the_existing_dashboard_layout(tmp_path: Path) -> None:
    from pypdf import PdfReader

    from story_guard.score import score_health

    record = json.loads(SYNTHETIC_STORY.read_text(encoding="utf-8"))
    assert len(record["acceptance_criteria"]) == 2
    assert len(record["tests"]) == 3
    assert len(record["bugs"]) == 1
    score = score_health(record)
    score["generated_at"] = record["generated_at"]
    output_path = tmp_path / "synthetic-story.pdf"

    render_pdf(score, TEMPLATE, output_path, narrative={}, record=record)

    pdf_bytes = output_path.read_bytes()
    pages = _pdf_page_texts(pdf_bytes)
    text = "\n".join(pages)
    assert pdf_bytes.startswith(b"%PDF-")
    assert pdf_bytes.rstrip().endswith(b"%%EOF")
    assert len(re.findall(rb"/Type\s*/Page\b", pdf_bytes)) >= 1
    for marker in (
        "Portfolio Summary",
        "Story Health Overview",
        "Acceptance Criteria vs Test Case Coverage",
        "Bug Details",
        "Key Observations",
        "Gap colour key",
        "User Stories Assessed",
        "User Story ID",
        "Total TC",
        "Total Bugs",
        "Coverage Depth (AI)",
        "Missed test cases",
        "Coverage weightage",
        "Bug ID",
        "Story Guard",
        "Page 1 of",
    ):
        assert marker in text
    assert text.index("1. Portfolio Summary") < text.index("2. Story Health Overview")
    assert text.index("2. Story Health Overview") < text.index(
        "3. Acceptance Criteria vs Test Case Coverage"
    )
    assert text.index("3. Acceptance Criteria vs Test Case Coverage") < text.index("4. Bug Details")
    assert "Update account contact details" in text
    assert "SYN-2401" in text
    assert "Synthetic Accounts" in text
    assert "Digital Banking" not in text
    assert "123086" not in text
    assert "SNAP Login Screen" not in text
    assert "Ecom MVP" not in text
    assert "2 acceptance criteria" in text
    assert "3 tests and 2 mapped." in text
    assert "1 bugs, with 1 open." in text
    assert "SYN-AC-001" in text and "SYN-AC-002" in text
    assert "SYN-BUG-001" in text
    assert "Test suite" not in text

    # The generated 123086 snapshot is not kept in the tree. The example PDF is the layout reference.
    reference = PdfReader(PROJECT_ROOT / "story_health_report_example.pdf")
    reference_text = "\n".join(page.extract_text() or "" for page in reference.pages)
    ordered_sections = (
        "1. Portfolio Summary",
        "2. Story Health Overview",
        "3. Acceptance Criteria vs Test Case Coverage",
        "4. Bug Details",
    )
    assert [text.index(section) for section in ordered_sections] == sorted(
        text.index(section) for section in ordered_sections
    )
    assert [reference_text.index(section) for section in ordered_sections] == sorted(
        reference_text.index(section) for section in ordered_sections
    )
    for marker in ("Project:", "User Story ID", "Total TC", "AC ID", "Bug ID"):
        assert marker in reference_text
        assert marker in text


def test_missing_bug_data_is_not_reported_as_zero_bugs(tmp_path: Path) -> None:
    from story_guard.score import score_health

    record = json.loads(SYNTHETIC_STORY.read_text(encoding="utf-8"))
    score = score_health(record)
    for key in ("bugs", "bug_count", "open_bug_count", "open_bugs_by_priority"):
        score.pop(key)
    output_path = tmp_path / "bugs-unavailable.pdf"

    render_pdf(score, TEMPLATE, output_path, narrative={}, record=record)

    text = "\n".join(_pdf_page_texts(output_path.read_bytes()))
    assert "Bug information unavailable." in text
    assert "Open bug count unavailable." in text
    assert "Unavailable bugs, with Unavailable open." in text
    assert "Unavailable" in text
    assert "No bugs." not in text
    assert "No open bugs" not in text


def test_long_review_notes_flow_past_the_summary_table(tmp_path: Path) -> None:
    """Bug text and later findings must not sit in the one-row summary table."""
    marker = "BUGDETAILMARKER"
    narrative = {
        "headline": "No open bugs.",
        "observations": [
            "Story health - No open bugs",
            "8 acceptance criteria, 0 adequately covered, 0 with gaps, 8 not covered.",
            "18 tests and 0 mapped.",
            "0 bugs, with 0 open.",
            f"Bug 122590 description: {marker} " + ("x" * 1500),
            "Bug 122590 repro steps part 1 of 2: " + ("y" * 1200),
            "Bug 122590 repro steps part 2 of 2: " + ("z" * 200),
            *[f"Finding {index} names AC-1." for index in range(1, 25)],
        ],
        "actions": [],
    }
    output_path = tmp_path / "long-notes.pdf"
    render_pdf(hand_built_score(), TEMPLATE, output_path, narrative=narrative)

    from pypdf import PdfReader

    reader = PdfReader(str(output_path))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "Key Observations" in text
    assert "Review notes" in text
    assert marker in text
    assert "Finding 24" in text
    assert len(reader.pages) >= 2


def test_long_actions_flow_past_the_summary_table(tmp_path: Path) -> None:
    """A side panel taller than one page used to raise LayoutError."""
    actions = [
        {
            "owner": "QA",
            "text": (
                f"ACTIONMARKER-{index:02d} close the gap. "
                + ("Check the retained email and the inline error. " * 12)
            ),
        }
        for index in range(16)
    ]
    actions.append(
        {
            "owner": "Dev",
            "text": "HUGEACTIONMARKER " + ("Reproduce the open defect. " * 400),
        }
    )
    narrative = {
        "headline": "Coverage gaps remain.",
        "observations": [
            "Story health - No open bugs",
            *[
                f"OBSMARKER-{index:02d} "
                + ("This criterion still has a coverage gap. " * 4)
                for index in range(10)
            ],
        ],
        "actions": actions,
    }
    output_path = tmp_path / "long-actions.pdf"
    render_pdf(hand_built_score(), TEMPLATE, output_path, narrative=narrative)

    from pypdf import PdfReader

    reader = PdfReader(str(output_path))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "Key Observations" in text
    assert "Recommended actions" in text
    for index in range(16):
        assert f"ACTIONMARKER-{index:02d}" in text
    for index in range(10):
        assert f"OBSMARKER-{index:02d}" in text
    assert "HUGEACTIONMARKER" in text
    assert len(reader.pages) >= 2
