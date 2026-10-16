"""Command line entry for score and generate."""

import argparse
import json
import sys

from story_guard.envfile import load_env_file
from story_guard.graph import ContractError, GateError, run, run_generate
from story_guard.narrative import NarrativeError, keep_only_model
from story_guard.render import RenderError
from story_guard.trace import record_batch, record_success

_USAGE = (
    "usage: story-guard score --story-id 121213\n"
    "       story-guard generate --story-id 121213\n"
    "       story-guard generate --story-id 123086 --live\n"
    "       story-guard generate --story-id 121213 --story-id 123086 --live\n"
    "       story-guard generate --story-ids 121213,123086 --live\n"
    "       story-guard generate --sprint \"<iteration path>\" --live\n"
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
    generate.add_argument("--story-id", action="append")
    generate.add_argument("--story-ids", action="append")
    generate.add_argument("--sprint", default="")
    generate.add_argument("--test-plan-id", default="")
    generate.add_argument("--live", action="store_true", default=False)
    parsed = parser.parse_args(args)
    if parsed.command == "score":
        return _score(parsed.story_id)
    if parsed.command == "generate":
        return _generate(
            parsed.story_id,
            parsed.story_ids,
            parsed.sprint,
            parsed.live,
            parsed.test_plan_id,
        )
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


def _generate(
    story_ids: list[str] | None,
    story_id_lists: list[str] | None,
    sprint: str,
    live: bool,
    test_plan_id: str = "",
) -> int:
    """Generate each story in order. One story's failure does not stop the next."""
    from story_guard.ado_client import ADOClientError

    sprint_path = sprint.strip() if isinstance(sprint, str) else ""
    if sprint_path and not live:
        print("--sprint requires --live", file=sys.stderr)
        return 1
    if test_plan_id and not live:
        print("test plan id requires --live", file=sys.stderr)
        return 1
    requested = _requested_ids(story_ids, story_id_lists)
    if sprint_path:
        try:
            requested = _dedupe(requested + _sprint_story_ids(sprint_path))
        except ADOClientError as exc:
            print(str(exc), file=sys.stderr)
            return 1
    if not requested:
        if sprint_path:
            print(f"sprint {sprint_path} has no user stories", file=sys.stderr)
            return 1
        print(_USAGE, file=sys.stderr)
        return 2
    if test_plan_id and len(requested) != 1:
        print("--test-plan-id applies only to one story", file=sys.stderr)
        return 1
    # Unload every other resident model before the first Ollama call.
    keep_only_model()
    written: list[str] = []
    failed = False
    # A plan id is rejected above unless this batch is exactly one story.
    plan_for_story = test_plan_id if len(requested) == 1 else ""
    # Stories run one at a time, so their Ollama calls do not overlap.
    for story_id in requested:
        if _generate_one(story_id, live, plan_for_story):
            written.append(story_id)
        else:
            failed = True
    skipped = [story_id for story_id in requested if story_id not in set(written)]
    try:
        record_batch(requested, written, skipped)
    except OSError as exc:
        print(f"batch trace was not written: {exc}", file=sys.stderr)
    return 1 if failed else 0


def _requested_ids(
    story_ids: list[str] | None,
    story_id_lists: list[str] | None,
) -> list[str]:
    found: list[str] = []
    for story_id in story_ids or []:
        found.append(story_id.strip())
    for chunk in story_id_lists or []:
        for part in chunk.split(","):
            text = part.strip()
            if text:
                found.append(text)
    return _dedupe(found)


def _dedupe(story_ids: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for story_id in story_ids:
        if story_id in seen:
            continue
        seen.add(story_id)
        ordered.append(story_id)
    return ordered


def _sprint_story_ids(iteration_path: str) -> list[str]:
    from story_guard.ado_client import ADOClient

    return ADOClient.from_env().story_ids_for_iteration(iteration_path)


def _named(story_id: str, exc: BaseException) -> str:
    text = str(exc).strip()
    if story_id and story_id in text:
        return text
    return f"story {story_id}: {text}"


def _generate_one(story_id: str, live: bool, test_plan_id: str = "") -> bool:
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
        return False
    try:
        record_success(
            state["story_id"],
            state["token_count"],
            state["narrative_latency_ms"],
        )
    except OSError as exc:
        # The Markdown and PDF are already on disk. A trace failure leaves them.
        print(_named(story_id, exc), file=sys.stderr)
    print(state["markdown_path"])
    return True


if __name__ == "__main__":
    raise SystemExit(main())
