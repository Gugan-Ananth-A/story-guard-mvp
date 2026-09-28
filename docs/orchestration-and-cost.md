# D6 / D10 — Orchestration decision and cost constraints

**Status:** Proposed lock (Gugan, tie-break) — 29 Sep 2026  
**Decisions:** D6 (orchestrator), D10 (single vs multi-agent), D7 development runtime (local model on an 8 GB Mac)  
**Risk owned here:** R4 (multi-agent token blow-up)  
**Companion:** `docs/requirements.md` §11 and TBD-ARCH-1 / TBD-ARCH-3  
**Reversible:** yes, if a build-week spike proves a specialist crew earns its tokens on the five fixtures. Default does not change without that evidence.

---

## 1. The decision (read this first)

| ID | Question | Choice | Why in one line |
| --- | --- | --- | --- |
| **D10** | Single agent vs multi-agent crew | **Single pipeline.** Deterministic code does the scoring. **One** LLM writes narrative around those facts. | Phase 1 is assemble-and-explain, not breadth-first research. A crew pays 3–15× tokens and adds handoff loss for work the scorecard already specifies. |
| **D6** | Orchestrator | **LangGraph** as a *workflow graph of code nodes*, not as a supervisor of specialist LLMs. | Durable state, later HITL interrupts, traces. CrewAI is rejected for phase 1 because its native unit is a role-crew. |
| **D7 dev** | Where the one narrative call runs during development | **Local model on an 8 GB Mac.** Ollama. Default Qwen3.5 4B, fallback Phi-4 Mini. Context loaded at 8,192. | That is the whole RAM budget once macOS and the editor are open. A hosted model, or a 7B+ checkpoint, is not the dev default. §4.5. |

**What we will build**

```
generate --story-id XXX
        │
        ▼
 [LangGraph state machine — mostly Python, one LLM node]
        │
        ├─ gate_input          hard stops, no model
        ├─ fetch_story         ADO adapter
        ├─ fetch_tests         dummy TMS adapter
        ├─ fetch_bugs          ADO relations / dummy
        ├─ validate_contract   schema check, no model
        ├─ score_health        H1–H11 in code, no model
        ├─ write_narrative     ONE structured LLM call over the score object
        └─ render_pdf          markdown template → PDF
        │
        ▼
 QA reviews the PDF, then shares
```

**What we will not build in phase 1**

- A CrewAI (or LangGraph-supervisor) crew of parser / AC auditor / coverage analyst / bug correlator / report writer, each with its own prompt and context.
- An LLM that invents coverage percentages, test lists, or AC↔test maps.
- A second orchestrator “just in case.”
- A hosted narrative model, or a second model resident beside the writer, on the development Mac.

---

## 2. Why the specialist roles do not need specialist models

The Thursday prompt mapped cleanly onto a crew:

| Imagined role | What it actually does in phase 1 | Owner in this design |
| --- | --- | --- |
| Parser | Turn ADO / fixture JSON into `StoryRecord` | Adapter (code) |
| AC auditor | Present / testable / ambiguous | Scorer (code + flags on the fixture) |
| Coverage analyst | Mapped vs gap, by type | Scorer (explicit `mapped_ac_ids` only) |
| Bug correlator | Open / severity / age | Scorer (code) |
| Report writer | Headline, narrative, actions | **LLM, once**, over the score object |

Those roles are real. They are not reasons to pay for five contexts.

Phase 1 inputs are small and already structured: one story, a handful of ACs, a handful of tests, a handful of bugs. That is not the task class multi-agent systems are for.

Anthropic’s own guidance, and the paper the week-2 shortlist pointed at, is consistent on when a crew earns its keep:

- The task is **breadth-first** and splits into independent directions that would overflow one context window (research, many sources).
- Subtasks produce a lot of tokens the parent must **not** see (context isolation).
- Specialists materially improve **tool selection** on disjoint toolboxes.

None of those are true here:

