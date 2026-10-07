# User Story Health Agent — Requirements Pack (Phase 1)

**Status:** Freeze draft (Gugan) — 29 Sep 2026  
**Revision:** 29 Sep 2026 — dummy story **121213** recorded in §6.2. D6/D10 and the 8 GB local runtime (D7) are proposed-locked in `docs/orchestration-and-cost.md`. Rubric-cache, tool-schema, and context-isolation constraints are in `docs/architecture.md` (not built this week). PDF library D8 is locked in `docs/pdf-library.md`.
**Revision:** 7 Oct 2026 — phase 1 takes the single-story parts of `Story_Guard_Report_2_Banking.pdf` (Desktop). Story health follows that PDF’s highest-open-bug rule. Coverage is a separate table. The portfolio pages, the charts, and the coverage percentages stay later. The 29 Sep 2026 revision still stands: dummy story **121213** is recorded in §6.2. D6/D10 and the 8 GB local runtime (D7) are proposed-locked in `docs/orchestration-and-cost.md`. Rubric-cache, tool-schema, and context-isolation constraints are in `docs/architecture.md` (not built this week). PDF library stays open.  
**Sprint window this pack covers:** Week 2 planning (25–28 Aug 2026) + close-out  
**Repo:** https://github.com/Gugan-Ananth-A/story-guard-mvp  
**Companion workbook:** `Story Guard - Week 2 - User Stories & Setup.xlsx`  
**Metrics draft:** `Story guard - Metrics Report.xlsx`  
**Dummy-data rule:** no live team project, no production agent loop this pack.

This document freezes the problem, users, phase-1 boundary, data sources, scorecard *intent*, generation gates, and phase map.  
D6 (orchestrator), D10 (single pipeline), and the development runtime (D7: local model on an 8 GB Mac) are a **proposed lock** in `docs/orchestration-and-cost.md`. PDF library D8 is locked in `docs/pdf-library.md` (TBD-ARCH-2).

---

## 1. Problem

QA currently spends too long stitching together a picture of whether a user story is healthy:

- whether acceptance criteria are present and testable,
- whether tests map to those acceptance criteria,
- whether coverage includes more than the happy path,
- whether open or failing bugs still sit against the story.

That work is slow, inconsistent, and easy to miss when the source data lives across Boards, tests, and bugs.

Phase 1 of the User Story Health Agent should:

1. take a single Story ID,
2. assemble those signals from dummy Azure DevOps story/bug data plus a dummy test pack,
3. apply published gates and a scorecard,
4. produce a PDF health report that a QA can review and share with confidence.

It is not a live production agent in this pack, not a sprint dashboard, and not a multi-tool SaaS platform.

---

## 2. Users and jobs-to-be-done

| Job | Role | What they do once the PDF exists |
| --- | --- | --- |
| **Generate** | QA (primary); PM/DM may request | Runs the report for one story. First look: did it render, does it look complete. |
| **Validate** | QA | Cross-checks the report’s AC, test, and bug claims against source data before trusting the verdict. |
| **Share** | QA → Developers / PM / Leads / DM / BA | QA sends it out. Developers fix the attributed bug or missing-test gap. PM raises Critical / At-Risk stories in stand-up. Leads use the roll-up as go/no-go evidence. BA rewrites requirements only when AC is untestable or ambiguous. |

**Primary operator:** QA.  
**Secondary readers:** developers, SM / leads, PM / DM, BA (ambiguous-AC findings only).

How QA said they would use it (Tue walkthrough):

- Bug section is what gets shared feature- or sprint-wise with PM / DM.
- Coverage section is what QA uses to see missing cases and update tests.
- Report must be trustworthy enough to forward; untrustworthy counts are worse than a thin report.

---

## 3. Phase map

### 3.1 Phase 1 (this product slice)

| Item | Phase 1 decision |
| --- | --- |
| Working name | User Story Health Agent (planning name only) |
| Input | One Azure DevOps work-item / Story ID |
| Data | Dummy stories, AC, tests, coverage, bugs only |
| Output | A PDF health report |
| Who runs it | QA generates, checks, then shares |
| Human in the loop | After generation only |
| Gates | Hard checks must pass before a PDF is produced (bad ID, wrong type, broken contract → no PDF) |
| Health model | Story health from the highest open bug, as in the banking PDF. Coverage is a separate table. Neither comes from model mood. |
| Source shape | ADO Boards for story + bugs; tests/coverage behind a dummy adapter so the source can be swapped later |
| Traceability | Explicit `mapped_ac` / linked TC IDs only. No LLM-guessed mapping as source of truth. |

What phase 1 actually does:

> Take a Story ID → assemble AC quality, test mapping, coverage types, and linked bugs → score them deterministically → wrap a short narrative around those facts → hand QA a shareable PDF.

### 3.2 Out of phase 1 / later SaaS

Parked. Must not leak into build-week stories.

