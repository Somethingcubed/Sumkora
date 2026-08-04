# Real paper test report

Date: 4 August 2026

## Fixture

- File: `Paper.pdf`
- Source format: 15-page image-only CamScanner PDF, A4, 2.6 MB
- Paper detected visually: Cambridge IGCSE Additional Mathematics 0606/13,
  October/November 2025, non-calculator, 80 marks
- Supplied acceptance expectation: approximately 56/80
- Mode: completed work only, no mark scheme, expected maximum set to 80
- Model: GPT-5.5 through the configured CXSee Responses endpoint

## Result

- Point estimate: **55/80**
- Displayed calibrated range: **49-61/80**
- Difference from acceptance expectation: **-1 mark**
- Coverage: **20 question parts**, Q1(a) through Q12(b)
- Maximum-mark reconciliation: **80/80**
- End-to-end assessment time: **258.1 seconds**
- Provider attempts: **1**
- Transport recovery/fallback: **none**

The result meets the approximate-score expectation and the under-ten-minute
target. The page-to-question evidence was coherent across all 15 uploaded
pages.

## Pipeline observations

- Upload normalization accepts this original image-only PDF without changing
  page order or orientation.
- The active pipeline intentionally does not run the legacy OCR/question-page
  mapper. GPT-5.5 reads the complete PDF directly; this avoids the earlier
  empty-image and wrong-question mapping failures.
- Structured response validation confirmed all evidence pages were in range,
  all maximums summed to the supplied 80, and all 20 labels were usable.
- The optional context pass expanded six lost-mark questions, then the
  bilingual feedback pass completed. Neither changed the marks.
- Automated integration tests separately cover draft creation, upload
  normalization, result persistence, failure cleanup, progress heartbeats,
  and student PDF report generation.

## Main lost-mark findings

The model identified full or near-full credit on inequalities,
differentiation, small changes, kinematics, vectors, integration, logarithms,
geometric progressions, and circle setup. The largest losses came from an
incomplete coordinate-geometry/calculus question, blank or incomplete
trigonometry/exponential/progression/circle parts, and an incomplete binomial
part.

## Errors and causes

- Numerical error against the requested approximate score: one mark. With no
  official mark scheme, the result is an estimate rather than examiner-exact
  marking; the displayed range correctly communicates that uncertainty.
- The exact mark allocation for method steps cannot be independently verified
  in completed-work-only mode.
- This test verifies direct vision, not the old OCR subsystem. That is by
  design: new student analyses no longer depend on OCR mapping.

## Fixes confirmed in this session

- No marking-logic change was needed. The restored whole-document pipeline
  already met score, coverage, and latency acceptance criteria.
- The upload screen now makes the answer-only path explicit and uses the
  student's maximum-mark entry as a coverage check.
- Mobile upload now adds direct camera capture, preview, order, rotation,
  replacement, deletion, low-resolution warning, progress, and retry while
  preserving the original PDF path.

## Remaining limitations

- A mark scheme is still required for exact question-by-question examiner
  marking.
- Provider latency varies; the server heartbeat distinguishes healthy slow
  work from a stalled request but cannot make the upstream model instant.
- One successful real paper is strong regression evidence, not a broad
  accuracy study across curricula or handwriting styles.

