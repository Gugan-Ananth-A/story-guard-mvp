# D8 — PDF library decision

**Status:** Locked for this sprint

**Selected:** ReportLab.

ReportLab is a pure-Python PDF library that writes the static fixture report in-process. It fits the project's Python stack and works without launching a browser, keeping rendering practical on an 8 GB Mac.

**Rejected alternative:** Playwright. PDF generation through Playwright launches a browser, which violates the no-browser requirement and adds unnecessary memory overhead on the 8 GB Mac.
