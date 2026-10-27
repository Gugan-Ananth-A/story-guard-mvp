"""Sprint rollup and multi-story PDF generation stay fixture-only and deterministic."""

import json
import re
from pathlib import Path

from story_guard.cli import main
from story_guard.render import render_pdf, render_sprint_pdf
from story_guard.score import score_health
from tests.test_render_pdf import _pdf_page_texts

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "templates" / "health_report.md"


def _fixture_scores() -> tuple[dict, dict, dict, dict]:
    normal_record = json.loads((ROOT / "fixtures" / "FIX-121213.json").read_text(encoding="utf-8"))
    synthetic_record = json.loads((ROOT / "tests" / "data" / "synthetic_story.json").read_text(encoding="utf-8"))
    normal_score = score_health(normal_record)
    synthetic_score = score_health(synthetic_record)
    normal_score["generated_at"] = "2026-10-21T09:00:00Z"
    synthetic_score["generated_at"] = "2026-10-21T09:00:00Z"
    return normal_score, normal_record, synthetic_score, synthetic_record


def _normalized_page(page: str) -> str:
    return re.sub(r"Page\s+\d+\s+of\s+\d+", "Page <number>", page)


def test_rollup_uses_only_current_scores_and_score_bucket_math(
    tmp_path: Path, monkeypatch
) -> None:
    normal_score, normal_record, synthetic_score, synthetic_record = _fixture_scores()
    output = tmp_path / "rollup.pdf"
    monkeypatch.delenv("ADO_PAT", raising=False)
    monkeypatch.delenv("ADO_PAT", raising=False)
    monkeypatch.delenv("ADO_PAT", raising=False)
    monkeypatch.delenv("ADO_PAT", raising=False)
    entries = [
        {"score": normal_score, "record": normal_record, "narrative": {}},
        {"score": synthetic_score, "record": synthetic_record, "narrative": {}},
    ]

    render_sprint_pdf(entries, TEMPLATE, output)

    pages = _pdf_page_texts(output.read_bytes())
    first_page = pages[0]
    assert output.read_bytes().startswith(b"%PDF-")
    assert output.read_bytes().rstrip().endswith(b"%%EOF")
    assert "Sprint Rollup" in first_page
    for column in (
        "Story ID",
        "Story title",
        "Health status",
        "Open bugs",
        "Coverage",
        "Coverage classification",
    ):
        assert column in first_page
    assert "121213" in first_page and "SNAP Login Screen" in first_page
    assert "SYN-2401" in first_page and "Update account contact details" in first_page
    assert "Digital Banking" not in first_page
    assert "0%" in first_page and "60%" in first_page
    assert "none" in first_page and "partial" in first_page
    assert "\n0\n" in first_page and "\n1\n" in first_page
    lines = first_page.splitlines()
    normal_start = lines.index("121213")
    synthetic_start = lines.index("SYN-2401")
    assert lines[normal_start : normal_start + 7] == [
        "121213",
        "SNAP Login Screen",
        "No open bugs",
        "0",
        "0%",
        "none",
        "Included",
    ]
    assert lines[synthetic_start : synthetic_start + 7] == [
        "SYN-2401",
        "Update account contact details",
        "High",
        "1",
        "60%",
        "partial",
        "Included",
    ]
    assert "123086" not in first_page
    assert "not-requested" not in first_page


def test_rollup_marks_all_three_coverage_buckets_adequate(tmp_path: Path) -> None:
    record = json.loads((ROOT / "tests" / "data" / "synthetic_story.json").read_text(encoding="utf-8"))
    criterion = record["acceptance_criteria"][0]
    record["acceptance_criteria"] = [criterion]
    record["tests"] = [
        {
            "id": f"BUCKET-{test_type}",
            "title": f"Exercise {test_type} behavior",
            "type": test_type,
            "mapped_ac_ids": [criterion["ac_id"]],
        }
        for test_type in ("happy", "negative", "adhoc")
    ]
    score = score_health(record)
    output = tmp_path / "adequate-rollup.pdf"

    render_sprint_pdf([{"score": score, "record": record}], TEMPLATE, output)

    rollup = _pdf_page_texts(output.read_bytes())[0]
    assert "100%" in rollup
    assert "adequate" in rollup
    assert "none" not in rollup


