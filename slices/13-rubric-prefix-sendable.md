# 13 — Finish the prefix so it can be sent

**Owner:** Valliammai (S4)
**Depends on:** [08](08-rubric-prefix-start.md)
**Size:** S
**Status:** Not started

## Outcome

`prompts/rubric_v1.md` is the exact prefix the narrative call will send. A unit test reads it twice and the hashes match. Slice 15 concatenates this file with the score JSON and does not assemble a second prompt.

`docs/architecture.md` §1.1: the prefix holds the rubric, the output schema, and the writer rules. The score object is the suffix. The prefix carries no story id.

## Done when

- The prefix file still has `rubric_version`, the output schema (`headline`, `sections`, `actions`), and the §4.2 rules.
- The rules that this call depends on are explicit in the file, in words the model is given:
  - Cite the counts on the score object, including the story health and the Adequate / Partial / None counts.
  - Do not invent coverage. Do not populate `mapped_ac`. Do not emit a percentage that the score object does not already contain. Do not change the story health. Do not write "partially covered".
- A unit test reads the file, hashes the bytes, reads the file again, and asserts the two hashes are equal.
- The hashed bytes are the file contents. The test does not format the prefix with a story id, a title, or a count before hashing.
- A search of the file still finds no `121213`, no `SNAP`, and no test id.

## Work

- Edit `prompts/rubric_v1.md` in place. Do not add `prompts/rubric_v1_121213.md` or a per-story copy.
- Add `tests/test_prefix_hash.py` with the double-read hash. Slice 22 extends this area with a two-run check. This slice’s test hashes the file, not a generate run.
- Export one function, `load_prefix() -> str`, that returns the file text. Slice 15 and slice 22 call it. No other function formats that string with story fields.

## Check

```bash
pytest tests/test_prefix_hash.py
rg -n "121213|SNAP" prompts/rubric_v1.md
```

The test passes. The search prints nothing.

## Out of this slice

A cache server, `cache_control`, and a Modelfile. Hosted prompt-cache billing does not apply this week (`docs/architecture.md` §1.3). The check is that the prefix string is stable.
