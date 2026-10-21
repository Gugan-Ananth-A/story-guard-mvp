"""Command line entry for score and generate."""

import argparse
import json
import re
import sys
from pathlib import Path

from story_guard.envfile import load_env_file
from story_guard.graph import ContractError, GateError, artifacts_dir, run, run_generate, _template_path
from story_guard.narrative import NarrativeError
from story_guard.render import RenderError, render_sprint_pdf
from story_guard.trace import record_success

_USAGE = (
    "usage: story-guard score --story-id 121213\n"
    "       story-guard generate --story-id 121213\n"
    "       story-guard generate --story-id 121213 --live\n"
    "       story-guard generate --story-id 121213 --test-plan-id 121214 --live\n"
    "       story-guard sprint --score-file SCORE.json --score-file OTHER.json --slug sprint-name"
)


def main(argv: list[str] | None = None) -> int:
    load_env_file()
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print(_USAGE)
        return 0
    parser = argparse.ArgumentParser(prog="story-guard")
    sub = parser.add_subparsers(dest="command")
    score = sub.add_parser("score")
    score.add_argument("--story-id", required=True)
    generate = sub.add_parser("generate")
    generate.add_argument("--story-id", required=True)
    generate.add_argument("--test-plan-id", default="")
    generate.add_argument("--live", action="store_true", default=False)
    sprint = sub.add_parser("sprint")
    sprint.add_argument("--score-file", action="append", required=True)
    sprint.add_argument("--slug", required=True)
    parsed = parser.parse_args(args)
    if parsed.command == "score":
        return _score(parsed.story_id)
    if parsed.command == "generate":
        return _generate(parsed.story_id, parsed.live, parsed.test_plan_id)
    if parsed.command == "sprint":
        return _sprint(parsed.score_file, parsed.slug)
    print(_USAGE, file=sys.stderr)
    return 2


def _score(story_id: str) -> int:
    try:
        state = run({"story_id": story_id})
    except (GateError, ContractError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(state["score"], indent=2))
    return 0


def _generate(story_id: str, live: bool, test_plan_id: str = "") -> int:
    from story_guard.ado_client import ADOClientError

    def progress(message: str) -> None:
        # Keep stdout reserved for the final Markdown path so shell scripts
        # can continue to consume it. Flush each line for long live calls.
        print(f"[story-guard] {message}", file=sys.stderr, flush=True)

    state_in = {"story_id": story_id, "live": live, "progress": progress}
    if test_plan_id:
        state_in["test_plan_id"] = test_plan_id
    progress(f"starting {'live ' if live else ''}generation for story {story_id}")
    try:
        state = run_generate(state_in)
    except (GateError, ContractError, NarrativeError, RenderError, ADOClientError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    try:
        record_success(
            state["story_id"],
            state["token_count"],
            state["narrative_latency_ms"],
        )
    except OSError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(state["markdown_path"])
    return 0


def _sprint(score_files: list[str], raw_slug: str) -> int:
    slug = _safe_slug(raw_slug)
    if not slug:
        print("sprint slug must contain at least one letter or number", file=sys.stderr)
        return 1
    entries = []
    for raw_path in score_files:
        path = Path(raw_path)
        try:
            score = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            entries.append(
                {
                    "source_label": path.stem or "score file",
                    "title": path.stem or "Score file",
                    "skip_reason": f"score file unavailable: {error}",
                }
            )
            continue
        if (
            not isinstance(score, dict)
            or not isinstance(score.get("story_id"), str)
            or not score["story_id"].strip()
            or not isinstance(score.get("title"), str)
            or not score["title"].strip()
        ):
            story_id = score.get("story_id") if isinstance(score, dict) else None
            title = score.get("title") if isinstance(score, dict) else None
            entries.append(
                {
                    "story_id": story_id or path.stem or "Unknown",
                    "title": title or "Story details unavailable",
                    "skip_reason": "score must contain a story_id and title",
                }
            )
            continue
        entries.append({"score": score, "narrative": {}})

    output_path = artifacts_dir() / f"sprint-{slug}.pdf"
    try:
        render_sprint_pdf(entries, _template_path(), output_path)
    except (OSError, ValueError, KeyError, TypeError, RenderError) as error:
        print(f"sprint PDF failed: {error}", file=sys.stderr)
        return 1
    print(output_path)
    return 0


def _safe_slug(value: str) -> str:
    """Normalize user input to a bounded filename component."""
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return slug[:64].rstrip("-")


if __name__ == "__main__":
    raise SystemExit(main())
