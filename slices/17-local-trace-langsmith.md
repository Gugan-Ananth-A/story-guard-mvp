# 17 — Local trace, LangSmith only when configured

**Owner:** Gugan (S7)
**Depends on:** [16](16-cli-generate.md)
**Size:** S
**Status:** Not started
**Slip:** drop this slice first. If any of it remains, keep the `runs.jsonl` line and drop the LangSmith client.

## Outcome

Every successful `generate` appends one local line with the story id, the token count, and the latency. LangSmith runs only when the key is set. A missing key still produces the PDF. The README says the key is optional.

This is the observability row in `docs/orchestration-and-cost.md` §4.3. A missing key must not block the PDF.

## Done when

- `artifacts/runs.jsonl` gains one JSON line per successful generate.
- The line includes `story_id`, a token count, and a latency. Names can be `story_id`, `token_count`, and `latency_ms`. The token count is the narrative call’s count. Latency is the narrative call, or the whole generate if that is the only clock already in hand; the field name says which.
- With `LANGSMITH_API_KEY` unset, `story-guard generate --story-id 121213` still exits 0 and still writes the report. No LangSmith request is attempted. The jsonl line is still appended.
- With `LANGSMITH_API_KEY` set, the same command creates a LangSmith trace for that run. The local line is still appended.
- The README says the LangSmith key is optional and that the PDF is produced without it.
- The key is read from the environment. It is not written into the jsonl line, the PDF, or the repo.

## Work

- Append the jsonl line at the end of a successful generate. A failed generate (bad id, second narrative failure, missing template) appends nothing, or appends a line whose status is `error` and still contains no secret. Pick one and test it. The success line is the requirement.
- Guard the LangSmith import or client call on a non-empty `LANGSMITH_API_KEY`.
- Document the optional key next to the other environment names in the README.

## Check

```bash
env -u LANGSMITH_API_KEY story-guard generate --story-id 121213
tail -n 1 artifacts/runs.jsonl
```

The command exits 0. The last jsonl line parses as JSON and contains the story id `121213`, a token count, and a latency. A unit test with a stub asserts that an empty key makes zero LangSmith calls and that a set key makes one. The unit test is the merge check for the branch. A live LangSmith project is not required to merge, as long as the stub shows the client is invoked only when the key is set.

## Out of this slice

Evals over the five fixtures, prompt-cache metrics, and blocking the PDF on a trace upload.
