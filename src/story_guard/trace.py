"""Local run line, and a LangSmith trace only when the key is set."""

import json
import hashlib
import os
import sys
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path


def record_success(story_id: str, token_count: int, narrative_latency_ms: int) -> None:
    """Append one jsonl line. A missing LangSmith key does not raise."""
    from story_guard.prefix import load_prefix

    prefix_bytes = load_prefix().encode("utf-8")
    line = {
        "story_id": story_id,
        "token_count": int(token_count),
        "narrative_latency_ms": int(narrative_latency_ms),
        "prefix_sha256": hashlib.sha256(prefix_bytes).hexdigest(),
    }
    _append_jsonl(runs_path(), line)
    _maybe_trace(line)


def runs_path() -> Path:
    from story_guard.graph import artifacts_dir

    return artifacts_dir() / "runs.jsonl"


def _append_jsonl(path: Path, line: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(line, separators=(",", ":")) + "\n")


def _maybe_trace(line: dict) -> None:
    raw = os.environ.get("LANGSMITH_API_KEY")
    if raw is None or raw.strip() == "":
        return
    try:
        _send_trace(raw.strip(), line)
    except OSError as exc:
        print(f"langsmith trace was not sent: {exc}", file=sys.stderr)


def _send_trace(api_key: str, line: dict) -> None:
    """POST one chain run. The key travels in the header only."""
    end = datetime.now(timezone.utc)
    start = end - timedelta(milliseconds=int(line["narrative_latency_ms"]))
    project = os.environ.get("LANGSMITH_PROJECT")
    if project is None or project.strip() == "":
        project = "story-guard"
    body = {
        "id": uuid.uuid4().hex,
        "name": "story-guard generate",
        "run_type": "chain",
        "inputs": {"story_id": line["story_id"]},
        "outputs": {
            "token_count": line["token_count"],
            "narrative_latency_ms": line["narrative_latency_ms"],
        },
        "start_time": start.isoformat(),
        "end_time": end.isoformat(),
        "session_name": project.strip(),
    }
    endpoint = os.environ.get("LANGSMITH_ENDPOINT")
    if endpoint is None or endpoint.strip() == "":
        endpoint = "https://api.smith.langchain.com"
    request = urllib.request.Request(
        endpoint.strip().rstrip("/") + "/runs",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-api-key": api_key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            response.read()
    except urllib.error.HTTPError as exc:
        raise OSError(f"langsmith returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise OSError(f"langsmith request failed: {exc.reason}") from exc
    except TimeoutError as exc:
        raise OSError("langsmith request timed out") from exc
