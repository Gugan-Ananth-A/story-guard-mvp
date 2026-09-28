# Architecture constraints — rubric cache, tool schemas, context isolation

**Status:** Constraints only (Gugan) — 29 Sep 2026  
**This week:** do not implement caching, a tool registry, or a multi-agent split.  
**Breach:** a generate path that breaks a rule below is a defect, same as a blown token cap.  
**Companions:** `docs/orchestration-and-cost.md` §4 (budget and the 8 GB runtime), `docs/requirements.md` §11 (the one-call graph).

Phase 1 this week stays the graph already locked: Python nodes score the story, one local model call writes the narrative, no tools, one shared score object. This file is the plan for three levers that sit around that call. It is not code, and it is not a second orchestrator.

---

## 1. Prompt caching on the rubric

The health rubric and the output schema are a **stable prefix**. The only bytes that change per story are the score object (and, when a gap needs it, one short quote).

### 1.1 Prefix and suffix

| Part | Contains | Changes per story? |
| --- | --- | --- |
| Prefix | Rubric in force (the kept H-rows and the published RAG rule), the output schema (`headline`, `sections[]`, `actions[]`), and the writer rules in `docs/orchestration-and-cost.md` §4.2 | No |
| Suffix | Score object for this story id. One AC-gap quote only when a specific gap needs it | Yes |

The prefix carries no story id, AC text, test id, bug id, or count. Those live in the suffix.

### 1.2 Stability

- The prefix is byte-stable across every `generate` in a build week.
- A rubric edit bumps `rubric_version` and replaces the whole prefix. It is not a silent edit inside a story prompt.
- Whitespace, key order, and a fresh timestamp inside the prefix count as a rewrite.
- Story fields are never interpolated into the prefix.

### 1.3 This week

Hosted prompt-cache billing does not apply. The development runner is local Ollama on an 8 GB Mac (`docs/orchestration-and-cost.md` §4.5).

The constraint still holds: one system message, or one Modelfile system block, identical for every story. Assemble the request as **prefix, then score JSON**, in that order.

Do not build a cache server, KV-reuse layer, or provider `cache_control` block this week.

### 1.4 When caching is turned on

Turn it on only after the same prefix has been used, unchanged, for the five fixtures.

| Runtime | How the prefix is cached | Still true |
| --- | --- | --- |
| Local Ollama | The runner may reuse a prefix only when the leading bytes match exactly. `num_ctx` stays **8192**. | A miss is acceptable. A hit that contains another story’s facts is a defect. |
| A later hosted model, if D7 ever leaves local | The same prefix is the cacheable block. The score object is not marked cacheable. | Cache the rubric, not the story. |

The 4,096-token target includes the prefix. If the prefix grows until the score object no longer fits, cut the rubric text. Do not raise `num_ctx`.

### 1.5 Done later, not this week

1. Freeze the rubric in one versioned asset. Point the prefix at that version.
2. Keep the request order: prefix, then score JSON.
3. After the five fixtures share one unchanged prefix, enable runner or provider prefix caching.
4. Record cached tokens against fresh tokens. The rubric tokens should stop being re-paid per story. Until that switch exists, the check is simply that the prefix string is identical across runs.

---

## 2. Tool-schema pruning

The narrative node has **no tools** in phase 1. Fetch and scoring already ran in code. A tool list on that call would invite the model to pick another query and to guess a link.

### 2.1 This week

- The narrative request has no `tools` array, no MCP catalogue, and no Ollama tool spec.
- The ADO adapter and the dummy test adapter are Python functions the graph calls **before** the model. The model does not select them.

### 2.2 If a later spike adds tools

That spike re-opens D10, because the narrative call is then no longer one completion. Do not add it in the same week as the first PDF.

Until that decision, the only schemas that may be sent are the two adapter signatures:

| Tool | Argument the model may see | Returns |
| --- | --- | --- |
| `fetch_story` | `story_id` | `StoryRecord` fields the scorer already understands |
| `fetch_tests` | `story_id` | Test rows and the coverage summary |

Bugs ride on the story adapter’s relations. They are not a third tool unless a later contract adds a bug adapter, and that addition is its own decision.

Prune each schema to that shape:

- One JSON schema per tool. No sample payloads, no sibling endpoints, no prose tour of the ADO REST API.
- Drop auth, org URL, API version, and `$expand`. Those are adapter configuration.
- Drop any operation the node must not call: create, update, search-all-stories, wiql.
- Tool results are the same fields the score object already uses. They are not raw `System.*` JSON.
- Two signatures is the ceiling. A longer list is a kitchen-sink catalogue.

### 2.3 Breach

- A `tools` array on this week’s narrative call.
- A schema that includes a PAT, an org URL, or a free-text query parameter.
- A tool whose result the model can treat as a new `mapped_ac`.

---

## 3. Context isolation, only if multi-agent

Phase 1 keeps **one** model context: the score object, with AC rows, test counts, and bugs in the same JSON. The headline is written from that object. Splitting those facts across calls is how an open Sev1 disappears from the header.

Multi-agent is not phase 1 (D10 in `docs/orchestration-and-cost.md`). This section applies only if the reversal test in §6 of that doc is met. It is not a design to build in parallel.

### 3.1 What may be split

Isolation is for **retrieval** when a fixture’s score object no longer fits in 4,096 tokens. It is not a way to split judgement.

| Material | Isolated context allowed? | Must remain in the writer’s score object |
| --- | --- | --- |
| Full test-step text | Yes, and only as retrieval. At most one quote per gap reaches the writer. | Counts by type, mapped test ids, unmapped AC ids |
| Long bug discussion | Yes, as retrieval | Severity, status, age, linked test id, open Sev1 flag |
| A later AC-prose edit | Yes, as a second call under the reversal test | AC ids, testable flag, ambiguity flags, gap labels |
| RAG, headline, action list | No | The published RAG and the counts it was computed from |

### 3.2 Rules that survive a reversal

- A specialist context does not receive raw ADO JSON.
- A specialist does not write `mapped_ac` or a coverage percentage.
- The writer runs last and receives the full score object, not a summary another model wrote.
- Two calls is the ceiling named in the reversal test, at under 2× the single-call tokens. A third context is a new decision.
- On the 8 GB Mac the same resident model runs those calls one after another. A second loaded model does not fit.
- Do not add a supervisor, handoff state, or per-role prompts this week.

### 3.3 Breach

- Separate model contexts for AC, tests, and bugs while D10 still stands.
- A headline whose context omitted open bugs.
- Isolation used so a specialist can infer coverage the explicit links do not show.

---

## 4. This week and later

| Lever | Hold this week | Turn on later only when |
| --- | --- | --- |
| Rubric cache | One identical prefix ahead of the score JSON. No cache product. | That prefix has survived the five fixtures unchanged. |
| Tool schemas | No tools on the narrative call. | D10 is explicitly re-opened, and the list is the two pruned signatures in §2.2. |
| Context isolation | One shared score object. | The reversal test in `docs/orchestration-and-cost.md` §6 has passed, and only retrieval is split. |
