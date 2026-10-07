# 07 — Freeze the eight section headings

**Owner:** Valliammai (S6)
**Depends on:** nothing. Slice 14 needs this file.
**Size:** S
**Status:** Complete

## Outcome

`templates/health_report.md` has the eight section headings from `docs/requirements.md` §10, in that order, including the appendix of raw IDs. The sprint template has those eight sections and no ninth.

The section order is frozen for this sprint. It does not publish the five-persona UX spec.

## Done when

The template headings, in this order, with these jobs:

1. **Title block** — story id, title, generated-at, source (`dummy fixture` or `ADO dummy project`)
2. **Overall RAG** — one RAG and a one-line headline. This sprint prints the single RAG from SR-2. A split of coverage health and bug health stays with TBD-HEALTH-1 and is not a ninth section or a second heading.
3. **AC review** — the AC field, and the discrete description scenarios
4. **AC ↔ test mapping** — each scenario, the linked test ids, and the gaps
5. **Coverage by type** — happy / negative / edge / security counts taken from the score object
6. **Bugs** — open bugs by severity, age, linked test, and found-in environment
7. **Recommended actions** — 3–7 items with an owner role (QA / Dev / PO)
8. **Appendix** — raw story, AC, test, and bug IDs

- The file is `templates/health_report.md`.
- A heading count of the template is 8.
- Body text under the headings may be placeholders (`{{ }}` or equivalent). The placeholders are filled in slice 14. This slice locks the headings and the order.

## Check

```bash
rg -n "^#+ " templates/health_report.md
```

The eight lines appear in the order above. There is no ninth heading.

## Out of this slice

A rendered PDF, a real score, and narrative prose. Slice 14 fills the placeholders from a hand-built score. Slice 21 fills them from `score_health`.