- Directions are not independent — AC, tests, and bugs must be read together to write one headline.
- Context is small. Isolation would *throw away* the shared picture QA needs.
- There are two tools (ADO adapter, dummy TMS), both deterministic fetches. No tool zoo.

On Anthropic’s published research-system numbers, agents run about **4×** a chat and multi-agent systems about **15×** a chat; token spend explained most of the quality lift. Independent write-ups of the same note put typical multi-agent overhead at **3–10×** a single agent for the same task. A matched-budget comparison on multi-hop reasoning found a single agent *ahead* of sequential / role / debate crews once tokens were equalised. That is the pattern we would be buying if we staffed five LLM specialists for a scorecard we can compute with counters. lemme cite those sources in the rejected table below.

A false “covered” AC is worse than a false “uncovered.” Giving an AC-auditor agent freedom to *infer* mapping is how that failure mode appears. Traceability law in `docs/requirements.md` §6.4 forbids it. Code cannot “guess a link”; an LLM can.

---

## 3. Why LangGraph and not CrewAI (or “no framework”)

| Option | Verdict | Why |
| --- | --- | --- |
| **LangGraph** (workflow graph) | **Chosen** | Phase-1 graph is almost linear, but we already know later-phase HITL, retries, and “run died halfway” will show up. Checkpoints and interrupts are the reason the week-2 shortlist preferred LangGraph over a thinner SDK. Nodes can be plain Python. Only `write_narrative` talks to a model. |
| **CrewAI** (roles / crew) | Rejected for phase 1 | Fastest way to encode the five specialist names — and therefore the fastest way to accidentally ship R4. Revisit only if the five fixtures prove one narrative call cannot write a trustworthy section. |
| **PydanticAI / OpenAI Agents SDK** | Rejected as *primary* | Fine thinner single-agent hosts. They do not give us durable runs or a later interrupt without adopting a second framework (non-goal: no dual-track). |
| **Plain functions, no framework** | Honourable mention, not the lock | A 80-line `generate()` is enough for the first spike. If LangGraph adds friction on day one, implement the pipeline as functions *behind* a graph façade and keep the node list identical. Do not start a second design. |

LangGraph here means **control flow**, not **a crew**. A supervisor node that delegates to four LLM specialists is the thing this decision forbids, even if it is drawn in LangGraph.

---

## 4. Cost constraints (bind the build week)

These are constraints, not a bake-off. Put them in `docs/architecture.md` and treat a breach as a defect.

### 4.1 Budget

| Constraint | Phase 1 rule |
| --- | --- |
| LLM calls per successful `generate` | **1** (narrative). Gates, fetch, schema, score, render = zero calls. |
| Exception | A second call is allowed only for *narrative rewrite after QA edit*, which is later-phase HITL — not phase 1. |
| Where that call runs in development | Local runtime in §4.5. No hosted API key is required to generate a PDF. |
| AC splitting | Deterministic (newlines / numbering / fixture-provided list). Not an LLM parse. Matches risk R2 mitigation. |
| Context loaded | **8,192** tokens (`num_ctx`). Do not load the model’s native 128k-class window. The KV cache would swap an 8 GB Mac. |
| Target tokens per report | **≤ 4,096** total (rubric + score object + completion). |
| Hard cap per report | **8,192** tokens or **60 s** of generation after the weights are loaded, whichever first. Exceed → fail closed, no PDF. Cold download and the first load are outside the 60 s. |
| Hard cap per day (dev) | No provider bill. A looping graph that swaps the Mac is a defect. Do not raise `num_ctx` to fit a fat prompt. |

The 4,096 target is the whole narrative call on this machine. If a fixture’s raw ADO blob is being stuffed into the prompt, the design is wrong — shrink the payload, do not raise the cap. The earlier 20,000-token hosted ceiling does not apply while development runs locally.

### 4.2 What the model is allowed to see

The narrative node receives a **score object**, not source-system JSON.

