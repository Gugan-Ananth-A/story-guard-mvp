"""Command line entry for score and generate."""

import argparse
import json
import sys

from story_guard.graph import ContractError, GateError, run, run_generate
from story_guard.narrative import NarrativeError
from story_guard.render import RenderError
from story_guard.trace import record_success

_USAGE = (
    "usage: story-guard score --story-id 121213\n"
    "       story-guard generate --story-id 121213"
)


def main(argv: list[str] | None = None) -> int:
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
    generate.add_argument("--live", action="store_true", default=False)
    parsed = parser.parse_args(args)
    if parsed.command == "score":
        return _score(parsed.story_id)
    if parsed.command == "generate":
        return _generate(parsed.story_id, parsed.live)
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


def _generate(story_id: str, live: bool) -> int:
    if live:
        print("--live is not wired", file=sys.stderr)
        return 1
    try:
        state = run_generate({"story_id": story_id})
    except (GateError, ContractError, NarrativeError, RenderError) as exc:
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


if __name__ == "__main__":
    raise SystemExit(main())
