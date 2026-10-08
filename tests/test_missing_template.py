"""The generate command fails closed when the required report template is missing."""

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "templates" / "health_report.md"
COMMAND = Path(__import__("sys").executable).with_name("story-guard")


def test_generate_missing_template_creates_no_artifacts(tmp_path: Path) -> None:
    backup = tmp_path / "health_report.md.backup"
    artifact_dir = tmp_path / "artifacts"
    environment = os.environ.copy()
    environment["STORY_GUARD_ARTIFACTS_DIR"] = str(artifact_dir)
    environment.pop("LANGSMITH_API_KEY", None)

    TEMPLATE.replace(backup)
    try:
        result = subprocess.run(
            [str(COMMAND), "generate", "--story-id", "121213"],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            check=False,
            text=True,
        )
        assert result.returncode != 0
        assert "template" in result.stderr.lower()
        assert not (artifact_dir / "121213.pdf").exists()
        assert not (artifact_dir / "121213.pdf.tmp").exists()
        assert not (artifact_dir / "121213.md").exists()
        assert not (artifact_dir / "runs.jsonl").exists()
    finally:
        backup.replace(TEMPLATE)

    assert TEMPLATE.is_file()
    assert list(artifact_dir.iterdir()) == [] if artifact_dir.exists() else True


def test_generate_invalid_template_fails_before_narrative_and_artifact(tmp_path: Path) -> None:
    backup = tmp_path / "health_report.md.backup"
    artifact_dir = tmp_path / "invalid-template-artifacts"
    environment = os.environ.copy()
    environment["STORY_GUARD_ARTIFACTS_DIR"] = str(artifact_dir)
    environment.pop("LANGSMITH_API_KEY", None)
    original = TEMPLATE.read_text(encoding="utf-8")

    TEMPLATE.replace(backup)
    try:
        TEMPLATE.write_text("## Wrong heading\n{{story_id}}\n", encoding="utf-8")
        result = subprocess.run(
            [str(COMMAND), "generate", "--story-id", "121213"],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            check=False,
            text=True,
        )
        assert result.returncode != 0
        assert "template" in result.stderr.lower()
        assert not (artifact_dir / "121213.pdf").exists()
        assert not (artifact_dir / "121213.pdf.tmp").exists()
        assert not (artifact_dir / "121213.md").exists()
        assert not (artifact_dir / "runs.jsonl").exists()
    finally:
        TEMPLATE.unlink(missing_ok=True)
        backup.replace(TEMPLATE)

    assert TEMPLATE.read_text(encoding="utf-8") == original
    assert list(artifact_dir.iterdir()) == [] if artifact_dir.exists() else True