def test_successful_details_match_standalone_reports_in_run_order(tmp_path: Path) -> None:
    normal_score, normal_record, synthetic_score, synthetic_record = _fixture_scores()
    output = tmp_path / "ordered.pdf"
    render_sprint_pdf(
        [
            {"score": normal_score, "record": normal_record, "narrative": {}},
            {"score": synthetic_score, "record": synthetic_record, "narrative": {}},
        ],
        TEMPLATE,
        output,
    )
    sprint_pages = _pdf_page_texts(output.read_bytes())
    standalone_texts = []
    for score, record, filename in (
        (normal_score, normal_record, "normal.pdf"),
        (synthetic_score, synthetic_record, "synthetic.pdf"),
    ):
        standalone = tmp_path / filename
        render_pdf(score, TEMPLATE, standalone, narrative={}, record=record)
        standalone_texts.append(_pdf_page_texts(standalone.read_bytes()))

    assert len(sprint_pages) == 1 + sum(len(pages) for pages in standalone_texts)
    detail_pages = sprint_pages[1:]
    offset = 0
    for score, standalone_pages in zip((normal_score, synthetic_score), standalone_texts):
        current_pages = detail_pages[offset : offset + len(standalone_pages)]
        assert [_normalized_page(page) for page in current_pages] == [
            _normalized_page(page) for page in standalone_pages
        ]
        assert "1. Portfolio Summary" in current_pages[0]
        assert score["story_id"] in "\n".join(current_pages)
        offset += len(standalone_pages)
    assert offset == len(detail_pages)
    first_synthetic_detail = next(
        index for index, page in enumerate(detail_pages) if "SYN-2401" in page
    )
    assert first_synthetic_detail > 0


def test_skipped_story_is_on_rollup_without_detail_and_unrequested_story_is_absent(tmp_path: Path) -> None:
    normal_score, normal_record, _synthetic_score, _synthetic_record = _fixture_scores()
    output = tmp_path / "skipped.pdf"
    render_sprint_pdf(
        [
            {"score": normal_score, "record": normal_record, "narrative": {}},
            {
                "story_id": "SKIP-77",
                "title": "Skipped fixture story",
                "skip_reason": "score validation failed",
            },
        ],
        TEMPLATE,
        output,
    )
    pages = _pdf_page_texts(output.read_bytes())
    assert "SKIP-77" in pages[0]
    assert "Skipped fixture story" in pages[0]
    assert "Skipped: score validation failed" in pages[0]
    assert all("SKIP-77" not in page for page in pages[1:])
    all_text = "\n".join(pages)
    assert "SYN-2401" not in all_text
    assert "STORY-OUTSIDE-RUN" not in all_text
    assert len(pages) > 1


def test_sprint_cli_renders_two_fixture_scores_without_ado_pat(tmp_path: Path, monkeypatch, capsys) -> None:
    normal_score, _normal_record, synthetic_score, _synthetic_record = _fixture_scores()
    score_paths = []
    for score in (normal_score, synthetic_score):
        path = tmp_path / f"{score['story_id']}.json"
        path.write_text(json.dumps(score), encoding="utf-8")
        score_paths.append(path)
    monkeypatch.delenv("ADO_PAT", raising=False)
    monkeypatch.setattr("story_guard.cli.artifacts_dir", lambda: tmp_path / "artifacts")

    from story_guard.ado_client import ADOClient

    monkeypatch.setattr(
        ADOClient,
        "from_env",
        classmethod(lambda cls: (_ for _ in ()).throw(AssertionError("ADO was contacted"))),
    )

    result = main(
        [
            "sprint",
            "--score-file",
            str(score_paths[0]),
            "--score-file",
            str(score_paths[1]),
            "--slug",
            "T36 Sprint PDF",
        ]
    )

    target = tmp_path / "artifacts" / "sprint-t36-sprint-pdf.pdf"
    assert result == 0
    assert capsys.readouterr().out.strip() == str(target)
    assert target.is_file()
    pages = _pdf_page_texts(target.read_bytes())
    assert "121213" in pages[0] and "SYN-2401" in pages[0]
    assert "Digital Banking" not in pages[0]
    assert target.read_bytes().startswith(b"%PDF-")
    assert target.read_bytes().rstrip().endswith(b"%%EOF")


def test_sprint_cli_lists_unreadable_score_as_skipped_and_slug_is_safe(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.delenv("ADO_PAT", raising=False)
    monkeypatch.setattr("story_guard.cli.artifacts_dir", lambda: tmp_path / "artifacts")
    missing = tmp_path / "broken-score.json"
    result = main(["sprint", "--score-file", str(missing), "--slug", "../outside"])

    target = tmp_path / "artifacts" / "sprint-outside.pdf"
    assert result == 0
    assert capsys.readouterr().out.strip() == str(target)
    pages = _pdf_page_texts(target.read_bytes())
    assert len(pages) == 1
    assert "broken-score" in pages[0]
    assert "Skipped:" in pages[0]
    assert not (tmp_path / "outside.pdf").exists()