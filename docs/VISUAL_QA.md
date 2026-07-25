# Visual QA

Updated: 25 July 2026

## Viewports and pages

Browser checks used configured viewports of 1440 x 900, 1024 x 768 and
390 x 844. The browser runtime applies its own display scale; horizontal
overflow was measured from document scroll/client width rather than inferred
from screenshot pixels.

Visually inspected:

- login and signup design system;
- new-student dashboard;
- three-document upload;
- paper list, comparison, strengths and settings;
- research overview, experiments, new experiment, OCR, grading, failures,
  student models and taxonomy;
- student paper PDF and research experiment PDF.

## Findings and changes

- Replaced every active logo wordmark and accessible label with Sumkora.
- Changed the symbol from N to S and added a matching SVG favicon/manifest.
- Added consistent browser titles, descriptions, canonical links and Open
  Graph product metadata.
- Preserved the restrained indigo/neutral visual system and existing layout.
- Verified the auth split layout on desktop and compact single-column mobile
  layout.
- Verified the upload flow keeps three distinct, readable file areas and one
  primary action on mobile.
- Verified principal student and research pages have no horizontal overflow.
- Verified browser console output is clean on inspected routes.
- Verified both PDFs have consistent typography, margins, section hierarchy,
  table boundaries, Sumkora footers and page numbers.
- Removed student-facing corrected-mapping terminology from the report.

## PDF render inspection

Generated artifacts:

- `output/pdf/student-report.pdf`
- `output/pdf/research-report.pdf`

Both were rendered to PNG at 120 DPI with Poppler. No clipping, overlap,
unexplained blank page, broken table, black glyph box or footer collision was
found. Automated tests also assert every text block remains inside page bounds.

## Remaining visual limitations

- Dense research tables rely on responsive scrolling/stacking and remain
  intentionally technical.
- Very long real paper titles and multi-page reports need continued fixture
  expansion even though current long-content bounds checks pass.
- Before/after screenshots are not committed because they may capture private
  account data; the audit records route-level results instead.
