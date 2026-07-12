# Document Change Log

## [2026-07-12 17:49] Correct document change log location

**Changed files:**
- `AGENTS.md`
- `docs/开发流程与里程碑.md`
- `docs/logs/document-changelog.md`

**Reason:**
- The user clarified that document change logs belong in `docs/logs/`, not the project root.

**Verification:**
- Moved the generated change log to `docs/logs/document-changelog.md`.
- Confirmed the project rule and development workflow reference the same path.

**Remaining verification:**
- Resume the paused review-report repair only after the user confirms the revised logging location.

## [2026-07-12 17:53] Apply document review report repairs

**Changed files:**
- `AGENTS.md`
- `docs/标航智导.md`
- `docs/开发流程与里程碑.md`
- `docs/教学内容与图谱数据规范.md`
- `docs/功能验收与赛事提交清单.md`
- `docs/superpowers/plans/2026-07-12-annotation-teaching-agent.md`
- `docs/文档评审修复记录.md`

**Reason:**
- Resolve the P0, P1, and P2 consistency, implementation-boundary, teaching-scope, workflow, and competition-compliance findings in `docs/文档评审报告.md`.

**Verification:**
- Confirmed the repair record covers all grouped findings A1-F5.
- Scanned for retired specifications such as `170+`, `62+`, `5 场景`, mixed D3/vis-network selection, screenshot diagnosis, and fixed `7±2` steps; no active conflicts remain.
- Confirmed new graph, mastery, scenario, task-conversion, runtime, submission, and log-location requirements are present in their governing documents.

**Remaining verification:**
- The official competition category name and final platform options must be checked in the submission-period management system.
- Team-specific prior foundation, contribution ratios, AI-use evidence, and all 62 source records require factual evidence before submission.

## [2026-07-12 18:43] Complete Task 1 content baseline

**Changed files:**
- `data/sources/source-registry.json`
- `data/curriculum/teaching-units.json`
- `tests/content/test_teaching_units.py`
- `docs/教学内容与图谱数据规范.md`
- `docs/superpowers/plans/2026-07-12-annotation-teaching-agent.md`
- `docs/logs/document-changelog.md`

**Reason:**
- Establish the approved four-domain source registry and minimum teaching-unit baseline before graph or application development.
- Record stable source, review, visibility, deterministic-evaluation, and error-taxonomy contracts for future content expansion.

**Verification:**
- `python -m pytest tests/content/test_teaching_units.py -q -p no:cacheprovider` completed with 8 passed tests.
- Parsed both JSON files successfully and confirmed four verified, publishable sources and four draft, student-invisible teaching units covering text, image, audio, and video.
- Confirmed all six official documentation and license URLs returned HTTP 200 on 2026-07-12.
- Completed independent specification and quality reviews with no remaining Critical or Important findings.

**Remaining verification:**
- A named content owner or teacher must review the four draft teaching units before any unit is marked `published` or student-visible.
- Mutable documentation and `develop`-branch license URLs must be pinned to a release/commit or retained as checksummed local archives before publication.

## [2026-07-12 20:10] Complete Task 2 capability graph

**Changed files:**
- `data/graph/graph-catalog.json`
- `data/graph/annotation-capability-graph.json`
- `data/graph/annotation-capability-graph.graphml`
- `scripts/build_graph.py`
- `scripts/validate_graph.py`
- `tests/graph/test_graph_integrity.py`
- `.gitignore`
- `tests/content/__pycache__/test_teaching_units.cpython-311-pytest-9.1.1.pyc` (removed)
- `docs/教学内容与图谱数据规范.md`
- `docs/superpowers/plans/2026-07-12-annotation-teaching-agent.md`
- `docs/logs/document-changelog.md`

**Reason:**
- Build the approved, reproducible graph v1 catalog and synchronized JSON/GraphML artifacts for four annotation domains.
- Resolve the graph/teaching-unit publication dependency by allowing draft taxonomy nodes while exposing only published, student-visible teaching-unit links as consumable.
- Record the project-owner-approved AI-agent development review policy without representing AI review as human or expert endorsement.

