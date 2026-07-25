# Product decisions

## Two experiences, upgraded in place

The repository already had most of the classroom and assessment workflow.
The reliable assessment and authentication foundations were extended in place,
while the obsolete teacher/classroom experience was removed from the active
product. Numera now has exactly two meaningful surfaces: the student product
and a private researcher workbench.

## Student-owned attempts

A paper belongs directly to the student who uploads it. A question paper,
completed answer script and mark scheme create a private paper attempt without
a class, assignment or pre-registered paper pack. Analysis versions preserve
the uploaded sources, detected metadata, OCR, model configuration and results.

## Separate student accounts

Scripts, marks and profiles are personal educational records. Every
student-facing read is constrained by authenticated `student_id`; a URL alone
does not grant access. Research access is a different role and export mode.

## Longitudinal and paper-centered

A single paper is noisy evidence, so profile claims require repeated attempts
and retain recency/all-time estimates. Individual-paper views remain central
because every longitudinal conclusion must be explainable back to a paper,
question, criterion and excerpt.

## Untested is not weak

No evidence is different from evidence of error. Numera lists untouched 0606
skills as `untested` and does not infer a weakness from absence. A first error
is an early signal; recurrence needs multiple papers.

## Uncertainty is visible

OCR and marking can be ambiguous. Instead of forcing false precision, the
product stores confidence and warnings and displays confirmed minimum,
provisional and possible maximum marks. Humans can append corrections without
erasing the model run.

## Research access is private

Raw student evidence, provider responses and correction history are more
sensitive than ordinary dashboard aggregates. The research workbench requires
a researcher/owner role; exports are pseudonymized by default. The inherited
`teacher` role is accepted as a compatibility alias for the same private owner
account, but cannot reach teacher routes.

## Limits

The evidence model is transparent but not psychometrically validated.
Criterion parsing is heuristic. Grade prediction is intentionally excluded.
No model is fine-tuned per student. Production use requires reviewed paper
packs, durable infrastructure, privacy approval and human calibration.
