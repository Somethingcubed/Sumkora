# Curriculum architecture

Updated: 19 August 2026

## Boundary

Sumkora keeps curriculum identity outside the document engine. The versioned
registry in `curricula.py` supplies the subject, course, level, topic taxonomy,
language preference, and practice source. The document engine still performs
ingestion, direct vision/reasoning assessment, evidence checks, diagnosis,
reports, history, and activity tracking.

Curriculum and language are deliberately independent. A Cambridge or AP paper
may be written in Chinese, and choosing Chinese as the interface language does
not silently change a student's curriculum.

## Current support

| Pathway | Levels | Status | Practice source |
| --- | --- | --- | --- |
| Cambridge IGCSE Additional Mathematics 0606 | Standard | Verified | Existing curated question bank |
| General Mathematics | Grades 1–12 | Beta | Generated and independently validated |
| Chinese National Mathematics | Grades 1–12 | Beta | Generated and independently validated |
| Cambridge IGCSE Mathematics 0580 | Core, Extended | Beta | Generated and independently validated |
| AP Precalculus | Full course | Beta | Generated and independently validated |
| AP Calculus AB | Full course | Beta | Generated and independently validated |
| AP Calculus BC | Full course | Beta | Generated and independently validated |
| AP Statistics | Full course | Beta | Generated and independently validated |
| Cambridge IGCSE Physics 0625 | Core, Extended | Beta | Generated and independently validated |
| Scottish Higher Physics | Higher | Beta | Generated and independently validated |

The existing 0606 analysis and bank-practice path remains unchanged. New
pathways are visibly labelled beta until representative real-paper benchmarks
meet the same release standard.

## Evidence and mastery rules

- Every new paper, help question, practice set, and generated question records
  its curriculum, level, and subject.
- Changing the active pathway never rewrites historical records.
- Progress only uses evidence from the student's active pathway and level.
- A topic with no attempted questions is omitted; it is not treated as weak.
- Uploaded questions that the student asks Sumkora to solve count as incorrect
  evidence, but only inside the active pathway.
- Generated questions must be stand-alone and include all required context.

## Generated-practice safeguards

AI practice is never presented as an official past paper. Questions are
generated in small batches, deduplicated, and passed to an independent model
that solves them from scratch. A question is saved only when that check confirms
that it is complete, in scope, appropriate for the selected level, and has a
correct worked solution and final answer. Physics checks also cover formula
choice, substitutions, units, significant figures, graphs, and experimental
reasoning. A partial or unvalidated worksheet is refused rather than shown.

## Curriculum references

The beta taxonomies are compact product groupings, not copies of syllabus text.
They are grounded in the active official frameworks:

- Cambridge IGCSE Mathematics 0580, 2025–2027:
  https://www.cambridgeinternational.org/programmes-and-qualifications/cambridge-igcse-mathematics-0580/
- Cambridge IGCSE Additional Mathematics 0606, 2025–2027:
  https://www.cambridgeinternational.org/programmes-and-qualifications/cambridge-igcse-mathematics-additional-0606/
- Cambridge IGCSE Physics 0625, 2026–2028:
  https://www.cambridgeinternational.org/Images/697209-2026-2028-syllabus.pdf
- College Board AP course frameworks:
  https://apcentral.collegeboard.org/courses
- Qualifications Scotland Higher Physics, session 2026–27 onward:
  https://www.sqa.org.uk/sqa/46507.html
- China compulsory mathematics curriculum (2022) and senior-high mathematics
  curriculum (2017 edition, revised 2020). The registry uses broad domains and
  exact grade selection because textbook sequencing can vary by edition.

## Adding or promoting a curriculum

1. Record the official framework version and compact taxonomy.
2. Add representative answer-only and detailed-marking benchmarks.
3. Define score, coverage, latency, and report acceptance thresholds.
4. Test image/PDF analysis, bilingual output, mastery isolation, and generated
   practice validation.
5. Run the full regression suite proving 0606 behavior remains unchanged.
6. Change `status` from `beta` to `verified` only after recording the evidence.
