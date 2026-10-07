"""Command line entry. Later slices add generate on this command."""

import argparse
import json
import sys

from story_guard.graph import ContractError, GateError, run


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("usage: story-guard score --story-id 121213")
        return 0
    parser = argparse.ArgumentParser(prog="story-guard")
    sub = parser.add_subparsers(dest="command")
    score = sub.add_parser("score")
    score.add_argument("--story-id", required=True)
    parsed = parser.parse_args(args)
    if parsed.command != "score":
        print("usage: story-guard score --story-id 121213", file=sys.stderr)
        return 2
    try:
        state = run({"story_id": parsed.story_id})
    except (GateError, ContractError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(state["score"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
