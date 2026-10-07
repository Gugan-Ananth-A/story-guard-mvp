# 02 — Install Ollama and pull qwen3.5:4b

**Owner:** Gugan (S1, D7 runtime)
**Depends on:** [01](01-repo-guard-rails.md)
**Size:** S
**Status:** Not started

## Outcome

The build Mac runs Ollama locally with `qwen3.5:4b` loaded at a context of 8192. A smoke script in the repo gets one JSON object back. The README names the fallback and tells the reader to keep a single model resident.

This is the development runtime locked in `docs/orchestration-and-cost.md` §4.5. The request sets `num_ctx`. The model’s native long window stays unused.

## Done when

- Ollama is running at `http://127.0.0.1:11434`.
- The pulled tag is `qwen3.5:4b` (about 3.4 GB). It is not a 4.5B tag and it is not a 7B tag.
- The smoke request sends `num_ctx` 8192. That value is on the request, not assumed from the Modelfile default.
- `scripts/ollama_smoke.py` calls the local server and prints one JSON object. The process exits 0.
- The README names `phi4-mini` as the fallback (about 2.5 GB, same `num_ctx`) and says to load one model at a time. Pull `phi4-mini` only when the default will not stay resident with the editor open. The smoke script targets `qwen3.5:4b`.

## Work

- Install Ollama and start it on `127.0.0.1:11434`.
- `ollama pull qwen3.5:4b`.
- Add `scripts/ollama_smoke.py`. It posts to the local API with the model name, `num_ctx` 8192, and JSON output. It prints the one object and exits 0. It does not read a story, a fixture, or a PAT.
- Document the fallback in the README in the same terms as §4.5: default `qwen3.5:4b`, fallback `phi4-mini`, one model loaded at a time, context 8192.

## Check

```bash
curl -sf http://127.0.0.1:11434/api/tags
python scripts/ollama_smoke.py
```

The tags list includes `qwen3.5:4b`. The smoke script prints a single JSON object and exits 0. A reader of the script can see `8192` on the request options. The README contains `phi4-mini` and a line that one model is loaded at a time.

## Out of this slice

The narrative prompt, retries, and the generate graph. Slice 15 is the one product call. This slice only proves the runner answers.
