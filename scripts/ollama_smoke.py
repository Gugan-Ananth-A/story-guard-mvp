"""Ask the local Ollama runner for one JSON object.

The request sets num_ctx. The model's native long window is not used.
This script does not read a story, a fixture, or a PAT.
"""

import json
import sys
import urllib.error
import urllib.request

HOST = "http://127.0.0.1:11434"
MODEL = "qwen3.5:4b"
NUM_CTX = 8192

PROMPT = 'Return one JSON object with a single key "ok" set to true.'


def main() -> int:
    payload = {
        "model": MODEL,
        "stream": False,
        "format": "json",
        "think": False,
        "messages": [{"role": "user", "content": PROMPT}],
        "options": {"num_ctx": NUM_CTX},
    }
    request = urllib.request.Request(
        f"{HOST}/api/chat",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            body = json.load(response)
    except urllib.error.URLError as exc:
        print(f"ollama smoke failed: {exc}", file=sys.stderr)
        return 1
    content = body.get("message", {}).get("content", "")
    try:
        obj = json.loads(content)
    except json.JSONDecodeError:
        print("ollama smoke failed: response was not JSON", file=sys.stderr)
        return 1
    if not isinstance(obj, dict):
        print("ollama smoke failed: response was not a JSON object", file=sys.stderr)
        return 1
    sys.stdout.write(json.dumps(obj))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
