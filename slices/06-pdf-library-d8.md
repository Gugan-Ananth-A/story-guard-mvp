# 06 — Pick the PDF library (D8)

**Owner:** Valliammai (S6)
**Depends on:** nothing
**Size:** S
**Status:** Not started

## Outcome

`docs/pdf-library.md` names one PDF library, why it was picked, and the rejected option. That note is the D8 lock for this sprint. Slice 14 renders with that library and no other.

TBD-ARCH-2 in `docs/requirements.md` stays the tracker row. After this slice, that row points at `docs/pdf-library.md` so the pack and the note agree.

## Done when

- `docs/pdf-library.md` is shorter than a page.
- It names one library.
- It says why, in terms of this machine: the library renders a PDF on the 8 GB Mac, and the render does not launch a browser.
- It names the rejected option and the reason.
- A one-line pointer from TBD-ARCH-2 in `docs/requirements.md` links to the note.
- The dependency is added to `pyproject.toml` only when slice 01 has landed. If slice 01 is still open, the note names the package and slice 14 adds the dependency. One library either way.

## Decision the note records

Pick **ReportLab**. It is pure Python, it is already the markdown-or-template alternative on the stack shortlist, and it writes a PDF in-process.

Reject a headless browser (Playwright, Puppeteer, or Chromium via WeasyPrint’s browser-shaped cousins) because the render would launch a browser, which this sprint forbids.

If the note’s author tries WeasyPrint first and the native Cairo/Pango install is the reason it loses, the note says that and still locks ReportLab. The lock is one library, written down the same day. Slice 14 does not carry two backends.

## Check

```bash
test -f docs/pdf-library.md
rg -n "pdf-library.md" docs/requirements.md
```

The note names ReportLab (or the single library the author locked, if a same-day install check forced a different pure-Python choice). The note names one rejected option. The requirements pointer resolves. The note’s library does not require a running browser.

## Out of this slice

The eight headings, the template, and a rendered file. Those are slices 07 and 14. Pixel-perfect layout is out (`docs/requirements.md` §4).
