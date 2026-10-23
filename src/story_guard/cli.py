"""Command line entry for score and generate."""

import argparse
import json
import re
import sys
from pathlib import Path

from story_guard.envfile import FILE_OWNS, load_env_file
from story_guard.graph import (
    ContractError,
    GateError,
    artifacts_dir,
    run,
    run_generate,
    _template_path,
)
from story_guard.narrative import NarrativeError, configured_llm, keep_only_model
from story_guard.render import RenderError, render_sprint_pdf
from story_guard.trace import record_batch, record_success

_USAGE = (
    "usage: story-guard score --story-id 121213\n"
    "       story-guard generate --story-id 121213\n"
    "       story-guard generate --story-id 123086 --live\n"
    "       story-guard generate --story-id 121213 --story-id 123086 --live\n"
    "       story-guard generate --story-ids 121213,123086 --live\n"
    "       story-guard generate --sprint \"<iteration path>\" --live\n"
    "       story-guard generate --sprint '<iteration path>'\n"
    "       story-guard generate --story-id 121213 --test-plan-id 121214 --live\n"
    "       story-guard list-stories --iteration-path 'Project\\Iteration'\n"
    "       story-guard sprints\n"
    "       story-guard fetch-stories --story-ids 121213 121214\n"
    "       story-guard sprint --score-file SCORE.json --score-file OTHER.json --slug sprint-name"
)


def main(argv: list[str] | None = None) -> int:
    for key, previous, value in load_env_file(file_owns=FILE_OWNS):
        print(
            f"[story-guard] {key}={value} from .env (shell had {previous})",
            file=sys.stderr,
            flush=True,
        )
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print(_USAGE)
        return 0
    parser = argparse.ArgumentParser(prog="story-guard")
    sub = parser.add_subparsers(dest="command")
    score = sub.add_parser("score")
    score.add_argument("--story-id", required=True)
    generate = sub.add_parser("generate")
    generate_input = generate.add_mutually_exclusive_group(required=True)
    generate_input.add_argument("--story-id", action="append")
    generate_input.add_argument("--story-ids", action="append")
    generate_input.add_argument("--sprint")
    generate.add_argument("--test-plan-id", default="")
    generate.add_argument("--live", action="store_true", default=False)
    sprint = sub.add_parser("sprint")
    sprint.add_argument("--score-file", action="append", required=True)
    sprint.add_argument("--slug", required=True)
    list_stories = sub.add_parser("list-stories")
    list_stories.add_argument("--iteration-path", required=True)
    sub.add_parser("sprints")
    fetch_stories = sub.add_parser("fetch-stories")
    fetch_stories.add_argument("--story-ids", nargs="+", type=int, required=True)
    parsed = parser.parse_args(args)
    if parsed.command == "score":
        return _score(parsed.story_id)
    if parsed.command == "generate":
        # A sprint without --live uses each story's explicit plan membership.
        # --sprint --live keeps the batch path that loads each story's plan.
        if parsed.sprint and not parsed.live:
            return _generate_sprint(parsed.sprint)
        return _generate(
            parsed.story_id,
            parsed.story_ids,
            parsed.sprint or "",
            parsed.live,
            parsed.test_plan_id,
        )
    if parsed.command == "sprint":
        return _sprint(parsed.score_file, parsed.slug)
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


