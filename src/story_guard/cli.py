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
    "       story-guard generate --story-id 121213\n"
    "       story-guard list-stories --iteration-path 'Project\\Iteration'\n"
    "       story-guard sprints\n"
    "       story-guard fetch-stories --story-ids 121213 121214"
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
    list_stories = sub.add_parser("list-stories")
    list_stories.add_argument("--iteration-path", required=True)
    sub.add_parser("sprints")
    fetch_stories = sub.add_parser("fetch-stories")
    fetch_stories.add_argument("--story-ids", nargs="+", type=int, required=True)
    parsed = parser.parse_args(args)
    if parsed.command == "score":
        return _score(parsed.story_id)
    if parsed.command == "generate":
        return _generate(parsed.story_id, parsed.live)
    if parsed.command == "list-stories":
        return _list_stories(parsed.iteration_path)
    if parsed.command == "sprints":
        return _sprints()
    if parsed.command == "fetch-stories":
        return _fetch_stories(parsed.story_ids)
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


def _list_stories(iteration_path: str) -> int:
    from story_guard.ado_client import ADOClient, ADOClientError

    try:
        stories = ADOClient.from_env().list_user_stories(iteration_path)
    except ADOClientError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(stories, indent=2))
    return 0


def _sprints() -> int:
    from story_guard.ado_client import ADOClient, ADOClientError

    try:
        iteration_paths = ADOClient.from_env().list_iterations()
    except ADOClientError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print("\n".join(iteration_paths))
    return 0


def _fetch_stories(story_ids: list[int]) -> int:
    from story_guard.ado_client import ADOClient, ADOClientError

    try:
        results = ADOClient.from_env().fetch_many_stories(story_ids)
    except ADOClientError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(results, indent=2))
    return 1 if any("error" in result for result in results) else 0


def _generate(story_id: str, live: bool) -> int:
    from story_guard.ado_client import ADOClientError

    try:
        state = run_generate({"story_id": story_id, "live": live})
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


if __name__ == "__main__":
    raise SystemExit(main())
