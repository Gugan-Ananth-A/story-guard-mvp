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

To use the ChatGPT API instead of Ollama, set these values in `.env`:

```bash
STORY_GUARD_LLM=chatgpt
OPENAI_API_KEY=your_api_key
OPENAI_MODEL=gpt-5.6-luna
# Optional. Overrides the provider model. Leave unset when switching providers.
# STORY_GUARD_MODEL=
```

`OPENAI_MODEL` selects the model. Leave it unset to use `gpt-5.6-luna`. `OPENAI_BASE_URL` defaults to `https://api.openai.com/v1`. `chatgpt` and `openai` are the same provider. Requests use `/chat/completions`, bearer authentication, and JSON output. GPT-5 and GPT-6 send `reasoning_effort` `low` and omit `temperature`. The completion budget adds room for reasoning tokens. The JSON object is read from the answer.

To use DeepSeek instead of Ollama, set these values in `.env`:

```bash
STORY_GUARD_LLM=deepseek
DEEPSEEK_API_KEY=your_api_key
DEEPSEEK_MODEL=deepseek-flash
# Optional. Overrides OLLAMA_MODEL, DEEPSEEK_MODEL, and XAI_MODEL.
# STORY_GUARD_MODEL=deepseek-v4-pro
```

`DEEPSEEK_MODEL` selects the DeepSeek model. Leave it unset to use `deepseek-flash`. Set `STORY_GUARD_MODEL` when you want one model id to apply to whichever provider `STORY_GUARD_LLM` selects. `DEEPSEEK_BASE_URL` defaults to `https://api.deepseek.com`.

The project `.env` replaces a shell value for `STORY_GUARD_LLM`, `STORY_GUARD_MODEL`, `OPENAI_MODEL`, `DEEPSEEK_MODEL`, `OLLAMA_MODEL`, and `XAI_MODEL`. An older export does not keep the next run on the previous provider after the file is changed. A model id removed from `.env` is not kept from the shell.

The DeepSeek path uses its `/chat/completions` endpoint, bearer authentication,
and JSON output mode. Leave `STORY_GUARD_LLM=ollama` to keep using Qwen locally. Ollama still reads `OLLAMA_MODEL`, and `STORY_GUARD_MODEL` overrides that too.

`story-guard generate` keeps stdout limited to the Markdown paths. Progress,
including fetch, contract validation, each AC/suite review, retries, and report
rendering, is flushed to stderr with a `[story-guard]` prefix.

A sprint or a run of two or more stories also writes `artifacts/sprint-<slug>.pdf`
beside the per-story files. The slug is the iteration path, or the story ids
when the run is not a sprint. Page one lists only the stories in that run. A
story that fails is marked skipped on that page and does not get its own PDF.

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