Include:

- story id, title, type, state
- discrete AC list with testable / flags already computed
- per-AC linked test ids and gap labels already computed
- coverage-by-type counts already computed
- bug list with severity, status, age, linked TC already computed
- overall RAG **already decided by the published rule**
- recommended-action *slots* the writer may phrase, not invent

Exclude:

- raw `System.*` ADO fields
- full test step text unless a specific AC gap needs a quote
- PAT, org URL internals, `.env`
- any instruction that says “if a test looks related, count it”

The model may:

- write the headline in the voice of the expected fixture headline
- write short section prose that **cites the counts**
- phrase the 3–7 actions with owner roles

The model may not:

- change the RAG
- add or drop a test, AC, or bug
- emit a coverage percentage that is not on the score object
- populate `mapped_ac`

If the writer disagrees with a count, that is a scorer bug or a fixture bug — not a prompt tweak.

### 4.3 Caching, schemas, traces

| Lever | Rule |
| --- | --- |
| Prompt prefix | The health rubric + output schema are a stable system prefix (Modelfile or the request’s system message). Do not rewrite the rubric per story. Hosted prompt-cache billing does not apply in dev. |
| Tool schemas | Narrative node has **no tools** in phase 1. If a later spike adds tools, pass only the two adapter signatures, not a kitchen-sink MCP catalogue. |
| Structured output | The local runner’s JSON mode (or a JSON schema) constrains the one call. The body must still match `headline`, `sections[]`, `actions[]`. Invalid JSON → retry once → fail closed. |
| Observability | Record token count and latency on every `generate` locally. LangSmith is the eval hook when a key is configured. A missing key must not block the PDF. |
| Context isolation | Do **not** isolate AC / tests / bugs into separate LLM contexts in phase 1. Isolation is how the headline loses the P1 bug. If a later report grows past the 4,096-token target because fixtures got huge, isolate *retrieval*, not *judgement*. |

### 4.4 Unit-economics sanity check

Illustrative, using Anthropic’s published multipliers (agents ~4× a chat, multi-agent ~15× a chat) — not a price quote.

| Shape | What we would run | Relative token bill | Fits phase 1? |
| --- | --- | --- | --- |
| One structured completion over a score object | D10 choice | ~1× a short chat | Yes |
| Single ReAct agent with tools looping on the raw work item | “just add an agent” | ~4× | No — we already fetched and scored in code |
| Supervisor + 4 specialist LLMs | CrewAI-shaped design | ~3–15× | No — R4 |

QA will generate reports one story at a time, a few times a day. A 15× crew does not make the PDF more shareable. On this Mac it also does not fit: a second resident model, or a 7B checkpoint with a long context, swaps an 8 GB machine.

### 4.5 Development runtime (8 GB Mac)

Development runs on a Mac with **8 GB** of unified memory. macOS, the browser, and the editor share that RAM, so the weight budget is about **4 GB**, not 8.

| Item | Choice |
| --- | --- |
| Runner | **Ollama**, OpenAI-compatible API at `http://127.0.0.1:11434/v1`. No API key. |
| Default | **Qwen3.5 4B**, tag `qwen3.5:4b`, about 3.4 GB. |
| Fallback | **Phi-4 Mini**, tag `phi4-mini`, about 2.5 GB. Same `num_ctx`. Use it when the default will not stay resident with the editor open. |
| Context | `num_ctx` **8192** on whichever tag is loaded. |
| Out | 7B–12B checkpoints (about 5–7 GB). They fit a discrete 8 GB GPU. They do not fit this Mac while a person is working. A hosted model is not a second dev stack. |

If an Ollama tag moves, keep the size class (weights at or under about 3.5 GB). Do not step up to a 7B to chase quality. One model loaded at a time.

---

## 5. Decision log rows (paste into the workbook)

