# 15 — One narrative call

**Owner:** Gugan (S5)
**Depends on:** [02](02-ollama-qwen.md), [09](09-score-121213.md), [13](13-rubric-prefix-sendable.md)
**Size:** M
**Status:** Done (7 Oct 2026)

## Outcome

`write_narrative` calls Ollama once. The request is the prefix from `prompts/rubric_v1.md`, then the score JSON. JSON mode is on. The request has no tools. Temperature is low and fixed. Invalid JSON retries that call once. A second failure exits without a PDF. The call is not repeated for a rewrite.

This is D10 (`docs/orchestration-and-cost.md` §4.1 and §4.2) and the narrative constraint in `docs/architecture.md` §1.3 and §2.1.

## Done when

- One function, `write_narrative(score) -> dict`, builds one request.
- Request order is prefix text, then the score JSON. The prefix is the return value of `load_prefix()` from slice 13.
- The model is `OLLAMA_MODEL` or the default `qwen3.5:4b`. The host is `OLLAMA_HOST` or `http://127.0.0.1:11434`.
- The request sets `num_ctx` to 8192.
- JSON mode is on (`format` of `json`, or the OpenAI-compatible JSON response format). The parsed body has `headline`, `sections`, and `actions`.
- The payload has no `tools` array, no MCP catalogue, and no tool spec.
- Temperature is a module-level constant, `0.1`. Callers cannot override it.
- If the body is not valid JSON or misses the schema, the function calls Ollama one more time with the same request. If that second response also fails, the function raises. The caller writes no PDF and exits non-zero. Slice 16 owns the process exit. This slice owns the “stop after two attempts” behavior.
- There is no third call. There is no rewrite call that takes QA edits. A schema failure is the only retry, and it retries the same narrative call (`docs/requirements.md` §8.2).
- The function does not change `rag`, counts, or `mapped_ac_ids` on the score. It returns the model’s narrative object beside the original score. Slice 21 is what refuses a narrative whose numbers disagree with the score.

## Work

- Add `src/story_guard/narrative.py`.
- Cap the call the way §4.1 caps a local generate: stop at 8192 tokens or 60 seconds of generation after the weights are loaded, whichever comes first. Cold start is outside the 60 seconds. Exceeding the cap is a failure and follows the same “no PDF” path as a second bad JSON.
- A unit test can stub the HTTP client. One test returns broken JSON twice and asserts exactly two calls and an exception. One test returns broken JSON then valid JSON and asserts the valid body is kept. One test inspects the request body: prefix bytes precede the score, `num_ctx` is 8192, temperature is 0.1, and `tools` is absent.

## Check

```bash
pytest -k narrative
```

The stub tests pass without a running model. A manual run against slice 02’s server is useful and is not the merge check. The merge check is the stub: one success is one POST; a bad payload is two POSTs; a second failure raises and the test’s output path does not exist.

## Out of this slice

A second model, a tool call, a crew, and a rewrite loop. `phi4-mini` is selected by changing `OLLAMA_MODEL` when the default is not resident. This function does not load both.
