# 22 — Prove the prefix is stable

**Owner:** Valliammai (S4)
**Depends on:** [13](13-rubric-prefix-sendable.md), [16](16-cli-generate.md)
**Size:** S
**Status:** Not started

## Outcome

Two generates record the same prefix hash. The bytes that were hashed contain no story id. The check is a test, not a manual diff.

This is the build-week form of `docs/architecture.md` §1.2 and §1.5. Caching stays off. The prefix string is what must be identical.

## Done when

- Each successful generate records the prefix hash beside the run (a field on the `artifacts/runs.jsonl` line, or a field the test reads from the graph state). If slice 17 was dropped, this slice still records the hash in the jsonl line or in an equivalent one-line log the test can read. The hash has to be observable outside the process.
- The hash input is the prefix string from `load_prefix()` (the file `prompts/rubric_v1.md`). The story id, the score JSON, and the narrative are not part of the hashed bytes.
- A test runs the generate path twice for story `121213` (the narrative client may be stubbed) and asserts the two recorded hashes are equal.
- The same test asserts that the hashed string does not contain `121213`.
- Changing the score between the two runs, if the test does that with a stub, does not change the hash. The prefix is independent of the suffix.

## Work

- Hash with SHA-256 of the prefix bytes, encoded the same way on every run (UTF-8, the file’s own newlines, no extra timestamp).
- Record the hex digest on the run line under `prefix_sha256`.
- Extend `tests/test_prefix_hash.py` or add `tests/test_prefix_stable.py`. Slice 13’s double-read of the file stays. This slice adds the two-run assertion.

## Check

```bash
pytest tests/test_prefix_stable.py
```

The test fails if a story id is interpolated into the prefix, and it fails if the two runs record different digests.

## Out of this slice

Turning on Ollama prefix caching or a hosted cache. That waits until the same prefix has covered the five fixtures (`docs/architecture.md` §1.4), which is outside this sprint.
