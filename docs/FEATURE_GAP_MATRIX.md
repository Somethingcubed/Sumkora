# Feature gap matrix

| Feature | Existing state | Evidence | Action taken | Final state |
|---|---|---|---|---|
| Student/teacher login | WORKING | Browser and inherited regressions | Timed sessions and secure-cookie config | WORKING |
| Backend student ownership | PARTIAL | Ownership patterns existed, no negative suite | Protected result/question/file routes; cross-student tests | WORKING |
| Research authorization | MISSING | No research role/workbench | Added roles, guard, dashboard and export checks | WORKING foundation |
| 0606 scope | BROKEN | README, defaults, seed and practice were 0580 | 0606 defaults/seeds; analytics boundary; legacy preserved | WORKING for new flows |
| PDF upload | WORKING | Student and teacher routes | Added byte/page validation, hashes and failure state | WORKING |
| Durable processing | MISSING | Request-bound grading | Persisted stages and polling; still in-process | PARTIAL |
| OCR | PARTIAL | Provider adapters and cache | Auditable runs, retry/fallback, timing, warnings | PARTIAL: live fallback works |
| `qwen-vl-ocr-latest` | MISSING | Not configured | Primary configured and live tested | PARTIAL: provider returned 503/not listed |
| Paper-pack registry | MISSING | Flat legacy ingest only | Versioned packs/questions/criteria and 0606 importer | PARTIAL: review required |
| Criterion marking | BROKEN | Whole-question grading only | Persisted criterion schema and compatibility adapter | PARTIAL |
| Follow-through/dependencies | MISSING | Free-text mark scheme | Schema supports rules/dependencies | MISSING evaluator |
| Mathematical verification | MISSING | Exact/keyword checks | SymPy numeric, symbolic, derivative and integral checks | WORKING utility, not universal |
| Score uncertainty | MISSING | Single mark shown | Confirmed/provisional/possible range | WORKING |
| Marks-lost diagnosis | MISSING | Notes only | Topic/subtopic/skill/category/mechanism aggregation | WORKING foundation |
| Individual paper | WORKING | Existing result/report | Added ranges, diagnoses and question links | WORKING |
| Question evidence | MISSING | Flat result cards | Evidence, criteria, confidence and related attempts | WORKING |
| Paper history | PARTIAL | Dashboard score list | Dedicated 0606 attempt page | WORKING |
| Paper comparison | MISSING | No student comparison route | Selectable papers and comparability warnings | WORKING |
| Longitudinal profile | PARTIAL | Aggregate topic averages | Recency-weighted evidence states and provenance | WORKING foundation |
| Untested vs weak | MISSING | Absence treated as no insight | 0606 taxonomy emits explicit untested skills | WORKING |
| Recurrence/improvement | MISSING | No evidence sequence model | Synthetic 3-paper tests detect both | WORKING |
| Reports | WORKING | Student/teacher PDFs | Profile and assessment routes preserved | WORKING |
| Human correction | PARTIAL | Teacher final overrides | Research correction records with provenance | WORKING foundation |
| Model-run preservation | MISSING | Provider output mostly ephemeral | Versioned `model_runs` and raw response storage | WORKING |
| Regrade/A-B UI | MISSING | None | Experiment registry and run list only | PARTIAL |
| Research export | MISSING | None | Protected pseudonymized JSON/JSONL/CSV | WORKING |
| Local styling | BROKEN | Tailwind CDN did not render | Locked local Tailwind build | WORKING |
| Deployment config | MISSING | Local start only | Dockerfile, environment contract, storage adapter | PARTIAL |
| Production DB/storage | MISSING | SQLite/local files | Target architecture documented | MISSING |
| Coze integration | PARTIAL | Separate public 0580 prototype | Inspected and assigned optional demo role | PARTIAL/separate |
