# Curriculum architecture

Updated: 20 August 2026

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
| AP Physics 1: Algebra-Based | Full course | Beta | Generated and independently validated |
| AP Physics 2: Algebra-Based | Full course | Beta | Generated and independently validated |
| AP Physics C: Mechanics | Full course | Beta | Generated and independently validated |
| AP Physics C: Electricity and Magnetism | Full course | Beta | Generated and independently validated |
| 沪教版九年级化学（2026新版） | Grade 9 | Beta | Generated and independently validated |

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
reasoning. Chemistry checks cover formulae, equation balancing, ionic charges,
state symbols, reaction conditions, observations, calculations, and laboratory
safety. A partial or unvalidated worksheet is refused rather than shown.

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
- College Board AP Physics course frameworks:
  https://apcentral.collegeboard.org/courses/ap-physics-1
  https://apcentral.collegeboard.org/courses/ap-physics-2
  https://apcentral.collegeboard.org/courses/ap-physics-c-mechanics
  https://apcentral.collegeboard.org/courses/ap-physics-c-electricity-and-magnetism
- China compulsory mathematics curriculum (2022) and senior-high mathematics
  curriculum (2017 edition, revised 2020). The registry uses broad domains and
  exact grade selection because textbook sequencing can vary by edition.
- Ministry of Education 2024 compulsory-education textbook catalogue (revised
  for the 2022 curriculum standard), listing Wang Zuhao's Shanghai Education
  Publishing House Grade 9 Chemistry volumes. The 2026 pathway uses the 2024
  revised nine-chapter structure:
  https://www.moe.gov.cn/srcsite/A26/s8001/202408/W020250418502592948423.pdf

## Adding or promoting a curriculum

1. Record the official framework version and compact taxonomy.
2. Add representative answer-only and detailed-marking benchmarks.
3. Define score, coverage, latency, and report acceptance thresholds.
4. Test image/PDF analysis, bilingual output, mastery isolation, and generated
   practice validation.
5. Run the full regression suite proving 0606 behavior remains unchanged.
6. Change `status` from `beta` to `verified` only after recording the evidence.
