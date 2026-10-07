# 08 — Start the rubric prefix

**Owner:** Valliammai (S4)
**Depends on:** nothing. Slice 13 finishes the same file.
**Size:** S
**Status:** Not started

## Outcome

`prompts/rubric_v1.md` exists. It is the stable prefix described in `docs/architecture.md` §1: rubric version, writer rules, and the output schema. It has no story in it.

The prefix is not sent to a model in this slice. Slice 13 makes it sendable. Slice 15 places it ahead of the score JSON.

## Done when

- The file is `prompts/rubric_v1.md`.
- It contains a `rubric_version` string. Use `rubric_v1` unless the file names a different version on the first line, in which case that is the version and the filename follows it. This sprint uses `rubric_v1`.
- It contains the may / may-not rules from `docs/orchestration-and-cost.md` §4.2, in the model’s voice:
  - The model may write the headline, write short section prose that cites the counts, and phrase 3–7 actions with owner roles (QA / Dev / PO).
  - The model may not change the story health, rewrite a row's depth, gap, or row status, add or drop a test, an AC, or a bug, emit a coverage percentage that is absent from the score object, write "partially covered", or populate `mapped_ac`.
- It contains the output schema the runner will require: `headline`, `sections`, `actions`. `sections` is an array. `actions` is an array of 3–7 items with an owner role.
- No sentence is about a particular story. The file has no story id, no story title, no AC text, no test id, and no count from 121213.

## Check

```bash
rg -n "rubric_version|headline|sections|actions|mapped_ac" prompts/rubric_v1.md
rg -n "121213|SNAP|AC-1|121216" prompts/rubric_v1.md
```

The first search shows the version, the schema names, and the mapping rule. The second search prints nothing.

## Out of this slice

The hash test (slice 13), the Ollama call (slice 15), and any story-specific example inside the prefix. Examples of the JSON shape use placeholder keys, not 121213’s numbers.
