# Self-review

Date: 4 August 2026

## Cycle 1 - new student

### Questions

- Would I understand what to do? Yes. The first line now says to upload photos
  of completed answers and explicitly says no question paper or mark scheme is
  required.
- Would I trust the value enough to start? More than before. A signed-out user
  can inspect a realistic synthetic result and can run one real photo through
  the same vision solver before creating an account.
- Does phone upload feel natural? The camera and gallery paths are separate,
  so the camera is optional rather than forced. Every page can be previewed,
  reordered, rotated, replaced, or removed with touch-sized controls.
- Would I know whether upload failed? Preparation and network upload now have
  a percentage. Interrupted uploads retain the selected pages and expose a
  retry action. Server validation messages are recovered from the response.

### Fixes made after review

- Kept gallery multi-select as the default and added camera capture as a
  separate action, resolving the conflict between fast phone capture and
  students who already used their camera/scanner app.
- Added a low-resolution warning before submission.
- Added exact server error extraction to the progress uploader instead of
  replacing useful validation errors with a generic message.
- Kept the dashboard structure unchanged.

## Cycle 2 - teacher and product reviewer

### Questions

- Is analysis trustworthy? The 15-page benchmark returned 55/80 against an
  expected approximately 56/80, covered all 20 parts, and matched the supplied
  80-mark total in one provider attempt.
- Are limitations clear? Completed-work-only output is labelled as an
  estimate and uses a range. Exact detailed marking still requires a mark
  scheme. Planned curricula are disabled and explicitly labelled as future
  support.
- Is the workflow reliable? Existing controlled retry, validation, heartbeat,
  failure deletion, and no-false-zero behavior are unchanged. The expanded
  suite passes.
- Did changes damage existing functionality? No. The dashboard was not
  redesigned, existing 0606 practice and progress behavior was preserved, and
  compatibility tests remained green.

### Fixes made after review

- Added a registry guard so a planned curriculum cannot be posted manually to
  the active analysis route.
- Kept private pages and reports out of the service-worker cache.
- Rate limited the public real-model trial and delete its temporary image
  immediately after processing.
- Documented rather than concealed the one-mark benchmark difference and the
  image-only warning limitation.

