"""Command line entry for score and generate."""

import argparse
import json
import sys

from story_guard.envfile import load_env_file
from story_guard.graph import ContractError, GateError, run, run_generate
from story_guard.narrative import NarrativeError
from story_guard.render import RenderError
from story_guard.trace import record_success

_USAGE = (
    "usage: story-guard score --story-id 121213\n"
    "       story-guard generate --story-id 121213\n"
    "       story-guard generate --story-id 121213 --live\n"
    "       story-guard generate --story-id 121213 --story-id 123086 --live\n"
    "       story-guard generate --story-id 121213 --test-plan-id 121214 --live"
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
    generate.add_argument("--story-id", required=True, action="append")
    generate.add_argument("--test-plan-id", default="")
    generate.add_argument("--live", action="store_true", default=False)
    parsed = parser.parse_args(args)
    if parsed.command == "score":
        return _score(parsed.story_id)
    if parsed.command == "generate":
        return _generate(parsed.story_id, parsed.live, parsed.test_plan_id)
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


def _generate(story_ids: list[str], live: bool, test_plan_id: str = "") -> int:
    """Generate each story. A failure is reported and the next story still runs."""
    failed = False
    for story_id in story_ids:
        if _generate_one(story_id, live, test_plan_id) != 0:
            failed = True
    return 1 if failed else 0


def _named(story_id: str, exc: BaseException) -> str:
    text = str(exc).strip()
    if story_id and story_id in text:
        return text
    return f"story {story_id}: {text}"


def _generate_one(story_id: str, live: bool, test_plan_id: str = "") -> int:
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
        print(_named(story_id, exc), file=sys.stderr)
        return 1
    try:
        record_success(
            state["story_id"],
            state["token_count"],
            state["narrative_latency_ms"],
        )
    except OSError as exc:
        print(_named(story_id, exc), file=sys.stderr)
        return 1
    print(state["markdown_path"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