**Verification:**
- Captured the expected TDD RED with `PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/graph/test_graph_integrity.py -q -p no:cacheprovider`: 2 failed and 16 skipped because the catalog, artifacts, and scripts did not yet exist.
- Rebuilt both artifacts with `PYTHONDONTWRITEBYTECODE=1 python scripts/build_graph.py`; output reported 166 nodes and 240 edges.
- Ran `PYTHONDONTWRITEBYTECODE=1 python scripts/validate_graph.py data/graph/annotation-capability-graph.json`; schema/version, exact counts, unique IDs, endpoint/type rules, PRE acyclicity, task traceability, and scenario compatibility all passed.
- Ran the targeted graph suite with 18 passed tests and the full suite with 26 passed tests, both with bytecode and pytest cache generation disabled.
- Parsed GraphML and confirmed it contains the same 166 nodes and 240 edges as JSON; `git diff --check` returned no whitespace errors.

**Remaining verification:**
- Graph nodes, scenario overlays, and teaching-unit links remain development drafts and are not student-consumable. Domain-specific KNG claims and every `INSCN` override still require concept-level source expansion and independent content review before development publication.
- `MAPCERT` is a non-authoritative curriculum display mapping; official certificate/occupational-standard alignment must be verified against pinned primary sources before external use.
- Final competition submission or real-student release still requires human domain-expert confirmation in Tasks 6-9.

## [2026-07-12 20:41] Repair Task 2 provenance and parity review findings

**Changed files:**
- `data/sources/source-registry.json`
- `data/graph/graph-catalog.json`
- `data/graph/annotation-capability-graph.json`
- `data/graph/annotation-capability-graph.graphml`
- `scripts/build_graph.py`
- `scripts/validate_graph.py`
- `tests/graph/test_graph_integrity.py`
- `docs/教学内容与图谱数据规范.md`
- `docs/logs/document-changelog.md`

**Reason:**
- Resolve the independent specification review findings for claim-level provenance, the three-condition teaching-unit publication gate, INSCN base-rule compatibility, meaningful task support relations, and complete JSON/GraphML attribute parity.
- Replace syntactically resolvable but unsupported KNG citations with explicit claim scopes, honest draft states, and narrowly compatible references.

**Verification:**
- Added focused regression tests first and ran `PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/graph/test_graph_integrity.py -q -p no:cacheprovider`; the expected RED was 6 failed and 16 passed for the six reviewed gaps.
- Rebuilt JSON and GraphML from the corrected catalog; output remained exactly 166 nodes and 240 edges.
- Ran `PYTHONDONTWRITEBYTECODE=1 python scripts/validate_graph.py data/graph/annotation-capability-graph.json`; all eight checks passed, including claim provenance, publication traceability, and scenario compatibility.
- Ran the targeted graph suite with 23 passed tests and the full suite with 31 passed tests, both with bytecode and pytest cache generation disabled.
- `git diff --check` returned no whitespace errors.

**Remaining verification:**
- The release-pinned Label Studio document candidates and CVAT v2.51 annotation-format candidate remain `unverified`, `publishable=false`, and draft-only until their exact paths, contents, and licenses are checked directly.
- KNG nodes marked `curriculum_draft` intentionally have no authority source and cannot support a published/student-visible task until a compatible source or explicitly identified project-policy record is reviewed.
- Citation permission does not grant asset redistribution; all external media or datasets still require separate license evidence before packaging.

## [2026-07-12 20:55] Harden Task 2 canonical and semantic validation

**Changed files:**
- `data/graph/graph-catalog.json`
- `data/graph/annotation-capability-graph.json`
- `data/graph/annotation-capability-graph.graphml`
- `scripts/validate_graph.py`
- `tests/graph/test_graph_integrity.py`
- `docs/教学内容与图谱数据规范.md`
- `docs/logs/document-changelog.md`

