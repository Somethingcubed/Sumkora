# OCR benchmark

Updated: 25 July 2026

## Scope and test data

The ignored owner-authorized corpus contains 99 raster pages:

- 91 pages across three official 0606 question-paper/mark-scheme pairs and one
  grade-threshold file;
- 8 pages across two split 0580 student scripts, used only as cross-syllabus
  OCR stress data and never imported into a 0606 learner profile.

The student scans contain dense handwriting, fractions, indices, diagrams,
crossed-out work, red teacher annotations and four logical paper pages on each
scanned sheet. Their PDF pages carry 270-degree rotation metadata. The official
0606 files are zero-degree portrait scans. None of these files has a useful
native text layer.

The live benchmark deliberately used a manageable two-page subset:

| Case | Conditions | Reference checks |
|---|---|---:|
| 0606 component 13, page 3 | Clean printed inequalities, powers, brackets and mark boxes | 7 tokens |
| 0580/04 script, scanned page 1 | Rotated four-up page, handwriting, formula sheet and red annotations | 6 numerical expressions |

This is 2 rendered pages, at least 3 top-level question labels and 13 manually
selected token/expression checks. It is not a complete transcription benchmark
and is not presented as an overall OCR-accuracy percentage.

## Method

The production CXSee path was called with the configured primary model
`qwen-vl-ocr-latest`, a 160 DPI PNG and the application OCR prompt. Each run
recorded the model actually used, fallback warning, latency, output length and
presence of manually selected reference tokens. Raw output, names, private
images and the API key were not written to tracked files or documentation.

The sideways student page was run once with the previous renderer and once
after metadata-rotation normalization.

## Results

| Case | Render | Model used | Latency | Checks found |
|---|---:|---|---:|---:|
| 0606 clean print | 1323 x 1871 portrait | qwen3-vl-plus fallback | 31.05 s | 6/7 |
| 0580 sideways baseline | 2646 x 1872 landscape | qwen3-vl-plus fallback | 88.27 s | 6/6 |
| 0580 normalized | 1872 x 2646 portrait | qwen3-vl-plus fallback | 71.25 s | 6/6 |

The renderer fix made the annotated scan upright for OCR and evidence previews
and reduced this matched call's latency by about 19%. Selected numerical-token
preservation remained 6/6 in both calls, so no transcription-accuracy
improvement is claimed from this small comparison.

The clean printed page preserved both inequalities, powers and both mark
values. The exact reference phrase `question 1` was not returned in that form,
showing that question-label normalization remains necessary even for clean
print.

## Failure categories and interpretation

- The primary configured OCR model was unavailable for all three calls; the
  auditable `qwen3-vl-plus` fallback completed them.
- Question-label formatting was less reliable than mathematical-token
  preservation on the clean page.
- Red annotations and printed/student separation were visually present but
  were not manually scored in this small token benchmark.
- Multi-page response reconstruction, faint pencil, radicals, logarithms,
  integrals, vectors and matrices were not individually scored here.
- Live latency was 31-88 seconds per dense page in this sample. End-to-end
  papers therefore remain too slow for synchronous processing at scale.

## Engineering change

`pdf_utils.page_render_matrix()` now normalizes only landscape pages carrying
90/270-degree metadata. Genuine unrotated landscape pages are left unchanged.
The same renderer is used by OCR and evidence previews. Original PDFs are
never modified. A deterministic test creates a 270-degree scan and verifies
that the output is portrait.

## Remaining work

Before accuracy claims or broader student testing:

1. obtain reliable availability for `qwen-vl-ocr-latest`;
2. expand the corrected subset across the listed mathematical notations;
3. label orientation, question numbers, annotation type and expression
   structure independently;
4. measure question-response mapping and multi-page reconstruction;
5. build a matched 0606 completed-script set with owner-reviewed ground truth;
6. report confidence intervals and failure counts alongside any aggregate.
