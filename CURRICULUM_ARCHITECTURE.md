# Curriculum architecture

Date: 4 August 2026

## Boundary

Sumkora now treats curriculum support as a registry outside the core document
engine. The registry lives in `curricula.py` and declares each entry as either
`verified` or `planned`.

The core engine remains responsible for:

- original-document ingestion and normalization;
- direct vision/reasoning assessment;
- evidence and consistency validation;
- mistake diagnosis and student modelling;
- reports, history, and activity tracking.

A curriculum module is responsible for:

- syllabus identity and terminology;
- topic and skill taxonomy;
- curriculum-specific marking constraints;
- verified question-bank sources and practice selection;
- benchmark papers, expected scores, and release evidence.

## Current support

`Cambridge IGCSE Additional Mathematics 0606` is the only verified module. It
is the only option accepted by the paper-upload route.

The interface lists 0580, AP Calculus AB/BC, IB Mathematics, A-Level
Mathematics, and General Mathematics as disabled planned entries. This is a
roadmap signal, not a support claim.

## Adding a curriculum safely

1. Create its taxonomy, terminology, marking rules, and practice adapter.
2. Add representative answer-only and detailed-marking benchmarks.
3. Define score, coverage, latency, and report acceptance thresholds.
4. Run regression tests proving existing 0606 behavior is unchanged.
5. Change the registry entry to `verified` only after the evidence is recorded.

The previously reverted general-mathematics implementation is not restored by
this architecture.