| Item | Later option |
| --- | --- |
| Working name | May become a named SaaS product |
| Input | Full story text, bulk IDs, Jira, CSV upload, Slack, sprint |
| Output | ADO comment, dashboard, Slack/Teams, HTML app, JSON API as the primary product |
| Human in the loop | Mid-flow approval, edit-in-place |
| Gates | Soft warnings only, still generate |
| Health model | Configurable scorecards per org |
| Data | Live ADO + Test Plans / other TMS; adapter hides the source |
| Access | MCP wrapper around ADO + TMS |
| Observability / evals | LangSmith (or similar) judging report quality on the fixture set |
| Other | Billing, orgs, Jira as source of truth, inventing tests or coverage % the fixture did not contain |

---

## 4. Non-goals

Tighter than phase 1. This pack is documents + contracts + static mocks, not shipping software.

- No production-form agent loop (no parser → auditor → writer pipeline that “is the product”).
- No live project connection. Dummy org / fixtures only. Never point code at a real delivery board.
- No pixel-perfect PDF engine in the planning week. Static mock PDF or formatted doc that shows section order. Rendering library is a stack decision, not a design debate.
- No model bake-off. Development default is **Qwen3.5 4B** via Ollama; fallback is **Phi-4 Mini**. Both fit an 8 GB Mac. Context loaded at 8,192. See `docs/orchestration-and-cost.md` §4.5.
- No Azure Test Plans dependency. JSON / SQLite dummy store is the default.
- No dual-track orchestrators. Proposed lock: **LangGraph** as a graph of code nodes, and **one** narrative LLM call. CrewAI, and a LangGraph supervisor over specialist models, are out of phase 1 (`docs/orchestration-and-cost.md`).
- No scope leaks into Slack / Jira / dashboards / billing / mid-flow HITL.

---

## 5. In / out / later (phase 1 boundary)

| | In phase 1 | Out / later |
| --- | --- | --- |
| Input | One Story ID | Bulk IDs, pasted story text, CSV, Slack, Jira, sprint |
| Output | PDF (markdown-first, then render) | ADO comment, dashboard, Slack/Teams, HTML app, JSON API as the product |
| Data | Dummy ADO story + bugs + dummy test pack | Live ADO, live Test Plans, any real team project |
| HITL | QA review after the PDF exists | Approve-each-section, edit-in-place while the agent runs |
| Scoring | Deterministic engine on fixture/adapter fields | Model-only “health vibe”, including an AI judgement of “partially covered” |
| Mapping | Explicit links in dummy data | Embedding / LLM-guessed AC ↔ test mapping as truth |
| Coverage numbers | Counts computed from `mapped_ac_ids` and test `type` | Invented by the model, including a coverage percentage the score does not contain |
| Report | One story: bug health, AC coverage table, bug table, actions, raw-id appendix | Portfolio summary, multi-story overview, charts, average coverage % |
| Operator | Local CLI / script QA can run | Multi-tenant SaaS |
| Orchestration | LangGraph code-node graph; code scores; one narrative call | CrewAI crew, supervisor of specialist LLMs, a second orchestrator |
| Narrative model (dev) | Local Ollama on an 8 GB Mac: Qwen3.5 4B, fallback Phi-4 Mini, context 8,192 | Hosted API, a 7B+ model, a second model loaded beside the writer |

---

## 6. Data sources

### 6.1 Strategy

| Layer | Choice | Why | Limitation | Owner |
| --- | --- | --- | --- | --- |
| Stories + AC + bugs | Azure DevOps Boards | Matches the intended source; REST API exists; 5 Basic users are free | Agile AC field is a long text blob, not structured bullets | Gugan / Thabitha |
| Test cases + coverage | Dummy store (JSON in repo, or SQLite) behind an adapter | Test Plans is paid after a 30-day trial — must not block phase 1 | Will not look like the Test Plans UI | Rithika / Thabitha |
| Access layer | Thin adapter interface + dummy implementation | Swap dummy → live ADO / other TMS later without rewriting the agent | Contracts must exist before build-week code | Thabitha |
| Auth for spike | ADO PAT on the dummy project only | Enough to answer “can we fetch a work item by ID?” | PAT is a secret — `.env`, never committed | Valliammai |

### 6.2 Current dummy project (as of close-out)

Read 29 Sep 2026 from the signed-in Ecom MVP session (`api-version=7.1`, work item `$expand=relations`, test plan / suite / test points). No PAT was stored. Anonymous calls still redirect to sign-in.