**Reason:**
- Resolve code-quality findings for canonical teaching-unit snapshot validation, machine-readable primary task support, supporter data-type compatibility, and malformed node/edge robustness.

**Verification:**
- Added black-box regressions first; the expected RED was 8 failed and 22 passed for missing primary references, stale/unknown/duplicate teaching links, cross-domain support, uncovered primary knowledge, and non-object records.
- Rebuilt deterministic artifacts with the same 166 nodes and 240 edges.
- The targeted graph suite passed 30 tests; the full suite passed 38 tests with bytecode and pytest cache generation disabled.
- The standalone validator loaded canonical teaching units and passed schema/version, exact counts, IDs, endpoints/types, PRE acyclicity, provenance, task traceability, and scenario compatibility.
- `git diff --check` returned no whitespace errors.

**Remaining verification:**
- No new factual claims were introduced. Existing draft-source and human-release gates from the prior entry remain in force.

## [2026-07-12 21:23] Implement Task 3 text and image curriculum candidates

**Changed files:**
- `data/curriculum/text/teaching-units.json`
- `data/curriculum/image/teaching-units.json`
- `data/curriculum/teaching-units.json`
- `data/sources/source-registry.json`
- `data/graph/graph-catalog.json`
- `data/graph/annotation-capability-graph.json`
- `data/graph/annotation-capability-graph.graphml`
- `scripts/build_curriculum.py`
- `scripts/evaluate_exercise.py`
- `tests/content/test_text_image_evaluation.py`
- `tests/content/test_teaching_units.py`
- `docs/教学内容与图谱数据规范.md`
- `docs/superpowers/plans/2026-07-12-annotation-teaching-agent.md`
- `docs/logs/document-changelog.md`

**Reason:**
- Add five deterministic text candidates and five deterministic image candidates with explicit boundary, occlusion, truncation, ambiguity, error-feedback, and remediation rules.
- Add a reusable standard-library evaluator for exact, ordered, allowed-answer, partial-credit, and manual-review outcomes, plus a deterministic per-domain curriculum aggregator with the Task 3 audio/video transition fallback.
- Link all candidate units to existing TSK/CAP/KNG graph records without changing the fixed 166-node/240-edge graph size.
- Record Context7 documentation verification separately from the blocked direct tag-license check, and identify all self-authored semantics as local project policy rather than external authority.

**Verification:**
- Captured the required initial RED with `PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/content/test_text_image_evaluation.py -q -p no:cacheprovider`: 3 failed and 7 skipped because domain files, scripts, task links, and verification metadata were absent.
- Rebuilt `data/curriculum/teaching-units.json` twice through the test harness and confirmed byte-identical output while preserving the prior audio/video unit objects through the explicit transition fallback.
- Ran `PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/content/test_text_image_evaluation.py -q -p no:cacheprovider`; all 10 tests passed.
- Ran `PYTHONDONTWRITEBYTECODE=1 python scripts/validate_graph.py data/graph/annotation-capability-graph.json`; all graph checks passed with exactly 166 nodes and 240 edges.
- Ran the graph suite with 30 passing tests and the complete suite with 48 passing tests, with bytecode and pytest cache generation disabled.

**Remaining verification:**
- All ten Task 3 candidates remain `draft`, `student_visible=false`, and have empty `review_records`. Plan Step 3 remains unchecked until a separate AI agent that did not implement this batch records an approved independent content review; no such approval is claimed here.
- Context7 verified the stated documentation paths and content for Label Studio 1.19.0 and CVAT v2.51.0, but direct GitHub navigation to the matching tag license files remained blocked. The candidates therefore remain `publishable=false` pending tag-specific license verification.
- Text ambiguity and image semantic/occlusion decisions are explicitly local project policies, not external standards. Final competition or real-student release still requires human domain-expert confirmation.

## [2026-07-12 21:58] Repair Task 3 review findings without publishing

