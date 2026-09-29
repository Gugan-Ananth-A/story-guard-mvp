# 12 — Dummy test adapter

**Owner:** Thabitha (S3)
**Depends on:** [04](04-fixture-field-names.md), [05](05-fix-121213.md)
**Size:** S
**Status:** Not started

## Outcome

The test adapter loads tests only from `fixtures/FIX-121213.json`. It returns the 18 rows with their ids, titles, and empty `mapped_ac_ids`. The graph’s `fetch` uses this adapter for tests. Azure Test Plans is not a source (`docs/requirements.md` §4 and §6.1).

## Done when

- One module, `src/story_guard/tests_adapter.py` (or a name as clear), exposes a function that takes a story id and returns the test rows.
- For `121213` it returns 18 rows. Ids are `121216` through `121233`. Titles match the fixture. Every `mapped_ac_ids` is `[]`.
- Any other story id returns an empty list or a typed “no pack” result that the caller can tell from a crash. It does not invent tests (gate G5, still disputed, treats a missing pack as empty coverage).
- The rows are TestCase records from `fixtures/SCHEMA.md`.
- A search of this module shows no `dev.azure.com` Test Plans URL and no `/_apis/test` path. The module opens the fixture file and nothing else.

## Work

- Read `tests` out of `fixtures/FIX-121213.json`.
- Call the adapter from `fetch` once slice 10’s graph exists. If slice 10 has not merged, the adapter is still done when its unit test passes; wiring into `fetch` is the last edit of this slice and blocks slice 16.

## Check

```bash
pytest -k tests_adapter
rg -n "dev.azure.com|_apis/test|testplan" src/story_guard/tests_adapter.py
```

The test asserts 18 ids, the titles, and empty `mapped_ac_ids`. The search prints nothing.

## Out of this slice

A live Test Plans client, coverage percentages, and filling in `type` from the `P` / `N` / `A` prefix.