| ID | Decision | Choice | Why | Rejected | Date | Owner | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| D6 | Orchestrator | LangGraph as a code-node workflow | Durable state, later HITL, traces; nodes are Python; only one node is an LLM | CrewAI as primary; dual-track LangGraph+CrewAI; PydanticAI / Agents SDK as primary | 29 Sep 2026 | Gugan | Proposed lock |
| D10 | Single vs multi-agent | Single pipeline: code scores, one LLM narrates | Task is small, shared-context, deterministic; crews cost 3–15× and invite guessed mappings | Parser+auditor+analyst+correlator+writer crew; supervisor-of-specialists in LangGraph | 29 Sep 2026 | Gugan | Proposed lock |
| D7 | Development narrative model | Local Ollama on an 8 GB Mac. Default `qwen3.5:4b`. Fallback `phi4-mini`. `num_ctx` 8192. | The build machine has 8 GB shared with the OS and the editor. One call over a compact score object is what fits. | Hosted API as the dev default; 7B+ checkpoints; loading two models; native 128k context | 29 Sep 2026 | Gugan | Proposed lock |

Rejected options, one line each (Overview stack table):

| Option | Why rejected |
| --- | --- |
| CrewAI specialist crew in phase 1 | Encodes R4 as the default. Roles are real; they belong to adapters and the scorer. |
| LangGraph supervisor + LLM subagents | Same cost shape as CrewAI, different drawing. |
| Dual-track CrewAI *and* LangGraph | Week-2 non-goal. |
| “The model *is* the scorecard” | QA will not share a mood. Counts live in code (B4). |
| Hosted model, or a 7B+ local model, as the dev default | Does not run beside the OS and the editor in 8 GB. |
| Mid-flow HITL inside the graph | Parked. Phase 1 HITL is after the PDF exists. |

---

## 6. What would reverse this lock

Re-open D10 only if **all** of the following are true after the five fixtures run through B4+B5:

1. The deterministic scorer is trusted (counts match the fixture README).
2. A single narrative call still produces sections QA will not share, **and** the failure is role-confusion (AC prose bleeding into bug advice) rather than a missing fact on the score object.
3. A two-call experiment (e.g. AC-prose editor + report writer) beats one call on the eval headlines at **< 2×** tokens.
4. Gugan records the reversal in the decision log the same day.

A desire to “look more agentic” in a demo is not a reversal criterion.

---

## 7. Build-week implications

| Backlog seed | Change under this lock |
| --- | --- |
| B4 Deterministic scoring engine | Unchanged. This is the product. |
| B5 Narrative writer | One structured call to the local model in §4.5. Prompt = stable rubric prefix + score JSON. `num_ctx` 8192. JSON mode. No tools. |
| B7 CLI `generate --story-id` | Thin graph invoke, or functions with the same node list. |
| B8 Eval on 5 fixtures | Assert headlines and RAG from the **engine**, then that the prose cites those numbers. Do not eval “does the crew sound like QA.” |
| Architecture diagram | Replace the Web UI / API / DB drawing with the graph in §1. |

---

## 8. Sources used for the cost argument

Internal week-2 notes already required this decision to look at Anthropic’s agent-design and multi-agent-cost write-ups. The figures cited above:

- Anthropic Engineering, *How we built our multi-agent research system* (Jun 2025): agents ~4× a chat, multi-agent ~15× a chat; +90.2% on an internal research eval vs single-agent Opus; token usage explained most of the variance. That task class is breadth-first research, not a 1-story scorecard.  
- Anthropic, *When to use multi-agent systems*: crews typically 3–10× tokens; wins when context pollution, parallelism, or disjoint toolboxes are real; many teams would have been fine with a better single-agent prompt.  
- Matched-budget follow-ups (2026): once tokens are equalised, a single agent is often even or ahead on multi-hop reasoning — i.e. a lot of the crew lift *is* the extra spend.

We are not claiming those papers measured user-story health reports. We are claiming our task does not look like the task they paid 15× to solve.


