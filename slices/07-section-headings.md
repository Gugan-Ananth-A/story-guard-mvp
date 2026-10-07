# 07 — Freeze the six section headings

**Owner:** Valliammai (S6)
**Depends on:** nothing. Slice 14 needs this file.
**Size:** S
**Status:** Not started

## Outcome

`templates/health_report.md` has the six section headings from `docs/requirements.md` §10, in that order, including the appendix of raw ids. The sprint template has those six sections and no seventh.

§10 freezes this outline for the 121213 demo. It is the single-story reading of `Story_Guard_Report_2_Banking.pdf`. It does not publish the portfolio report or the five-persona UX spec.

## Done when

The template headings, in this order, with these jobs:

1. **Title block** — document title Story Health Report. Story id, title, project, generated-at, source (`dummy fixture` or `ADO dummy project`). One line: user story health, test coverage, and defect status.
2. **Story health** — the SR-2 word and band, the rule key, open counts for P1–P4, and the escaped count. This is not a Green / Amber / Red heading, and it is not a coverage percentage.
3. **Acceptance criteria vs test coverage** — the count line (`N acceptance criteria | A adequately covered | G with gaps | U not covered`), then a table with columns AC ID, Coverage depth, and Coverage gap. The color key words Adequate, Partial, and None appear in the section.
4. **Bug details** — columns Bug ID, Title, State, Story ID, TC ID, Priority, Severity, Assigned To, Found in Env, Application, Created. The heading and the column names render when the bug list is empty.
5. **Recommended actions** — 3–7 items with an owner role (QA / Dev / PO).
6. **Appendix** — raw story, AC, test, and bug ids.

- The file is `templates/health_report.md`.
- A heading count of the template is 6.
- Body text under the headings may be placeholders (`{{ }}` or equivalent). The placeholders are filled in slice 14. This slice locks the headings and the order.
- The template has no heading for a portfolio summary, a multi-story overview, a chart, or a coverage percentage.

## Check

```bash
rg -n "^#+ " templates/health_report.md
```

The six lines appear in the order above. There is no seventh heading.

## Out of this slice

A rendered PDF, a real score, and narrative prose. Slice 14 fills the placeholders from a hand-built score. Slice 21 fills them from `score_health`.
