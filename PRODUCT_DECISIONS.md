# Product decisions

## Two experiences, upgraded in place

The repository already had most of the classroom and assessment workflow.
The reliable assessment and authentication foundations were extended in place,
while the obsolete teacher/classroom experience was removed from the active
product. Sumkora now has exactly two meaningful surfaces: the student product
and a private researcher workbench.

## Student-owned attempts

A paper belongs directly to the student who uploads it. Completed work creates
a private paper attempt without a class, assignment, question bank or
pre-registered paper pack. A mark scheme is optional. Analysis versions
preserve the uploaded sources, model configuration and results.

## Separate student accounts

Scripts, marks and profiles are personal educational records. Every
student-facing read is constrained by authenticated `student_id`; a URL alone
does not grant access. Research access is a different role and export mode.

Students register with a case-insensitive username and password, without email
or classroom data. Public registration always creates the student role. A
one-time recovery code is shown once at signup because the product does not
collect contact details; its digest is stored separately from the password and
the code is consumed when used.

## Whole-document assessment

Students always provide completed work. Without a mark scheme, Sumkora gives a
calibrated score range plus strengths and weaknesses. With a complete mark
scheme, Sumkora performs detailed marking. A question paper is never required.

New analyses send the complete document set to a reasoning model and validate
the structured result. Detailed mode then runs a second independent
whole-document audit before storing marks. The old OCR-to-single-page mapper is
retained only for historical compatibility and is not used by active analyses.

## Bilingual student experience

English and Simplified Chinese are first-class interface choices for
authentication, navigation and the principal student journey. The persistent
`EN / 中文` control keeps the current page when switching languages.

## Longitudinal and paper-centered

A single paper is noisy evidence, so profile claims require repeated attempts
and retain recency/all-time estimates. Individual-paper views remain central
because every longitudinal conclusion must be explainable back to a paper,
question, criterion and excerpt.

## Untested is not weak

No evidence is different from evidence of error. Sumkora lists untouched 0606
skills as `untested` and does not infer a weakness from absence. A first error
is an early signal; recurrence needs multiple papers.

## Uncertainty is visible

Document reading and marking can be ambiguous. Instead of forcing false precision, the
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
Automated marking still requires continued human calibration. Grade prediction is intentionally excluded.
No model is fine-tuned per student. Production use requires reviewed paper
packs, durable infrastructure, privacy approval and human calibration.
