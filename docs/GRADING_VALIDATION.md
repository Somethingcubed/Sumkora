# Grading validation

Updated: 25 July 2026

## Scope

The checked set is a manually specified synthetic regression set, not a set of
real Cambridge scripts marked by an examiner. It is useful for preventing
known over-credit and state-management failures, but it cannot establish
examiner-level reliability.

Four deterministic grading cases were checked with external AI disabled:

| Case | Expected | Actual | Safety expectation |
|---|---:|---:|---|
| Multi-mark item with unsafe final-answer match | 0 | 0 | Flag for review |
| Clear wrong one-mark answer | 0 | 0 | Finalize without false uncertainty |
| Persisted unsafe multi-mark grading job | 0 | 0 | Finalize conservatively and retain risk flag |
| Reused high-confidence one-mark suggestion | 1 | 1 | Preserve provenance and finalize |

## Metrics

- Questions: 4
- Exact question-total agreement: 4/4 (100%)
- Mean absolute mark difference: 0.0
- Within one mark: 4/4 (100%)
- Over-marking count: 0
- Under-marking count: 0
- Omitted-response count: 0 in this narrow fixture set

These metrics describe only the four synthetic cases above.

## Additional deterministic checks

- uncertain evidence produces confirmed/provisional/possible score ranges;
- multiple longitudinal observations move from early signal to recurring
  concern to improving;
- untested skills remain untested rather than weak;
- reruns preserve the previous version and its question results;
- human corrections are appended separately and do not overwrite AI marks;
- exact-match logic does not award all method marks from a final-answer token;
- archived teacher override routes cannot mutate active grading results.

## Error-source coverage

| Source | Current coverage |
|---|---|
| OCR-caused grading error | Stored and distinguishable, but no real-script gold-set metric yet |
| Question mapping | Deterministic parser tests for Cambridge page numbers and marking principles |
| Mark-scheme parsing | 77 parsed question/subpart rows and 260 criteria remain review-required |
| Deterministic checking | Regression-covered |
| Model grading | Live smoke-tested previously; not calibrated against a representative human set |
| Diagnosis | Range/category persistence tested; explanation quality not statistically validated |

## Limitations and next validation

A representative owner-reviewed 0606 gold set is still required. It should
include criterion-level M/A/B marks, dependencies, follow-through,
alternative methods, misreads, omitted work and source-page references.
Report sample size, exact agreement, mean absolute error, within-one-mark,
over/under-marking and error cause. Sumkora must not be described as an
official examiner.
