# Current state audit

Date: 4 August 2026

## What already works well

- The active student pipeline sends the complete answer PDF, plus an optional
  mark scheme, to the reasoning model. It does not use the old question-to-page
  OCR mapper.
- Multi-photo uploads are merged in the student's chosen order. Students can
  preview, rotate, reorder, and remove pages before submission.
- Processing has server-backed stages, percentages, elapsed time, and a live
  heartbeat. The page distinguishes slow work from a stalled or failed job.
- Technical failures do not become zero marks and failed analysis records are
  automatically removed.
- The dashboard, progress view, Mistake Book, targeted practice, one-question
  solver, bilingual interface, reports, and researcher visibility are covered
  by a broad automated suite.
- The supplied 15-page 0606 benchmark is a clear scan and matches the previous
  56/80 gallery-image benchmark documented in `STATUS.md`.

## What must not be changed

- The current dashboard information hierarchy and visual language.
- Whole-document marking, validation, controlled provider retry, score-range
  calibration, and the rule that model failures never record zero marks.
- Existing account, session, upload, paper, and progress data.
- The verified 0606 question bank and worksheet behavior.

## First-use and activation gaps found

- Before this pass, signed-out students could not see a representative result
  or test the real vision solver.
- Upload copy mentioned the optional mark scheme but did not make the
  answer-photos-only path sufficiently prominent.
- The first-paper screen did not expose the future curriculum boundary.

## Mobile problems found

- Gallery multi-select worked, but there was no prominent phone-camera action.
- Page replacement required remove-then-add rather than one direct control.
- Preparation status existed, but network upload progress and retry did not.
- Low-resolution images were accepted without an early warning.
- The manifest existed but no service worker or install prompt made the site a
  complete installable web experience.

## Technical risks

- Analysis runs in an in-process background task, so a deployment restart can
  interrupt active work.
- SQLite plus a single persistent volume is suitable for a small pilot, not
  horizontal scaling.
- Long whole-document model calls remain dependent on the provider gateway.
- Image quality warnings are advisory and cannot guarantee legibility.
- Public trial calls consume model capacity, so they are rate limited and are
  not saved as student progress.

## Implemented recommendations

- Add a public synthetic sample analysis and a rate-limited real one-question
  trial.
- Make answer-only instructions unmistakable on the analysis screen.
- Add phone camera input, direct replacement, touch-sized page controls,
  low-resolution warnings, upload progress, and retry.
- Add an app-shell service worker, offline fallback, manifest refinements, and
  install controls.
- Add a curriculum registry with a hard verified/planned boundary. Only 0606
  remains selectable until another module has its own validation evidence.

