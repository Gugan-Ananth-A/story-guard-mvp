# 18 — Publish the expected counts

**Owner:** Thabitha (S8)
**Depends on:** [05](05-fix-121213.md), [09](09-score-121213.md)
**Size:** S
**Status:** Not started

## Outcome

`fixtures/FIX-121213.md` is the page a reader uses to check the PDF. They can do that without opening Azure DevOps.

The numbers are the ones `score_health` emits for this fixture. If the page and the scorer disagree, the fixture or the scorer is wrong. The page is not a second score.

## Done when

`fixtures/FIX-121213.md` lists these facts, in words a reviewer can match by eye:

| Fact | Value |
| --- | --- |
| AC field | empty |
| Scenarios | 8 |
| Tests | 18 |
| Mapped | 0 |
| Bugs | 0 |
| RAG | Red |
| Rule ids | SR-1 and SR-2 |

- The page says SR-2 is the rule that sets Red, and that SR-1 is the rule that an empty `mapped_ac_ids` covers nothing.
- The page points at `fixtures/FIX-121213.json` and at `docs/rag-stand-in.md`.
- The page says the button-disabled contradiction is a note and is not a mapping.
- The page does not tell the reader to sign in to Azure DevOps to verify these counts.

## Work

Write the markdown page. Keep it to a single screen. Slice 19’s test asserts the same numbers from the scorer, so this page and that test are the two public copies of one result.

## Check

```bash
rg -n "empty|8|18|Red|SR-1|SR-2" fixtures/FIX-121213.md
```

A reader can find each row of the table. The file mentions mapped 0 and bugs 0 explicitly, not only as a subtraction the reader has to do.

## Out of this slice

Expected-count pages for the other four personas. Those fixtures are not in this sprint.