def _generate_sprint(iteration_path: str) -> int:
    """Generate one report per story, using that story's linked test plans."""
    from story_guard.ado_client import ADOClient, ADOClientError
    from story_guard.graph import load_live_story

    try:
        client = ADOClient.from_env()
        stories = client.list_user_stories(iteration_path)
    except ADOClientError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if not stories:
        print(f"No User Stories found in {iteration_path}")
        return 0

    unique_stories = []
    seen_story_ids = set()
    duplicate_story_ids = set()
    for story in stories:
        story_id = str(story["id"])
        if story_id in seen_story_ids:
            duplicate_story_ids.add(story_id)
            continue
        seen_story_ids.add(story_id)
        unique_stories.append(story)

    bundles = {}
    failures = []
    for story in unique_stories:
        story_id = str(story["id"])
        try:
            bundle = client.fetch_many_stories([int(story_id)])[0]
            if "error" in bundle:
                error = bundle["error"]
                if error.get("code") == "not_found":
                    bundles[story_id] = bundle
                    continue
                message = error.get("message", "could not fetch story")
                raise ADOClientError(message)
            bundles[story_id] = bundle
        except ADOClientError as exc:
            failures.append((story_id, str(exc)))

    case_ids = {
        int(test_case["id"])
        for bundle in bundles.values()
        for test_case in bundle.get("test_cases", [])
    }
    try:
        plan_memberships = client.test_case_plan_memberships(sorted(case_ids))
    except ADOClientError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    entries: list[dict] = []
    for story in unique_stories:
        story_id = str(story["id"])
        bundle = bundles.get(story_id)
        if bundle is None:
            reason = next(
                (message for failed_id, message in failures if failed_id == story_id),
                "could not fetch story",
            )
            entries.append(_rollup_entry(story_id, None, reason))
            continue
        try:
            live_record = load_live_story(
                story_id,
                client=client,
                story_bundle=bundle,
                plan_memberships=plan_memberships,
            )
            if story_id in duplicate_story_ids:
                live_record.setdefault("validation_messages", []).append(
                    f"Duplicate Userstory ID - “{story_id}” found"
                )
            state = run_generate(
                {"story_id": story_id, "live": True, "live_record": live_record}
            )
            record_success(
                state["story_id"],
                state["token_count"],
                state["narrative_latency_ms"],
            )
        except (
            ADOClientError,
            GateError,
            ContractError,
            NarrativeError,
            RenderError,
            OSError,
        ) as exc:
            failures.append((story_id, str(exc)))
            entries.append(_rollup_entry(story_id, None, str(exc)))
            continue
        print(state["markdown_path"])
        entries.append(_rollup_entry(story_id, state, ""))

    for story_id, message in failures:
        print(f"Story {story_id}: {message}", file=sys.stderr)
    rollup_ok = _write_run_rollup(entries, iteration_path)
    return 1 if failures or not rollup_ok else 0


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
    try:
        provider, model = configured_llm()
    except NarrativeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(
        f"[story-guard] provider {provider}, model {model}",
        file=sys.stderr,
        flush=True,
    )
    written: list[str] = []
    entries: list[dict] = []
    failed = False
    # A plan id is rejected above unless this batch is exactly one story.
    plan_for_story = test_plan_id if len(requested) == 1 else ""
    # Stories run one at a time, so their Ollama calls do not overlap.
    for story_id in requested:
        state, error = _generate_one(story_id, live, plan_for_story)
        if state is None:
            failed = True
        else:
            written.append(story_id)
        entries.append(_rollup_entry(story_id, state, error))
    skipped = [story_id for story_id in requested if story_id not in set(written)]
    try:
        record_batch(requested, written, skipped)
    except OSError as exc:
        print(f"batch trace was not written: {exc}", file=sys.stderr)
    slug = sprint_path if sprint_path else "-".join(requested)
    if not _write_run_rollup(entries, slug):
        failed = True
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


def _generate_one(story_id: str, live: bool, test_plan_id: str = "") -> tuple[dict | None, str]:
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
        message = _named(story_id, exc)
        print(message, file=sys.stderr)
        return None, message
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
    return state, ""


def _rollup_entry(story_id: str, state: dict | None, error: str) -> dict:
    """One rollup row. A story without a score stays on the skipped list."""
    if isinstance(state, dict) and isinstance(state.get("score"), dict):
        narrative = state.get("narrative")
        record = state.get("record")
        return {
            "score": state["score"],
            "narrative": narrative if isinstance(narrative, dict) else {},
            "record": record if isinstance(record, dict) else None,
        }
    return {
        "story_id": story_id,
        "title": f"Story {story_id}",
        "skip_reason": error or "not processed",
    }


def _write_run_rollup(entries: list[dict], slug: str) -> bool:
    """Write sprint-<slug>.pdf for a sprint or a run of two or more stories."""
    if len(entries) < 2:
        return True
    if not any(isinstance(entry.get("score"), dict) for entry in entries):
        return True
    # Look this up at call time so a test patch on graph.artifacts_dir applies.
    from story_guard.graph import artifacts_dir as current_artifacts_dir

    safe = _safe_slug(slug) or "run"
    output_path = current_artifacts_dir() / f"sprint-{safe}.pdf"
    try:
        render_sprint_pdf(entries, _template_path(), output_path)
    except (OSError, ValueError, KeyError, TypeError, RenderError) as error:
        print(f"sprint PDF failed: {error}", file=sys.stderr)
        return False
    print(output_path)
    return True


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
