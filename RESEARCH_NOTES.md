# Research notes

Updated: 25 July 2026

## Cambridge

- [0606 syllabus 2025–2027](https://www.cambridgeinternational.org/Images/662470-2025-2027-syllabus.pdf)
- [2025 specimen Paper 1](https://www.cambridgeinternational.org/Images/664576-2025-specimen-paper-1.pdf)
- [2025 specimen Paper 2 mark scheme](https://www.cambridgeinternational.org/Images/664581-2025-specimen-paper-2-mark-scheme.pdf)
- [June 2025 grade thresholds](https://www.cambridgeinternational.org/Images/741349-additional-mathematics-0606-june-2025-grade-threshold-table.pdf)

Open question: obtain owner-reviewed, licensed interpretation tests for
dependent marks, follow-through, misreads, recovery and alternative methods
across multiple live 0606 sessions.

## CXSee

- [Owner-supplied API documentation](https://docs.cxsee.com/doc/view_105.html)
- [OCR guidance](https://docs.cxsee.com/doc/view_87.html)
- [Authentication/base URL](https://docs.cxsee.com/doc/view_77.html)
- [Model listing documentation](https://docs.cxsee.com/doc/view_58.html)

Live result: authentication/model listing worked; requested
`qwen-vl-ocr-latest` was not listed and returned 503. `qwen3-vl-plus`
succeeded as an auditable fallback. Unanswered: contractual retention, data
residency, student-data terms, published rate limits and latest-model rollout.

## Coze and comparable product evidence

- [Current Numera Coze prototype](https://numera.coze.site)
- [Coze Space](https://www.coze.com/space)
- [`@coze/cli`](https://www.npmjs.com/package/@coze/cli)
- [Coze privacy policy](https://www.coze.com/legal/privacy)

The public site is useful product/UI evidence, not a verified deployment of
this repository. No competitor source code or proprietary content was copied.
A broader competitor benchmark was intentionally deferred in favor of
implementation and security testing.

## Learner-model literature

The transparent evidence-state approach is inspired by Bayesian knowledge
tracing but is not a BKT implementation or validated mastery score:

- Corbett & Anderson, *Knowledge Tracing: Modeling the Acquisition of
  Procedural Knowledge*, User Modeling and User-Adapted Interaction 4 (1994),
  [DOI 10.1007/BF01099821](https://doi.org/10.1007/BF01099821).

Future study should compare simple aggregates, the current recency-Beta
heuristic and calibrated knowledge-tracing models against held-out human marks.

## Libraries and licensing

FastAPI, Starlette, Jinja, Tailwind, SymPy and SQLite have permissive/public
licenses suitable for review. PyMuPDF is dual AGPL/commercial and must be
resolved before a closed-source commercial deployment. Cambridge papers and
mark schemes remain copyrighted owner-supplied inputs and are not committed or
redistributed. No external GitHub implementation was vendored.
