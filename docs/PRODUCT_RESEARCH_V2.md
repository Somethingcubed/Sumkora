# Product research v2

Research date: 25 July 2026

## Cambridge 0606

The implementation targets the official 2025–2027 Cambridge IGCSE Additional
Mathematics 0606 syllabus. Official specimen material confirms method,
accuracy and independent marks (`M`, `A`, `B`) plus dependent and
follow-through conventions. A grade threshold is a session/component
interpretation aid, not a question-level grading rule and not a supported
personal grade prediction.

Sources:

- [Official 2025–2027 syllabus](https://www.cambridgeinternational.org/Images/662470-2025-2027-syllabus.pdf)
- [Official 2025 specimen Paper 1](https://www.cambridgeinternational.org/Images/664576-2025-specimen-paper-1.pdf)
- [Official 2025 specimen Paper 2 mark scheme](https://www.cambridgeinternational.org/Images/664581-2025-specimen-paper-2-mark-scheme.pdf)
- [Official June 2025 grade thresholds](https://www.cambridgeinternational.org/Images/741349-additional-mathematics-0606-june-2025-grade-threshold-table.pdf)

Product consequence: marking must retain criterion dependencies,
follow-through, alternative valid methods, exact-form requirements and
uncertainty. The current adapter does not yet implement all of those rules.

## CXSee

CXSee exposes an OpenAI-compatible `/v1/chat/completions` flow with Bearer
authentication and multimodal message content. The owner-supplied endpoint and
credential authenticated successfully. The provider's live model inventory
did not include `qwen-vl-ocr-latest`; requests to it and `qwen-vl-ocr`
returned 503 during this audit. `qwen3-vl-plus` successfully handled both the
synthetic image and an authorized private scan page.

Sources:

- [Owner-supplied CXSee documentation](https://docs.cxsee.com/doc/view_105.html)
- [CXSee Qwen model page](https://docs.cxsee.com/doc/view_107.html)
- [CXSee OCR guidance](https://docs.cxsee.com/doc/view_87.html)
- [CXSee authentication/base URL](https://docs.cxsee.com/doc/view_77.html)

Product consequence: keep the requested latest model as primary, but record
fallbacks and surface availability instead of silently switching models.

## Historical prototype

The previous public prototype is reachable and presents a separate Next.js,
0580-era student tracker with login, dashboard analytics, recommendations and
assignments. No local configuration establishes a build or data connection
between it and this repository.

Coze describes full-stack hosting, deployment, domains, AI services, database
and object storage. Its CLI documentation includes deployments, environment
variables, custom domains and Supabase-backed database workflows. Platform
terms also make independent backup and retention planning important.

Sources:

- Previous prototype retained as historical product evidence
- [Coze Space](https://www.coze.com/space)
- [Coze CLI package documentation](https://www.npmjs.com/package/@coze/cli)
- [Coze privacy policy](https://www.coze.com/legal/privacy)

Recommendation: preserve the public prototype, but do not place private
student scripts there until authentication, storage privacy, export/deletion,
backup, worker behavior and repository deployment linkage have been verified.

## Learner modelling

This iteration uses transparent, rebuildable evidence aggregation rather than
student-specific model fine-tuning. Each observation retains paper, question,
criterion, marks, confidence and time. Recency weighting changes the current
estimate without deleting the all-time view. Status transitions require
repeated papers, and missing evidence remains untested.

This is deliberately a product heuristic, not a validated psychometric score.
Future work should calibrate it against human-marked longitudinal data.