**Changed files:**
- `data/curriculum/text/teaching-units.json`
- `data/curriculum/image/teaching-units.json`
- `data/curriculum/teaching-units.json`
- `data/reviews/content-review-registry.json`
- `data/sources/source-registry.json`
- `data/graph/graph-catalog.json`
- `data/graph/annotation-capability-graph.json`
- `data/graph/annotation-capability-graph.graphml`
- `scripts/build_curriculum.py`
- `scripts/evaluate_exercise.py`
- `tests/content/test_text_image_evaluation.py`
- `tests/graph/test_graph_integrity.py`
- `docs/教学内容与图谱数据规范.md`
- `docs/logs/document-changelog.md`

**Reason:**
- Resolve review findings for strict JSON types, complete allowed-answer records, reachable diagnostic errors, lifecycle gates, prerequisites, local-policy provenance, and failed-review auditability.
- Correct and directly verify exact tagged Label Studio/CVAT document and license paths while separating external format facts from local semantic policy.
- Preserve 60 KNG, 166 nodes, and 240 edges by repurposing draft policy slots and swapping primary/direct-SUP relationships.

**Verification:**
- Initial focused RED: 12 failed and 13 passed for scalar coercion, permissive candidates, blanket diagnostics, prerequisites, review records, and policy KNG mappings.
- Source/publication RED: 2 failed and 25 deselected for stale pinned URLs and the absent builder gate; a separate RED covered diagnostic precedence/overlap.
- Direct raw GitHub GET returned HTTP 200 for Label Studio 1.19.0 Choices (2365 bytes), Labels (1827), Relations (968), and Apache LICENSE (11341); CVAT v2.51.0 format-cvat.md returned 22319 bytes and MIT LICENSE returned 1123.
- Deterministic curriculum rebuild preserved legacy audio/video; graph rebuild remained exactly 166 nodes and 240 edges.
- Task 3 tests: 28 passed; legacy content: 8 passed; graph integrity: 30 passed; full suite: 66 passed. Standalone graph validation passed all checks.

**Remaining verification:**
- Both recorded AI reviews are `changes_required` with `authorizes_publication=false`; corrected candidates still require independent re-review.
- All ten units remain `draft`, `student_visible=false`, and Task 3 Step 3 remains unchecked.
- Project-policy sources are development-only and `human_release_allowed=false`; formal competition or real-student release still requires human domain-expert confirmation.

## [2026-07-12 22:18] Restore stable KNG identities with additive policy overlays

**Changed files:**
- `data/curriculum/text/teaching-units.json`
- `data/curriculum/image/teaching-units.json`
- `data/curriculum/teaching-units.json`
- `data/graph/graph-catalog.json`
- `data/graph/annotation-capability-graph.json`
- `data/graph/annotation-capability-graph.graphml`
- `scripts/validate_graph.py`
- `tests/content/test_text_image_evaluation.py`
- `tests/graph/test_graph_integrity.py`
- `docs/教学内容与图谱数据规范.md`
- `docs/logs/document-changelog.md`

**Reason:**
- Restore seven KNG rows to their `c05413a` identity and meaning rather than reusing stable IDs for unrelated local semantics.
- Attach Task 3 local rules additively to meaning-aligned base KNGs through structured project-policy overlays.
- Return task primary knowledge and direct SUP mappings to stable base concepts without changing graph counts or version.

**Verification:**
- Added stable-identity and overlay regressions first; focused RED was 4 failed and 57 deselected for mutated base fields, missing validator checks, invalid overlay provenance acceptance, and stale task primaries.
- Focused GREEN was 4 passed and 57 deselected after restoring identities and adding overlays.
- Deterministic curriculum and graph rebuilds remained byte-identical to their generated outputs.
- Task 3 suite passed 28 tests; graph integrity passed 33 tests; full suite passed 69 tests.
- Standalone graph validation passed all checks with exactly 60 KNG nodes, 166 total nodes, 240 edges, and graph version 1.0.0.

**Remaining verification:**
- This commit is a corrected draft candidate only. The recorded prior AI reviews remain `changes_required` and do not authorize publication.
- All Task 3 units remain `draft` and hidden; Task 3 Step 3 remains unchecked pending re-review.
