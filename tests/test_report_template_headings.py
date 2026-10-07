"""Lock the PDF template to the eight report headings."""

import re
from pathlib import Path


def test_report_template_has_exact_frozen_headings_in_order() -> None:
    template_path = Path(__file__).resolve().parents[1] / "templates" / "health_report.md"
    template = template_path.read_text(encoding="utf-8")
    headings = re.findall(r"^## (.+)$", template, flags=re.MULTILINE)

    assert headings == [
        "Title block",
        "Overall RAG",
        "AC review",
        "AC ↔ test mapping",
        "Coverage by type",
        "Bugs",
        "Recommended actions",
        "Appendix",
    ]
