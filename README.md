# Story Guard

Phase 1 health report for one story. The default provider is a local model; a
hosted DeepSeek provider is also supported.

For live analysis, the model reviews every acceptance criterion against each
test suite in bounded batches. It predicts the AC-to-test links, reports AC
quality, and the Python scorer calculates final coverage status and story
health. Existing source-side links are not used as a shortcut.

## Model

Ollama serves the model at `http://127.0.0.1:11434`. Narrative and live-review requests set `num_ctx` to **8192**. Large suites are split into bounded batches so one AC review stays within the local model context. The model's native long window stays unused.

| Role | Tag | Size |
| --- | --- | --- |
| Default | `qwen3.5:4b` | about 3.3 GB |
| Fallback | `phi4-mini` | about 2.5 GB |

`phi4-mini` uses the same `num_ctx` of 8192. Pull it only when `qwen3.5:4b` will not stay resident with the editor open.

Load one model at a time. Do not load both. `qwen3.5:9b` is about 6.6 GB and does not stay resident on this 8 GB Mac, so unload it before a generate.

```bash
ollama pull qwen3.5:4b
python scripts/ollama_smoke.py
```

The smoke script targets `qwen3.5:4b`, sends `num_ctx` 8192 on the request, and prints one JSON object.

To use DeepSeek instead of Ollama, set these values in `.env`:

```bash
STORY_GUARD_LLM=deepseek
DEEPSEEK_API_KEY=your_api_key
DEEPSEEK_MODEL=deepseek-chat
```

The DeepSeek path uses its `/chat/completions` endpoint, bearer authentication,
and JSON output mode. Leave `STORY_GUARD_LLM=ollama` to keep using Qwen locally.

`story-guard generate` keeps stdout limited to the final Markdown path. Progress,
including fetch, contract validation, each AC/suite review, retries, and report
rendering, is flushed to stderr with a `[story-guard]` prefix.

## Sprint PDF

Build an offline multi-story PDF from score JSON files with repeatable
`--score-file` arguments. The first page is a run-local rollup; successful
scores follow as their standard single-story reports. Unreadable or incomplete
score files are identified as skipped on the rollup and do not receive detail
pages. No ADO request, PAT, or narrative model call is used by this command.

```bash
story-guard sprint \
	--score-file tests/data/score-one.json \
	--score-file tests/data/score-two.json \
	--slug 2026-10-21
```

The output is `artifacts/sprint-2026-10-21.pdf` (or the configured
`STORY_GUARD_ARTIFACTS_DIR`). The slug is lowercased, non-alphanumeric runs
become hyphens, and the result is capped at 64 characters before it is used as
a filename component. Input order determines rollup row and detail-page order.

## Trace

`LANGSMITH_API_KEY` is optional. The PDF is produced without it. A successful `story-guard generate` appends one line to `artifacts/runs.jsonl` with the story id, the narrative token count, and the narrative latency. When the key is set, that run is also sent to LangSmith. The key is read from the environment. It is not written into the report or the jsonl line.
