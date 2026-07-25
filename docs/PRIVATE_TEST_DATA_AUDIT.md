# Private test-data audit

Audit date: 25 July 2026

## Student scripts

Four owner-provided PDFs were copied into ignored local storage. Each file has
two raster pages with 270-degree rotation metadata, handwriting and red
teacher annotations; no useful native text layer was present. The shared page
renderer now normalizes these pages to portrait before OCR and evidence
preview generation without altering the source files.

- `20260422125354420_0001.pdf`
- `20260422125354420_0002 (1).pdf`
- `20260422135002935_0001.pdf`
- `20260422135002935_0002 (1).pdf`

Visual grouping indicates two split scripts:

- the `125354420` pair: Cambridge 0580/04, March 2025;
- the `135002935` pair: Cambridge 0580/02, March 2025.

They are therefore cross-syllabus OCR stress tests only. They were not
registered as 0606 attempts and do not update 0606 learner profiles. One page
from the second group was sent to CXSee under the owner's explicit test
authorization; the fallback model returned a usable transcription.

## Official 0606 material

The seven supplied October/November 2025 files contain components 11, 12 and
13 question papers/mark schemes plus a grade-threshold file. They are
zero-degree portrait scans without a useful native text layer. The local
importer registered three packs and produced 77 question/subpart rows and 260
criterion rows, all marked `parsed_requires_review`.

## Handling

- Private working root: ignored `private_test_data/`.
- Original files were copied, never moved or renamed at source.
- SHA-256 hashes were calculated for duplication/integrity checks.
- No PDF is tracked or staged by Git.
- Student scans and official copyrighted source documents are not included in
  exports, fixtures or screenshots.
- The API secret is not stored in this manifest or any tracked file.

See `PRIVATE_DATA_MANIFEST.md` for the file-level record.