| Decision | Recorded fact |
| --- | --- |
| Planned | New free ADO org + Agile project + sample User Story + linked Bug |
| Actual | Reusing **Ecom MVP**: `https://dev.azure.com/rootquotient/Ecom%20MVP` |
| Story | **121213** [SNAP Login Screen](https://dev.azure.com/rootquotient/Ecom%20MVP/_workitems/edit/121213). User Story, state **New**, reason New, rev 3. Priority 2. Value area Business. Area **Ecom MVP**. Iteration **Ecom MVP\Ecom phase 2.1 release\Story Guard - AI Agent**. Assigned to Vignesh Balakrishnan. Created 2026-09-28, changed 2026-09-28. 0 comments. Story points and risk are unset. |
| AC field | `Microsoft.VSTS.Common.AcceptanceCriteria` is **absent** on the payload (empty). The scenarios are in `System.Description`. |
| Links on the story | **None.** No parent, no bug, no Tested By. |
| Tests | Plan **121214** [Story Guard - AI Agent](https://dev.azure.com/rootquotient/Ecom%20MVP/_testPlans/execute?planId=121214&suiteId=121215), state Active, same area and iteration, 28 Sep 2026–30 Nov 2026, owner Vignesh Balakrishnan. One suite only: root suite **121215**, type **staticTestSuite**, configuration Windows 10. 18 test cases, 18 points, **0% run** (outcome `unspecified`, result state `ready`). |
| Links on the tests | **None** on 121216–121233. The title prefix `AUTH-102065` is not a work item in this project (GET 102065 returns 404). |

**TBD-DATA-1** (Gugan + Thabitha): the sample is read. Still decide whether H1 reads `Microsoft.VSTS.Common.AcceptanceCriteria` only, or also `System.Description`, because on 121213 the first is empty and the second holds the scenarios. This story has **no bug**; a separate work item is still required if H8/H9 need a non-zero example. Do not score the 18 tests as AC coverage until a human writes `mapped_ac_ids`. Do not mix these IDs with STORY-101 / FIX-* until that map exists.

#### 6.2.1 Story 121213 — description scenarios

User voice in the description: as a registered user, log in with email and password to reach the SNAP account. Background: the user is on the “Login to SNAPS” page.

The AC-n labels below are for this pack only. They are not stored on the work item.

| Pack label | Scenario in `System.Description` | Expected result written on the story |
| --- | --- | --- |
| AC-1 | Successful login with valid credentials | Authenticated and redirected to the SNAP dashboard / home page |
| AC-2 | Empty email field | Login button stays disabled or inactive |
| AC-3 | Empty password field | Login button stays disabled or inactive |
| AC-4 | Invalid email format (example `user@domain`) | Inline validation error; user stays on the login page |
| AC-5 | Unregistered email, or valid email with the wrong password | Invalid-credentials error; user stays on the page; password field is cleared |
| AC-6 | Show / Hide on the password field | Plain text, then masked again |
| AC-7 | Forgot Password? | Redirect to the password recovery page |
| AC-8 | Either required field empty | Login button stays disabled or inactive |

AC-2, AC-3, and AC-8 say the button cannot be clicked when a field is empty. Tests **121217**, **121218**, and **121219** say the tester clicks Login and sees inline validation errors. That contradiction is part of the dummy data. The report should surface it. It is not a license to guess a mapping.

#### 6.2.2 Suite 121215 — 18 test cases

Every case is type Test Case, state **Design**, priority 2, automation **Not Automated**, configuration Windows 10, tester Vignesh Balakrishnan. Each has steps on `Microsoft.VSTS.TCM.Steps`. None has a last completed result. None links to 121213 or to a bug.

The P / N / A prefix is the author’s label. It is not the happy / negative / edge / security / adhoc field H5 and H6 need.

| ID | Title | Author prefix |
| --- | --- | --- |
| 121216 | [AUTH-102065-P01] Verify successful login with valid registered email and correct password | P |
| 121217 | [AUTH-102065-P02] Verify validation error when email field is left empty | P |
| 121218 | [AUTH-102065-P03] Verify validation error when password field is left empty | P |
| 121219 | [AUTH-102065-P04] Verify validation errors when both email and password fields are empty | P |
| 121220 | [AUTH-102065-P05] Verify validation error for incorrectly formatted email | P |
| 121221 | [AUTH-102065-P06] Verify error message for unregistered email | P |
| 121222 | [AUTH-102065-P07] Verify error message and field reset for incorrect password | P |
| 121223 | [AUTH-102065-P08] Verify password field is masked by default | P |
| 121224 | [AUTH-102065-P09] Verify 'Show' toggle reveals the entered password | P |
| 121225 | [AUTH-102065-P10] Verify 'Hide' toggle re-masks the password | P |
| 121226 | [AUTH-102065-P11] Verify 'Login' button remains disabled when required fields are empty | P |
| 121227 | [AUTH-102065-P12] Verify 'Login' button becomes active once valid inputs are entered | P |
| 121228 | [AUTH-102065-P13] Verify navigation to the Forgot Password flow | P |
| 121229 | [AUTH-102065-P14] Verify leading/trailing spaces in the email field are handled correctly | P |
| 121230 | [AUTH-102065-P15] Verify email field accepts case-insensitive match for login | P |
| 121231 | [AUTH-102065-N01] Verify system handles malicious input (SQL/script injection) in the email field | N |
| 121232 | [AUTH-102065-N02] Verify session persists after successful login on page refresh | N |
| 121233 | [AUTH-102065-A01] Verify all UI elements are displayed correctly on the login page | A |

P14, P15, N01, N02, and A01 have no matching scenario in the description. Sitting in suite 121215 does not make them covered ACs (§6.4).

#### 6.2.3 Still required after this read

| Gap | Why it still matters |
| --- | --- |
| Which field is “the AC”? | H1 as written looks at an AC field. On this story that field is empty and the description is not. Splitting that text into AC ids is deterministic (numbering or a fixture list). It is not an LLM parse (`docs/orchestration-and-cost.md` §4.1). |
| Stable `ac_id`s and `mapped_ac_ids` | H4 has nothing explicit to count. A topical resemblance is not a link. |
| Coverage type on each test | H5 and H6. P / N / A is not that enum. N02 is a session refresh; A01 is a UI checklist. |
| A bug work item | This story’s bug count is zero. The FIX-BUGGY persona still needs its own bug. |
| The other four fixture rows | §9. One login story does not stand in for thin AC, no tests, happy-path-only, and an open Sev1. |
| A sanitized fixture file in the repo | The live read is the evidence. Do not commit identity payloads. A PAT still belongs only in `.env`. |

### 6.3 Adapter contracts (intent)

Adapters hide source shape. The evaluation layer must not speak ADO field names (`System.Title`, etc.).

Minimum records the dummy TMS + ADO adapters must be able to return (see also `fixtures/SCHEMA.md` when frozen):

- **StoryRecord** — id, title, type, state, description, area, iteration, raw AC text, discrete AC list
- **AcceptanceCriterion** — ac_id, text, testable flag, ambiguity flags
- **TestCase** — id, title, type (happy / negative / edge / security / adhoc), mapped_ac_ids[], last_result, last_result_at, linked bug ids. The report prints `happy` as Positive, `negative` as Negative, and `adhoc` as Adhoc. `edge` and `security` stay on the record and in the appendix. They do not fill the three coverage-depth lines.
- **CoverageSummary** — per scenario: mapped test ids, depth, gap, and row status (Adequate / Partial / None). Counts of those three statuses. Computed by the scorer from `mapped_ac_ids` and `type`, not by the LLM, and not stored as a coverage percentage.
- **BugRecord** — id, title, severity, priority (`P1`–`P4` when known), status, age, found-in env, linked story id, linked TC id, assigned_to, application, created. The last three may be empty. Empty prints blank. The scorer does not copy severity into priority.
- **HealthReport** — story header, story health from §7.1, AC coverage table, bug table, narrative, recommended actions, appendix of raw IDs

**TBD-DATA-2** (Thabitha): freeze `fixtures/SCHEMA.md` and `docs/contracts.md` on **one** field-naming convention (`ac_id` vs `acId`, `mapped_ac` vs `covers`). Schema is law.

### 6.4 Traceability rule (phase 1 law)

A test covers an AC only if the link was set explicitly.

- Source of truth: `mapped_ac` / `mapped_ac_ids` / linked TC IDs written by a human or fixture author.
- Never persist LLM-guessed or embedding/semantic matches as coverage.
- A “this looks related” suggestion may be shown to a human. It must not populate the data used to score.
- No explicit link means the AC is uncovered. A false “covered” is worse than a false “uncovered.”

**TBD-DATA-3** (Thabitha, after Vignesh review 28 Sep 2026): update the Google contract doc with the agreed mapping rule and point this pack at the repo copy.

---

## 7. Health scorecard v0

QA owns “what healthy means.” Devs own “how we compute it from adapter fields.”  
If a metric cannot be computed from dummy fields, it does not ship in phase 1.

Seed (DoD sheet). Keep / park / drop is **not** re-frozen here — QA’s SharePoint draft is the working rewrite.

| ID | Signal | What good looks like | Source field (dummy) | Gate or report? | Weight | Seed keep? |
| --- | --- | --- | --- | --- | --- | --- |
| H1 | AC present | AC field non-empty and split into discrete criteria | `story.acceptance_criteria[]` | Report + soft warn | High | Keep |
| H2 | AC testability | Each AC is Given-When-Then or otherwise pass/fail | `ac.testable` + `ac.text` | Report | High | Keep |
| H3 | AC ambiguity | No vague words only (“should work”, “fast”, “as expected”) without a measure | `ac.flags[]` | Report | Med | Keep |
| H4 | AC ↔ test mapping | Every AC has ≥1 explicitly linked test | `test.mapped_ac_ids[]` | Report | High | Keep |
| H5 | Required tests exist | Happy path + at least one negative per critical AC | `coverage.by_type` | Report | High | Keep |
| H6 | Coverage breadth | Happy / negative / edge / (optional) security represented | `coverage.by_type` | Report | Med | Keep |
| H7 | Execution freshness | Mapped tests have a result newer than N days | `test.last_result_at` | Report | Low | Park |
| H8 | Open bugs linked | Count + severity + age of bugs related to the story | `bugs[]` | Report | High | Keep |
| H9 | Blocker bugs | No open P1 / Sev1 against the story | `bugs[].severity`, `status` | Report (optional gate later) | High | Keep |
| H10 | Orphan evidence | Tests or bugs that claim the story but do not map to an AC | `tests[]`, `bugs[]` | Report | Med | Park |
| H11 | Story health | Critical / High / Medium / Low, or No open bugs, from the highest open bug (§7.1). Not model mood, and not a coverage percentage | derived | Report header | High | Keep |
| H12 | Recommended actions | 3–7 concrete next steps with owner role (QA / Dev / PO) | derived | Report footer | High | Keep |

Worked examples already in `Story guard - Metrics Report.xlsx` (not yet aligned to the fixture-matrix names):

| Story ID | Title | Traceability snapshot | Open bugs of note |
| --- | --- | --- | --- |
| STORY-101 | Reset password via email | 4 ACs; AC-4 has 0 TCs; two ACs positive-only | Open P1 Critical found in UAT (old password still works) |
| STORY-102 | Bulk CSV upload for contacts | 5 ACs; 3 with no TC; one linked TC failing | Two open P2 High |
| STORY-103 | Apply discount code at checkout | 4 ACs, each linked to 1 TC, marked Adequate | One closed P3 |

`Story_Guard_Report_2_Banking.pdf` is the QA sample for how a finished report looks. It is a four-story portfolio (Digital Banking App, 30 Sep 2026). Phase 1 does not generate that portfolio. It takes the single-story parts and leaves the rest.

Taken into the one-story PDF:

- The health words and the rule key: Critical = open P1 (At Risk), High = open P2 (At Risk), Medium = open P3 (Healthy), Low = open P4 (Healthy).
- Open-bug counts by P1–P4, and escaped defects (found in Production or UAT), for this story.
- The acceptance-criteria table: AC id, coverage depth, coverage gap, and the Adequate / partial / no-coverage key.
- The bug table columns: Bug ID, Title, State, Story ID, TC ID, Priority, Severity, Assigned To, Found in Env, Application, Created. Closed bugs stay on the table. Open bugs sort first by priority.

Left for later, with the portfolio:

- The six KPI tiles, the portfolio summary, and the four-story overview.
- The two charts (open bugs by priority, test-case coverage % by story).
- Average coverage %, and any coverage percentage. The sample’s 43–88% figures have no formula in this pack. Phase 1 prints counts.
- An AI judgement of coverage depth. The sample’s caption says the depth was generated by AI analysis. Phase 1 fills the same columns from `mapped_ac_ids` and test `type`. The phrase “partially covered” is that AI judgement. The scorer does not emit it.

### 7.1 Story health — sprint stand-in, taken from the banking PDF

Draft A is the rule the sample uses, with one case the sample never shows. Drafts B and C stay unpublished. **Do not implement a fifth rule in code.** The sprint text is `docs/rag-stand-in.md`.

| Draft | Rule of thumb | Source |
| --- | --- | --- |
| A | Highest **open** bug sets the story health, regardless of coverage. P1 Critical, P2 High, P3 Medium, P4 Low. | `Story_Guard_Report_2_Banking.pdf` |
| B | Coverage % + open / critical / major bug counts → Healthy vs Unhealthy | Architecture review fixtures |
| C | Published Green / Amber / Red from H1–H10 (seed H11) | DoD scorecard |

Phase 1 uses draft A, split from coverage the way the sample splits them. Coverage does not change the health word. QA’s earlier comment preferred that split. The sample has no story with zero open bugs. 121213 is that story, so the stand-in adds one label: **No open bugs**. It is not Critical, High, Medium, Low, Healthy, or Red.

An open bug has a status other than Resolved, Closed, Rejected, or Unable to Reproduce. In Progress is open. Escaped means `found_in` contains Production or UAT. QA is not escaped. Priority is the `P1`–`P4` token on the bug. Severity does not fill a missing priority.

**TBD-HEALTH-1** (Vignesh, freeze owner): accept this stand-in or replace it. The sprint builds the stand-in. Replacing it reopens the report header and the 121213 expected counts.

**TBD-HEALTH-2** (Vignesh + Rithika): finish keep / park / drop on H1–H12 against the SharePoint draft and copy the winner into the DoD sheet.

---

## 8. Generation gates

Gates protect the generator. The report carries the bad news.

Hard gate → no PDF, clear error.  
Soft gate → still generate; header and actions show the gap.

### 8.1 Seed gates (DoD sheet)

| ID | Gate | Fail behaviour | Severity | Phase 1? |
| --- | --- | --- | --- | --- |
| G1 | Story ID resolves in dummy project or fixture index | Do not generate; return a clear error | Hard | Yes |
| G2 | Story type is User Story (or an allowed-types list) | Do not generate | Hard | Yes |
| G3 | Adapter payload matches the contract | Do not generate; log schema errors | Hard | Yes |
| G4 | AC missing entirely | Still generate. The coverage section shows the empty AC field and an action “write AC”. Story health stays the bug rule. | Soft | Yes — **disputed** |
| G5 | No test pack found for story id | Generate with empty coverage + actions; do not invent tests | Soft | Yes — **disputed** |

QA comments on the seed:

- G4: “We won’t be having this use case mostly.”
- G5: prefer a one-liner “no test pack for this Story ID” instead of a hollow coverage section.

### 8.2 Hard-stop scenario list (QA)

Treat as the expanded G1–G3 family. All of these fail closed (no PDF) unless marked soft.

| Scenario | Reason | Severity |
| --- | --- | --- |
| Story ID not provided / blank | Nothing to generate against | Hard |
| Story ID malformed | Cannot attempt a lookup | Hard |
| Story ID belongs to a different org/project than configured | Would silently pull the wrong story | Hard |
| ADO org/project unreachable | No data source | Hard |
| Authentication failed | Cannot prove the request is authorized | Hard |
| Permission denied (403) | Reading it would be a security violation | Hard |
| Story ID does not exist (404) | Nothing to report on | Hard |
| Work item exists but is not a User Story | Wrong data shape | Hard |
| Story is deleted | Nothing to generate against | Hard |
| AC field throws a read/parse error | Read failure, not a data gap | Hard |
| Story title is null | Cannot build the report header | Hard |
| Process template has no AC field | Structural schema mismatch | Hard |
| Test Plans / dummy pack unreachable | Generate and say tests are missing | **Soft** |
| Report PDF template missing or corrupted | Nothing to render into | Hard |
| Generation exceeds a hard timeout | Do not hang forever. Dev model call: **60 s** of generation after the weights are loaded, or **8,192** tokens, whichever first (`docs/orchestration-and-cost.md` §4.1). Target for that call is ≤ 4,096 tokens. | Hard |
| Narrative JSON fails its schema | Retry the one narrative call once, then no PDF | Hard |

**TBD-GATES-1** (Rithika, Vignesh reviews): lock G4 and G5. Write `docs/gates.md` as the build-week checklist.

---

## 9. Fixtures (product spec for later evals)

Five stories are enough. Each row becomes a JSON file and later an eval case.  
Coverage percentages live in the fixture; the engine copies them. The model does not invent them.

### 9.1 Planned matrix (DoD sheet)

| Fixture id | Persona / title | AC quality | Tests / coverage | Bugs | Story health | Expected headline |
| --- | --- | --- | --- | --- | --- | --- |
| FIX-HEALTHY | Checkout — apply discount code | 4 discrete GWT criteria | 8 tests: happy, negative, edge; all mapped; recent pass | 0 open | No open bugs | Ready to ship from a QA lens |
| FIX-THIN-AC | Profile — upload avatar | One sentence: “User can upload a photo” | 2 vague tests, mapping unclear | 0 open | No open bugs | AC too thin to test — rewrite before adding cases |
| FIX-NO-TESTS | Search — filter by date range | Solid AC (3 GWT) | 0 tests | 0 open | No open bugs | AC exist but nothing tests them |
| FIX-WEAK-COV | Login — password reset | Good AC including lockout + expiry | Happy path only; no negative / security | 1 low bug, old | Low (Healthy) | Coverage is a happy-path tunnel |
| FIX-BUGGY | Payments — save card | Decent AC | Tests exist but 2 failing / stale | 1 P1 open + 2 P2 | Critical (At Risk) | Do not call this done — open P1 and failing tests |

Story health in this table is the §7.1 stand-in. A thin AC or a missing test pack shows up in the coverage table and in the headline. It does not paint the story Critical. These four fixtures are not in the sprint. 121213 is the demo, and under the same rule its health is No open bugs.

File naming: `fixtures/FIX-HEALTHY.json` etc. Include a `story_id` that matches an ADO work item once the dummy project exists.

### 9.2 What actually exists today (do not treat as the matrix)

| Source | IDs | Notes |
| --- | --- | --- |
| Ecom MVP dummy sample | Story **121213** SNAP Login Screen; plan **121214** / static suite **121215** (18 cases, none linked, none run) | Read 29 Sep 2026. Scenarios are in the description; AC field empty; no bug. See §6.2. Not yet a FIX-* file. |
| Metrics workbook | STORY-101 / 102 / 103 | Traceability + bugs filled; overall metric formulas empty |
| Architecture review note | US-100 healthy reset-password; US-101 unhealthy update-profile | Thin contracts; not the H1–H12 scorecard |
| Fixture matrix sheet | FIX-* rows | Status still “Not Started” |

**TBD-FIX-1** (Rithika + Vignesh): pick **one** ID scheme and land five JSON files + README headlines in the repo. Stop maintaining three parallel examples.  
**TBD-FIX-2** (Valliammai + Rithika): the 121213 section order is frozen in §10. The portfolio outline and the five-persona mocks are still open. Those mocks are not the UX spec until that outline is frozen.

---

## 10. Report shape (target output)

Phase 1 output is one PDF for one story. QA reviews markdown first if the renderer is markdown → PDF.

Frozen section order for this sprint (from the scorecard + consumer walkthrough):
The 121213 demo freezes the six sections below. They are the single-story reading of `Story_Guard_Report_2_Banking.pdf`, plus the two phase-1 jobs that sample does not do: recommended actions (H12) and a raw-id appendix so QA can check Azure DevOps. There is no seventh section. Portfolio summary, the multi-story overview, and the charts are not headings in this template.

1. **Title block** — the document title is Story Health Report. Story id, title, project, generated-at, and source (`dummy fixture` or `ADO dummy project`). One line for the reader: user story health, test coverage, and defect status.
2. **Story health** — the §7.1 word and band, the rule key (Critical / High / Medium / Low, and the No open bugs line), open counts for P1–P4, and the escaped count. Coverage is not restated here as a second health color.
3. **Acceptance criteria vs test coverage** — one count line and one table. The count line is `N acceptance criteria | A adequately covered | G with gaps | U not covered`. On 121213 the rows are the eight description scenarios, and the line says the AC field is empty. Columns are AC ID, Coverage depth, and Coverage gap. The color key is three words the text extract must contain: Adequate, Partial, None. A green, amber, or red fill may sit behind those words. Depth uses the sample’s phrases for types that are present: “Positive scenarios are covered”, “Negative scenarios are covered”, “Adhoc scenarios are covered”. A missing type uses “No Positive scenarios Covered”, “No Negative scenarios Covered”, or “No Adhoc scenarios Covered”. None uses depth `None` and gap `No coverage`. The scorer does not write “partially covered”.
4. **Bug details** — the sample’s columns, for this story, including bugs that are not open. Sort by priority, P1 first. The section still renders when `bugs` is empty, and it says there are no bugs. Not-open rows are marked not open. Production and UAT are marked escaped.
5. **Recommended actions** — 3–7 items with an owner role (QA / Dev / PO). The narrative phrases them from the score. It does not invent a gap the score did not record.
6. **Appendix** — raw story, AC, test, and bug ids so QA can validate against the source.

Each numbered item is one PDF section. The possible RAG split remains within section 2; it does not create another section. The exact template headings are in `templates/health_report.md`.

Static mocks for FIX-HEALTHY and one unhealthy fixture are the UX spec for the build week. They are **not** agent-generated.

**TBD-REPORT-1** (Valliammai + Rithika): the eight-section order is frozen for this sprint in `templates/health_report.md`; UX critique remains open.
**TBD-REPORT-2** (Vignesh): QA critique of the mocks — 5 concrete template edits — after the PDFs exist.
Row status, computed with the mapping law in §6.4:

- **Adequate** — the scenario’s mapped tests include Positive, Negative, and Adhoc.
- **Partial** — at least one test is mapped, and at least one of those three types is missing.
- **None** — no test lists this `ac_id`.

`happy` counts as Positive. `edge` and `security` do not satisfy Positive, Negative, or Adhoc. The author prefix `P` / `N` / `A` on a 121213 title is still not `type` (§6.2.2). With `mapped_ac_ids` empty, every 121213 row is None. That is 8 acceptance criteria, 0 adequately covered, 0 with gaps, 8 not covered, story health No open bugs.

Static mocks for FIX-HEALTHY and one unhealthy fixture remain the later UX spec. They are not this sprint’s demo, and they are not agent-generated.

**TBD-REPORT-1** (Valliammai + Rithika): the six headings above are the 121213 freeze. A portfolio outline is still open.  
**TBD-REPORT-2** (Vignesh): QA critique of the mocks — 5 concrete template edits — after a PDF exists. The critique can accept or reject the stand-in in §7.1.

---

## 11. System intent (phase 1, not a platform)

Proposed lock, 29 Sep 2026: **D6 LangGraph** as control flow, **D10 one pipeline**. Full argument, reversal test, and cost rules: `docs/orchestration-and-cost.md`. This section is the requirements view of that lock.

```
generate --story-id
        │
        ▼
 [LangGraph — Python nodes, one LLM node]
        │
        ├─ gate_input          hard stops, no model
        ├─ fetch_story         ADO adapter
        ├─ fetch_tests         dummy TMS adapter
        ├─ fetch_bugs          ADO relations, or the dummy bug record
        ├─ validate_contract   schema check, no model
        ├─ score_health        H1–H11 in code, no model
        ├─ write_narrative     one structured LLM call over the score object
        └─ render_pdf          markdown template → PDF
        │
        ▼
 QA reviews the PDF, then shares
```

Rules the architecture must obey:

- Adapters first. The scorer and the narrative node do not speak raw ADO JSON. The narrative node receives the score object.
- Coverage rows, story health, and `mapped_ac` come from code and explicit links. The model cites them. It does not change them, and it has no tools on this call.
- One orchestrator. A specialist crew (parser, AC auditor, coverage analyst, bug correlator, writer) is out, including the same shape drawn as a LangGraph supervisor.
- One LLM call per successful generate, against the local model in `docs/orchestration-and-cost.md` §4.5. The runner’s JSON mode constrains it. A schema failure retries that call once, then fails closed. A second call for a QA rewrite is later-phase HITL.
- AC splitting is deterministic. Markdown-first so QA can diff; PDF is a render step.
- Dev caps bind the build week: context loaded at 8,192, narrative target ≤ 4,096 tokens, hard stop at 8,192 tokens or 60 s of generation. Do not raise the context to fit a raw work-item blob.

The Thursday architecture review draft that introduces a Web UI, API gateway, and application database is a **later** shape. It is not phase 1.

**TBD-ARCH-1** (Gugan): D6 and D10 are proposed-locked in `docs/orchestration-and-cost.md`. Remaining action is to paste those decision-log rows into the workbook. Re-open only if §6 of that doc is met.  
**TBD-ARCH-2** (Valliammai): D7 development runtime is locked in `docs/orchestration-and-cost.md` §4.5. D8 PDF library is locked as ReportLab in `docs/pdf-library.md`.
**TBD-ARCH-3** (Gugan): rubric-cache, tool-schema pruning, and context-isolation constraints are in `docs/architecture.md`. Not implemented this week. A breach is a defect.

---

## 12. Working agreements

- Dummy data only. Fixtures and a clearly named dummy project. No live delivery board.
- 1–2 hours per person per day. Unfinished work becomes an open question with an owner — it is not silently dropped.
- Decisions are written the same day (this pack + the decision log).
- QA owns “what healthy means.” Devs own “how we will build it.”
- Status on the week-2 workbook feeds the individual tracker. Blocked if any day is Blocked; Completed only if all four planning days are Completed.
- Secrets (ADO PAT) live in `.env`. Never committed. README warns dummy-data-only.
- Scope editor: Gugan. Anything that sounds like a product feature after phase 1 goes on the Later list in §3.2.

---

## 13. Open questions (explicit TBD)

| ID | Question | Owner | Blocks |
| --- | --- | --- | --- |
| TBD-DATA-1 | 121213 is read: AC field empty, scenarios in `System.Description`, no bug, 18 unlinked tests in static suite 121215. Still decide which field H1 reads, and write `mapped_ac_ids` before any coverage score. | Gugan, Thabitha | H1 source field, H4 scoring, fixture `story_id` alignment |
| TBD-DATA-2 | Freeze SCHEMA.md / contracts.md field names | Thabitha | Dummy TMS adapter, scoring engine |
| TBD-DATA-3 | Traceability contract doc updated after 28 Sep review | Thabitha (Vignesh reviewed) | H4 scoring |
| TBD-HEALTH-1 | Vignesh accepts or replaces the banking-PDF stand-in in §7.1 and `docs/rag-stand-in.md` | Vignesh | Report header, eval headlines |
| TBD-HEALTH-2 | Final keep / park / drop on H1–H12 | Vignesh, Rithika | Scoring engine |
| TBD-GATES-1 | Lock G4 / G5; write `docs/gates.md` | Rithika | Generator fail-closed behaviour |
| TBD-FIX-1 | One fixture ID scheme + 5 JSON files | Rithika, Vignesh | Evals, mock PDFs |
| TBD-FIX-2 | Portfolio and five-persona mock outline. The 121213 section order is frozen in §10. | Valliammai, Rithika | Later mock PDFs |
| TBD-REPORT-1 / 2 | 121213 outline is frozen (§10). QA critique of the rendered PDF is still open. | Valliammai, Rithika, Vignesh | PDF template |
| TBD-ARCH-1 | D6/D10 proposed lock is written. Paste the workbook rows. Do not re-open without the reversal test in `docs/orchestration-and-cost.md` §6. | Gugan | Workbook decision log |
| TBD-ARCH-2 | D7 dev runtime is locked (local, 8 GB Mac). D8 PDF library is locked as ReportLab in `docs/pdf-library.md`. | Valliammai | B6 |
| TBD-ARCH-3 | Constraints are in `docs/architecture.md`. Implementation of cache, tool pruning, and isolation waits. | Gugan | None this week |
| TBD-PLAN-1 | Next-week backlog resized to 1–2 hrs/day | Gugan + all | Monday start |
| TBD-PLAN-2 | Decision log D5–D10 dated and closed. D6 and D10 are proposed-locked (29 Sep 2026) in `docs/orchestration-and-cost.md`; the workbook copy is still outstanding. | Gugan | Stop relitigating Tuesday |
| TBD-PLAN-3 | Risk register rows owned and mitigated | All; Gugan on R4, R6, R7 | Build week |

---

## 14. Definition of done for this pack

This requirements pack is frozen when:

- [x] Problem, users, phase-1 I/O, non-goals, and later-list are written here (this document).
- [ ] Scorecard v0 keep/park/drop copied from QA’s draft (TBD-HEALTH-2).
- [ ] Story-health stand-in accepted by Vignesh (TBD-HEALTH-1). The sprint text is already in `docs/rag-stand-in.md`.
- [ ] Gates G4/G5 locked (TBD-GATES-1).
- [ ] Fixture scheme chosen (TBD-FIX-1).
- [ ] Pointers to `docs/architecture.md`, `docs/contracts.md`, `docs/gates.md`, `fixtures/SCHEMA.md` resolve in the repo.
- [ ] Every TBD row has an owner (yes) and a next action dated in the decision log.

Build-week code must not start on a TBD as if it were closed.

---

## 15. Pointers

| Artifact | Where it lives now | Where it should live |
| --- | --- | --- |
| This pack | `docs/requirements.md` | repo `/docs/requirements.md` |
| Week plan / DoD / decision log / risks | Week-2 workbook | keep workbook; copy locked rows into `/docs/decisions.md` |
| Scorecard rewrite | Rithika SharePoint xlsx | `/docs/scorecard.md` after TBD-HEALTH-2 |
| Metrics worked examples | `Story guard - Metrics Report.xlsx` | feed fixtures, do not remain the contract |
| Dataset spec | Google Doc | `/fixtures/SCHEMA.md` |
| Architecture + ADO spike notes | Google Doc + architecture review write-up | `/docs/architecture.md`, `/docs/ado-adapter.md` |
| D6 / D10 and cost caps | `docs/orchestration-and-cost.md` | same file; paste the decision-log rows into the workbook |
| Rubric cache, tool schemas, context isolation | `docs/architecture.md` | same file; constraints only this week |
| Gates | This pack §8 + workbook seed | `/docs/gates.md` |
| Repo skeleton | https://github.com/Gugan-Ananth-A/story-guard-mvp | `/docs`, `/fixtures`, `/artifacts`, `.env.example` |

---