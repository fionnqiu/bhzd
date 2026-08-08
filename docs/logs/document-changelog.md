# Document Change Log

## [2026-08-04 21:21] Add local project startup script

**Changed files:**

- `start-project.bat`
- `start-project.ps1` (removed)

**Reason:**

- Replace the PowerShell launcher with a double-clickable Windows batch file that starts or reuses the local FastAPI and Vite services, then opens the frontend and Swagger interfaces after readiness checks.

**Verification:**

- Ran `./start-project.bat --no-browser` from the repository root.
- Confirmed the batch file correctly reused the reachable FastAPI Swagger endpoint at `http://127.0.0.1:8787/docs` and Vite frontend at `http://127.0.0.1:5173`.

**Remaining verification:**

- Browser tab opening is controlled by omitting `--no-browser` and was not exercised during the non-interactive verification.

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

## [2026-07-12 22:32] Publish AI-reviewed Task 3 text and image units for development

**Changed files:**

- `data/curriculum/text/teaching-units.json`
- `data/curriculum/image/teaching-units.json`
- `data/curriculum/teaching-units.json`
- `data/reviews/content-review-registry.json`
- `data/sources/source-registry.json`
- `data/graph/annotation-capability-graph.json`
- `data/graph/annotation-capability-graph.graphml`
- `tests/content/test_text_image_evaluation.py`
- `tests/graph/test_graph_integrity.py`
- `docs/superpowers/plans/2026-07-12-annotation-teaching-agent.md`
- `docs/logs/document-changelog.md`

**Reason:**

- Record independent text and image re-reviews explicitly performed by `reviewer_type=ai_agent`, while retaining both historical `changes_required` review records for auditability.
- Publish exactly the five Task 3 text units and five Task 3 image units to the development-only student-visible index after approved AI review; keep legacy audio and video units draft and hidden.
- Make the ten canonical graph teaching-unit links consumable without changing taxonomy status, node counts, or edge counts.
- Complete Task 3 Step 3 only for AI-reviewed development publication. This does not imply human, teacher, or domain-expert review or authorize formal competition or real-student release.

**Verification:**

- Rebuilt `data/curriculum/teaching-units.json` with `python scripts/build_curriculum.py`; the index contains 12 units and retains the audio/video transition fallback.
- Rebuilt the generated graph with `python scripts/build_graph.py`.
- Ran `python -B -m pytest tests/content/test_text_image_evaluation.py -q -p no:cacheprovider`; all 30 tests passed.
- Ran `python -B -m pytest tests/content/test_teaching_units.py -q -p no:cacheprovider`; all 8 legacy content tests passed.
- Ran `python -B -m pytest tests/graph/test_graph_integrity.py -q -p no:cacheprovider`; all 33 graph tests passed.
- Ran `python -B scripts/validate_graph.py data/graph/annotation-capability-graph.json`; all checks passed with exactly 166 nodes and 240 edges.
- Ran `python -B -m pytest -q -p no:cacheprovider`; the complete suite passed all 71 tests.

**Remaining verification:**

- The approved reviewers are AI agents only. No human, teacher, or domain-expert review is claimed.
- Publication is limited to development use; both project-policy sources remain `publication_scope=development_only` and `human_release_allowed=false`.
- Formal competition submission and real-student release remain gated on human domain-expert confirmation.

## [2026-07-12 22:57] Harden Task 3 publication binding and generated-input boundaries

**Changed files:**

- `data/curriculum/legacy/teaching-units.json`
- `data/reviews/content-review-registry.json`
- `scripts/build_curriculum.py`
- `scripts/evaluate_exercise.py`
- `scripts/validate_graph.py`
- `tests/content/test_text_image_evaluation.py`
- `tests/graph/test_graph_integrity.py`
- `docs/教学内容与图谱数据规范.md`
- `docs/logs/document-changelog.md`

**Reason:**

- Bind each approved Task 3 unit review to a canonical SHA-256 digest of the reviewed content, excluding only the three top-level lifecycle fields, and require a full lowercase Git commit ID.
- Require every reviewed or published unit to declare a non-empty, unique list of nonblank source IDs whose records are verified, publishable, and citation-allowed.
- Reject coercible, non-finite, or out-of-range `allowed_answers.pass_score` values while retaining numeric `[0, 1]` boundaries and the `1.0` default.
- Gate published, visible, or consumable tasks on eligible provenance for their exact primary KNG and every linked teaching-unit rule KNG, including compatible project-policy overlays without accepting unrelated KNG evidence.
- Replace the generated central curriculum file as a fallback input with an explicit versioned audio/video legacy snapshot; per-domain sources supersede the matching legacy domain and legacy collisions are rejected.

**Verification:**

- Initial shared RED: Task 3 content had 19 failures and 33 passes for score, snapshot, digest, commit, and source-reference contracts; graph integrity had 2 failures and 33 passes for missing exact task provenance.
- A separate whitespace-source RED failed with the expected malformed-reference path before the nonblank-string check was added.
- Rebuilt the curriculum with `python -B scripts/build_curriculum.py`; output reported exactly 12 units, including the explicit audio/video fallback.
- Rebuilt the graph with `python -B scripts/build_graph.py`; output reported exactly 166 nodes and 240 edges.
- Ran `python -B -m pytest tests/content/test_text_image_evaluation.py -q -p no:cacheprovider`; all 52 Task 3 tests passed, including deletion/corruption independence, domain override, and byte determinism.
- Ran `python -B -m pytest tests/content/test_teaching_units.py -q -p no:cacheprovider`; all 8 legacy content tests passed.
- Ran `python -B -m pytest tests/graph/test_graph_integrity.py -q -p no:cacheprovider`; all 36 graph tests passed, including black-box primary/rule provenance mutations and eligible overlay acceptance.
- Ran `python -B scripts/validate_graph.py data/graph/annotation-capability-graph.json`; all checks passed with exactly 166 nodes and 240 edges.
- Ran `python -B -m pytest -q -p no:cacheprovider`; the complete suite passed all 96 tests.

**Remaining verification:**

- The ten approved reviews remain independent AI reviews limited to development publication; no human, teacher, domain-expert, competition, or real-student release approval is implied.
- Lifecycle-only changes intentionally do not alter `content_digest`; any other teaching-unit content change invalidates the approval until a new digest-bound review is recorded.
- The duplicated stable-KNG baseline manifest in validator/tests remains a minor maintenance concern and is intentionally outside this focused hardening change.

## [2026-07-13 09:52] Complete Tasks 4-5 development publication and review gates

**Changed files:**

- `data/assets/audio/task4-segmentation-alignment.authorization.json`
- `data/assets/audio/task4-segmentation-alignment.wav`
- `data/assets/audio/task4-structured-fixture-manifest.json`
- `data/curriculum/audio/01-foundations.json`
- `data/curriculum/audio/02-advanced.json`
- `data/curriculum/video/teaching-units.json`
- `data/curriculum/teaching-units.json`
- `data/graph/graph-catalog.json`
- `data/graph/annotation-capability-graph.json`
- `data/graph/annotation-capability-graph.graphml`
- `data/resources/audio/emotion-event-review.json`
- `data/reviews/content-review-registry.json`
- `data/reviews/scenario-review-registry.json`
- `data/scenarios/content-safety.json`
- `data/scenarios/customer-service.json`
- `data/scenarios/in-vehicle.json`
- `data/scenarios/medical.json`
- `data/sources/source-registry.json`
- `evidence/audio-learning-chain/app.js`
- `evidence/audio-learning-chain/ffprobe-mp4.json`
- `evidence/audio-learning-chain/ffprobe-webm.json`
- `evidence/audio-learning-chain/index.html`
- `evidence/audio-learning-chain/learning-loop.mp4`
- `evidence/audio-learning-chain/learning-loop.webm`
- `evidence/audio-learning-chain/learning-loop-desktop.png`
- `evidence/audio-learning-chain/learning-loop-mobile.png`
- `evidence/audio-learning-chain/recording-metadata.json`
- `evidence/audio-learning-chain/record-learning-loop.js`
- `evidence/audio-learning-chain/styles.css`
- `scripts/build_curriculum.py`
- `scripts/evaluate_exercise.py`
- `scripts/generate_task4_audio_evidence.py`
- `scripts/validate_scenarios.py`
- `tests/content/test_audio_advanced_review.py`
- `tests/content/test_audio_foundations_review.py`
- `tests/content/test_audio_learning_path.py`
- `tests/content/test_audio_review_integration.py`
- `tests/content/test_task5_lifecycle.py`
- `tests/content/test_text_image_evaluation.py`
- `tests/content/test_video_and_scenarios.py`
- `tests/content/test_video_review_fixes.py`
- `tests/graph/test_graph_integrity.py`
- `docs/教学内容与图谱数据规范.md`
- `docs/superpowers/plans/2026-07-12-annotation-teaching-agent.md`
- `docs/logs/document-changelog.md`
- `E:\\ObsidianWorkSpace\\logs\\codex\\Work Log 2026-07-13.md`

**Reason:**

- Complete the six-capability audio learning chain, authorized WAV and recorded learning-practice-feedback-remediation evidence, including the reviewed language, ambiguity, timestamp, asset, and remediation corrections.
- Add and publish three video teaching units plus four scenario documents with nine strict overrides and nine structured examples without duplicating the common curriculum.
- Retain all `changes_required` review history, record independent AI approvals with exact content digests, and publish all Task 4-5 units only for development use.
- Restore the three-field teaching-unit digest contract, reject malformed review scopes with `ValueError`, and enforce development-only boundaries through the approved AI review and qualified local project-policy source.
- Mark all Task 4 and Task 5 plan steps complete after the reviewed implementation and evidence gates passed.

**Verification:**

- Followed TDD for Task 5 review hardening (`13 failed, 2 passed` then target GREEN), the development-boundary bypass (`8 failed` then GREEN), and Task 4 publication (`4 failed, 26 passed` then audio GREEN `48 passed`).
- Independent AI reviewers approved the Task 4 foundation and advanced content, the Task 5 specification and code quality, and the final Task 4 publication integration; no human or expert approval was recorded.
- The complete test suite passed `234` tests; graph validation passed at exactly `166` nodes and `240` edges; scenario validation passed `4` scenarios, `9` overrides, and `9` examples.
- Temporary rebuilds of the central curriculum JSON, graph JSON, and GraphML were byte-identical to the committed artifacts.
- The 24 audio asset references resolve to 23 structured fixtures and one authorized WAV with matching SHA-256 values. WAV, MP4, and WebM decode successfully; desktop/mobile screenshots and an MP4 middle frame were visually checked.

**Remaining verification:**

- All approvals are from independent AI agents and authorize development use only. Formal competition submission and real-student release still require human domain-expert review.
- The MP4/WebM evidence files contain video only. The evidence proves that the authorized WAV is loaded and used by the timeline exercise, but it does not prove audible playback within the recording.
- Synthetic structured fixtures and one authorized sample do not establish real-world audio or video annotation performance.

## [2026-07-14 19:29] Split Task 6 into system delivery and document submission

**Changed files:**

- `docs/superpowers/plans/2026-07-12-annotation-teaching-agent.md`
- `docs/logs/document-changelog.md`

**Reason:**

- Separate implementation and verification of the teaching application from the later production of the operation manual and competition submission package, as requested by the user.

**Verification:**

- Checked the revised plan preserves all original Task 6 outcomes: application functionality, automated and end-to-end verification, user trials, operation manual, four-directory submission package, and clean-environment checks.
- Confirmed Task 7 explicitly depends on completed Task 6 evidence and returns system defects to Task 6.

**Remaining verification:**

- Neither Task 6 nor Task 7 has been implemented; their respective verification gates remain pending.

## [2026-07-14 19:55] Record the approved Task 6 application design

**Changed files:**

- `docs/superpowers/specs/2026-07-14-task6-teaching-application-design.md`
- `docs/logs/document-changelog.md`

**Reason:**

- Persist the user-approved Task 6 brief as an implementation-grade design for the local Web teaching application, deterministic learning engine, file diagnostics, automated verification, and real-user trial gate.

**Verification:**

- Checked that the specification covers every Task 6 function and excludes the Task 7 manual and competition package.
- Checked the design against the published-unit gate, 166-node/240-edge graph contract, deterministic exercise evaluator, PRE remediation algorithm, mastery formula, four diagnostic formats, screenshot restriction, and Windows browser acceptance requirements.
- Scanned the specification for placeholders, contradictory technology choices, ambiguous completion claims, and unsupported human-trial assertions; none remain.

**Remaining verification:**

- The written specification still requires the user's final review before the implementation plan is created.
- Real teacher/student trials remain gated on human domain-expert release approval and coordinated participants.

## [2026-07-14 20:00] Add the reviewed Task 6 implementation plan

**Changed files:**

- `docs/superpowers/plans/2026-07-14-task6-teaching-application.md`
- `docs/superpowers/specs/2026-07-14-task6-teaching-application-design.md`
- `docs/logs/document-changelog.md`

**Reason:**

- Convert the user-reviewed Task 6 design into TDD-sized implementation increments with exact files, commands, verification expectations, commit checkpoints, and an explicit real-human trial gate.

**Verification:**

- Mapped every design section to one or more implementation tasks covering canonical data, publication gates, graph planning, evaluator parity, learning state, scenarios, task conversion, four-format diagnostics, application UI, E2E coverage, accessibility, browser checks, and trial evidence.
- Recorded the user's final written-spec approval in the Task 6 design status.
- Checked that the plan never marks real trials complete without human domain release and genuine participant records.
- Scanned the plan for unresolved placeholders and inconsistent public interfaces.

**Remaining verification:**

- Application code has not started; the execution approach must be selected before following the plan.

## [2026-07-14 20:08] Stabilize Windows baseline verification

**Changed files:**

- `.gitattributes`
- `docs/superpowers/plans/2026-07-14-task6-teaching-application.md`
- `docs/logs/document-changelog.md`

**Reason:**

- Prevent system-level `core.autocrlf=true` from converting generated JSON and GraphML authority files to CRLF and breaking byte-determinism tests in fresh Windows worktrees.
- Supply the required scenario file arguments in the Task 6 verification commands.

**Verification:**

- Reproduced both deterministic-build failures and confirmed `git ls-files --eol` reported `i/lf w/crlf` for the compared authority files.
- Confirmed the scenario validator CLI requires one or more positional scenario paths.

**Remaining verification:**

- Recreate the clean worktree so the new attributes apply, then rerun the full Python baseline and both validators before application implementation.

## [2026-07-15 23:38] Record verified Task 6 engineering status and real-trial gate

**Changed files:**

- `evidence/user-trials/README.md`
- `evidence/user-trials/trial-protocol.md`
- `evidence/user-trials/trial-record-template.md`
- `evidence/user-trials/session-summary.schema.json`
- `docs/superpowers/plans/2026-07-12-annotation-teaching-agent.md`
- `docs/superpowers/specs/2026-07-14-task6-teaching-application-design.md`
- `docs/logs/document-changelog.md`

**Reason:**

- Record that Task 6 engineering and browser verification are complete while preparing blank, non-fabricated materials for the separate real-human trial gate.
- Mark only Task 6 Steps 1-2 complete and preserve Step 3 as pending until authentic release and participant evidence exists.

**Verification:**

- `python -m pytest -q` passed: 234 tests.
- `python scripts/validate_graph.py data/graph/annotation-capability-graph.json` passed: 166 nodes and 240 edges.
- `python scripts/validate_scenarios.py data/scenarios/medical.json data/scenarios/customer-service.json data/scenarios/in-vehicle.json data/scenarios/content-safety.json` passed: 4 scenarios, 9 overrides, and 9 examples.
- `npm --prefix app test -- --run` passed: 19 files and 418 tests; `npm --prefix app run build` passed; `npm --prefix app run test:e2e` passed: 28 Chromium/Edge tests.
- Real-browser inspection passed at 1440x900 and 390x844, including keyboard focus and reduced motion. `rg -n "通过试用|全部满意|教师已批准|学生已完成" evidence/user-trials` returned no matches, and the session schema has all required fields with no `default` keys.

**Remaining verification:**

- A human domain-release decision and 2-3 genuine participant records, feedback, revisions, and retest outcomes are still required before Task 6 Step 3 can be checked or external trial/release claims can be made.

## [2026-07-17 22:56] Rebuild the Agent platform documentation baseline

**Changed files:**

- Added `docs/superpowers/specs/2026-07-17-agent-platform-design.md`.
- Updated `docs/标航智导.md`.
- Rebuilt `docs/开发流程与里程碑.md`.
- Rebuilt `docs/功能验收与赛事提交清单.md`.
- Deleted the superseded `docs/superpowers/plans/2026-07-12-annotation-teaching-agent.md` and `docs/superpowers/plans/2026-07-14-task6-teaching-application.md`.
- Deleted the superseded `docs/superpowers/specs/2026-07-12-annotation-teaching-agent-design.md` and `docs/superpowers/specs/2026-07-14-task6-teaching-application-design.md`.
- Deleted the one-time `docs/文档评审报告.md` and `docs/文档评审修复记录.md`.
- Updated `app/src/tasks/productMetadata.ts` and `app/tests/tasks/taskConverter.test.ts` to replace source anchors that pointed at deleted specifications.
- Updated `docs/logs/document-changelog.md`.

**Reason:**

- Replace the obsolete deterministic-application planning set with one Windows-first real-Agent design covering authenticated users, a single hidden-route administrator, encrypted multi-provider configuration, native Xunfei Xingchen/Spark adapters, Chat Completions, Anthropic Messages, typed teaching tools, streaming execution, and user confirmation gates.
- Align the product definition, milestones, acceptance gates, and competition narrative with the approved “weak navigation, strong Agent, embedded tools” interaction model.

**Verification:**

- Confirmed the new design explicitly distinguishes the verified current React teaching baseline from the unimplemented authentication, backend, LLM, admin, and Agent target state.
- Confirmed the new milestone and acceptance documents preserve deterministic scoring, diagnostics, mastery, PRE planning, source, privacy, and real-trial boundaries.
- Searched the remaining documentation for deleted planning filenames and legacy four-mode/LLM claims.
- Followed TDD for product-metadata source anchors: the focused task-converter suite first failed exactly 2 provenance assertions, then passed all 47 tests after the minimal source-reference update.
- Confirmed no remaining application or documentation references point to the deleted Task 1-7 or Task 6 planning files.
- Documentation and requirement scans passed with no placeholders, deleted references, legacy four-mode claims, or obsolete shortest-path/platform-completion wording.
- `git diff --check` passed; Git reported only the existing Windows line-ending conversion notices.
- `npm --prefix app test -- --run` passed: 19 files and 418 tests.
- `npm --prefix app run build` passed, including graph-chunk isolation verification; the existing Vite chunk-size advisory remains non-blocking.

**Remaining verification:**

- The new implementation plan must not be generated until the user reviews and approves the written design specification.
- Actual provider request fields, account permissions and live connectivity remain implementation-time verification items that require current official documentation and valid credentials.

## [2026-07-17 23:26] Add the reviewed Agent platform implementation plan

**Changed files:**

- Added `docs/superpowers/plans/2026-07-17-agent-platform-implementation.md`.
- Updated `docs/superpowers/specs/2026-07-17-agent-platform-design.md`.
- Updated `docs/开发流程与里程碑.md`.
- Updated `docs/logs/document-changelog.md`.

**Reason:**

- Convert the user-reviewed Windows-first Agent platform design into a single executable plan with explicit files, TDD-sized steps, RED/GREEN commands, security boundaries, provider gates, verification commands, and commit checkpoints.
- Keep the existing deterministic teaching capabilities as the baseline while sequencing authentication, administrator configuration, four model protocols, typed tools, Agent orchestration, embedded UI, Windows verification, and genuine trials.

**Verification:**

- Plan structure scan passed: 16 tasks, 16 file sections, and 16 commit checkpoints.
- Placeholder scan found no `TODO`, `TBD`, incomplete implementation instruction, or cross-task shorthand.
- Coverage scan confirmed Windows, SQLite, email/SMTP, single `/admin`, AES-256-GCM, all four provider protocols, primary/fallback roles, all eight typed tools, confirmation events, Agent Cockpit, later Linux/Docker, and genuine trials each map to plan steps.
- Checked provider event names, tool names, Cookie names, confirmation semantics, and the design/plan links for consistency.

**Remaining verification:**

- Implementation has not started; every task still requires its own reviewed brief or execution checkpoint and fresh RED/GREEN evidence.
- Xunfei Xingchen/Spark request fields, signatures, account permissions, and live connectivity remain behind the explicit official-contract hard gate in Task 9.

## [2026-07-20 20:53] Add the Kimi-layout Agent Cockpit Pencil design

**Changed files:**

- Added `designs/APP.pen`.
- Updated `docs/logs/document-changelog.md`.

**Reason:**

- Create the user-approved frontend design draft before implementation, using Kimi only for layout, whitespace, collapsed navigation and progressive disclosure while strictly applying the `designs` directory's Pinguo/Apple tokens and component language.
- Cover the design foundation, minimal first-run entry, active Agent run with an on-demand execution drawer, write-action confirmation, and the 390 x 844 mobile adaptation in one Pencil source file.

**Verification:**

- Confirmed `designs/APP.pen` was saved to disk at 331,138 bytes and the editor's unsaved marker cleared.
- Pencil returned exactly five top-level frames: design foundation, first-run entry, active run, write confirmation, and mobile run.
- Fresh full-document `snapshot_layout` verification at depth 8 reported `No layout problems.`
- Individually reviewed screenshots for all four product screens; the confirmation overlay was repaired after an initial hierarchy issue and then revalidated with no clipping.

**Remaining verification:**

- The user must visually approve the Pencil draft before any frontend implementation or refactor begins.
- No PNG, PDF, HTML, or additional `.pen` file was exported, as requested.

## [2026-07-20 21:24] Add light and dark color systems to the Agent Cockpit design

**Changed files:**

- Updated `designs/APP.pen`.
- Updated `docs/logs/document-changelog.md`.

**Reason:**

- Preserve the approved Kimi-inspired layout while applying a richer Apple/Pinguo semantic color system in paired light and dark themes.
- Improve the readability of success, warning, and indigo content on tinted surfaces without changing screen structure, copy, dimensions, or frontend code.

**Verification:**

- Confirmed `designs/APP.pen` contains the `mode: light/dark` theme axis and ten paired top-level boards covering foundations, first-run, Agent run, write confirmation, and mobile run.
- Recalculated six foreground/surface pairs; all pass WCAG AA at or above `4.5:1`, including light success `5.20:1`, light warning `5.01:1`, and dark indigo `6.70:1`.
- Reviewed light and dark screenshots for the first-run capability states and write-confirmation states.
- Saved the Pencil document to disk, confirmed the editor dirty marker cleared, and reran a depth-8 full-document layout scan with `No layout problems.`

**Remaining verification:**

- The user must approve the final dual-theme Pencil design before frontend implementation begins.
- No PNG, PDF, HTML, additional `.pen` file, or frontend code was created or modified.

## [2026-07-20 21:30] Optimize the light-mode Agent Cockpit sidebar

**Changed files:**

- Updated `designs/APP.pen`.
- Updated `docs/logs/document-changelog.md`.

**Reason:**

- Replace the near-black sidebar in the light desktop boards with an Apple/Pinguo system-gray navigation surface that visually belongs to the light theme.
- Establish reusable sidebar semantic tokens for background, surfaces, borders, text hierarchy, active navigation, and progress states instead of continuing with hardcoded dark colors.

**Verification:**

- Reviewed the updated `02L Agent 运行` and `03L 写操作确认` screenshots; both now use the same light sidebar hierarchy while preserving layout, copy, and dimensions.
- Confirmed the dark confirmation board remains visually unchanged.
- Recalculated six key sidebar foreground/background pairs; all pass WCAG AA, with the lowest contrast at `4.54:1`.
- Saved `designs/APP.pen` to disk at 676,630 bytes, confirmed the editor dirty marker cleared, and reran a depth-8 full-document layout scan with `No layout problems.`

**Remaining verification:**

- The user must visually approve the revised light sidebar before frontend implementation begins.
- No additional design files, exported assets, or frontend code were created or modified.

## [2026-07-20 21:43] Remove reverse-theme component surfaces

**Changed files:**

- Updated `designs/APP.pen`.
- Updated `docs/logs/document-changelog.md`.

**Reason:**

- Remove pure-black component backgrounds from light product boards and pure-white component backgrounds from dark product boards.
- Replace reverse-theme surfaces with semantic brand-blue and emphasis-surface tokens so brand, primary actions, task summaries, and next-step cards remain prominent without breaking theme continuity.

**Verification:**

- Reviewed screenshots for all eight light and dark product boards covering first-run, Agent run, write confirmation, and mobile states.
- Confirmed light boards no longer contain pure-black product component surfaces and dark boards no longer contain pure-white product component surfaces; overlay scrims and the foundation color swatches remain intentional exceptions.
- Recalculated eight key brand and emphasis foreground/background pairs; all pass WCAG AA, with the lowest contrast at `4.90:1`.
- Saved `designs/APP.pen` to disk at 678,892 bytes, confirmed the editor dirty marker cleared, and reran a depth-8 full-document layout scan with `No layout problems.`

**Remaining verification:**

- The user must visually approve the cross-theme surface update before frontend implementation begins.
- No additional design files, exported assets, or frontend code were created or modified.

## [2026-07-22 22:46] Add administrator console boards to the Pencil design

**Changed files:**

- Updated `designs/APP.pen`.
- Added `designs/exports/W3ZMrC.png`.
- Added `designs/exports/rzhla.png`.
- Updated `docs/logs/document-changelog.md`.

**Reason:**

- Continue the approved Pencil canvas design with an administrator console surface.
- Cover model configuration gateway, model token usage, supplier token usage, platform account management, and account token usage in both light and dark modes.

**Verification:**

- Confirmed the active Pencil editor was `/e:/AgentWorkspaces/bhzd/designs/APP.pen`.
- Added two top-level frames: `05L 管理员 · Light` and `05D 管理员 · Dark`.
- Ran `snapshot_layout` checks on both new frames after height repairs; both returned `No layout problems.`
- Exported and visually reviewed both PNG previews for nonblank rendering and expected light/dark theme application.

**Remaining verification:**

- The user should visually approve the administrator console boards before frontend implementation begins.

## [2026-07-22 23:25] Implement the administrator console at /amdin

**Changed files:**

- Updated `app/src/app/router.tsx`.
- Updated `app/src/app/App.tsx`.
- Updated `app/src/admin/AdminPage.tsx`.
- Updated `app/src/app/app.css`.
- Added `app/tests/admin/AdminPage.test.tsx`.
- Added `app/tests/app/router.test.tsx`.
- Added `bhzd-amdin-light.png`.
- Added `bhzd-amdin-dark.png`.
- Updated `docs/logs/document-changelog.md`.

**Reason:**

- Restore the administrator console from the approved Pencil boards as a real frontend route.
- Use the user-specified `/amdin` route spelling while preserving the existing administrator login and provider-management API behavior.
- Keep the first viewport aligned with the Pencil light/dark administrator boards and move the live provider CRUD surface below the matched dashboard viewport.

**Verification:**

- `npx tsc --noEmit` passed after the final code adjustment.
- `npm run test:run -- tests/admin/AdminPage.test.tsx tests/app/router.test.tsx` passed with 3 tests.
- `npm run test:run` passed with 27 tests after the final code adjustment.
- Browser-verified `http://127.0.0.1:5174/amdin` at a 1440 x 960 viewport with mocked admin APIs; all five requested modules were visible.
- Browser-verified `http://127.0.0.1:5174/amdin?theme=dark`; `data-theme="dark"` was applied and the account token usage module was visible.
- Saved runtime screenshots as `bhzd-amdin-light.png` and `bhzd-amdin-dark.png`.

**Remaining verification:**

- `npm run build` still fails at the existing `verify:graph-chunk` step because the built manifest has no `GraphWorkspace` entry; `tsc` and `vite build` completed before that verifier failed.
- The user should visually approve the runtime `/amdin` page against the Pencil board before further admin data wiring.

## [2026-07-23 00:20] Remove obsolete Node backend remnants

**Changed files:**

- Updated `.env.example`.
- Updated `docs/标航智导.md`.
- Updated `docs/开发流程与里程碑.md`.
- Deleted `docs/superpowers/plans/2026-07-17-agent-platform-implementation.md`.
- Deleted `docs/superpowers/specs/2026-07-17-agent-platform-design.md`.
- Updated `docs/logs/document-changelog.md`.

**Reason:**

- Remove obsolete Node.js/Fastify/better-sqlite3 backend guidance after the active server moved to Python/FastAPI/SQLite.
- Keep front-end Node.js usage scoped to the React/Vite toolchain while preventing stale server startup and test commands from guiding future work.

**Verification:**

- Removed the old registered worktrees `agent-platform-task1` and `task6-teaching-application`, including their stale Node backend directories and references.
- Verified `git worktree list` now shows only `E:/AgentWorkspaces/bhzd`.
- Ran `rg -n "Fastify|better-sqlite3|npm --prefix server|npm.cmd --prefix server|Node.js/TypeScript|TypeScript 服务|Nodemailer|Zod|tsx watch|hash-admin-password|app/server|app\\server" . -S --glob '!app/node_modules/**' --glob '!app/dist/**' --glob '!app/package-lock.json' --glob '!designs/**' --glob '!.git/**' --glob '!docs/logs/document-changelog.md'`; no matches.
- Ran `python -m pytest server/tests -q`; 20 tests passed.

**Remaining verification:**

- None.

## [2026-07-23 00:26] Redraw administrator console Pencil boards

**Changed files:**

- Updated `designs/APP.pen`.
- Added `designs/exports/FOhpj.png`.
- Added `designs/exports/tB3BV.png`.
- Updated `docs/logs/document-changelog.md`.

**Reason:**

- Recreate the administrator console boards in the active Pencil canvas after the current file no longer contained admin boards.
- Cover model configuration gateway, model token usage, supplier token usage, platform account management, and account token usage in both light and dark modes.

**Verification:**

- Confirmed the active Pencil editor was `/e:/AgentWorkspaces/bhzd/designs/APP.pen`.
- Added two top-level frames: `05L 管理员 · Light` and `05D 管理员 · Dark`.
- Ran `snapshot_layout` checks for both frames; both returned `No layout problems.`
- Exported and visually reviewed the light and dark PNG previews, then repaired an initial horizontal overflow so the supplier and account token modules fit within the 1440 x 960 boards.

**Remaining verification:**

- The user should visually approve the redrawn administrator console boards before any further frontend alignment work.

## [2026-07-23 00:42] Pixel-update the runtime administrator page

**Changed files:**

- Updated `app/src/admin/AdminPage.tsx`.
- Updated `app/src/app/app.css`.
- Updated `app/tests/admin/AdminPage.test.tsx`.
- Updated `bhzd-amdin-light.png`.
- Updated `bhzd-amdin-dark.png`.
- Updated `docs/logs/document-changelog.md`.

**Reason:**

- Align the runtime `/amdin` administrator page with the newly redrawn Pencil administrator boards.
- Preserve the existing administrator login and provider CRUD surface while replacing the first viewport with the new model gateway, token usage, supplier usage, platform account, and account token layout.

**Verification:**

- `npx tsc --noEmit` passed.
- `npm run test:run` passed with 27 tests across 4 files.
- Browser-verified `http://127.0.0.1:5174/amdin` and `http://127.0.0.1:5174/amdin?theme=dark` at 1440 x 960 with mocked admin APIs; both rendered the expected theme, no horizontal overflow, right modules ended at x=1408, and the alert bar ended at y=942.
- `npm run build` completed `tsc --noEmit` and `vite build`, then failed at the existing `verify:graph-chunk` gate because the manifest has no `GraphWorkspace` entry.

**Remaining verification:**

- The `verify:graph-chunk` build gate remains unresolved and is outside this administrator-page visual update.

## [2026-07-24 00:30] Add Agent orchestration, tool gateway and model protocol design docs; trim completed milestones

**Changed files:**

- `docs/Agent编排实现方案.md` (new)
- `docs/工具网关封装方案.md` (new)
- `docs/模型协议适配方案.md` (new)
- `docs/开发流程与里程碑.md` (edited)
- `docs/logs/document-changelog.md` (appended)

**Reason:**

- User requested a complete plan to finish Agent orchestration (A6), tool gateway encapsulation (A5) and the four model protocol adapters (A4), placed under `docs/`.
- User also requested removing obsolete already-implemented plan docs. Investigation found `docs/superpowers/` (referenced by the dev-flow doc) had already been deleted earlier; the four remaining md docs all still hold value. User chose to trim the dev-flow doc instead: collapse completed B0/A1/A2/A3 milestones into a "done" summary and keep the unimplemented A4-A8/D1-D2 detail.

**Verification:**

- Confirmed the three new design docs align with current code state: reuse existing `agent_runs`/`tool_calls`/`pending_confirmations`/`learning_profiles`/`provider_configs` tables, mirror the 8 event types in `app/src/agent/agentEvents.ts`, and reference concrete files (`agent/graph.py`, `repositories.py::_execute_confirmed_tool`, `security.py::decrypt_secret`).
- Confirmed the trimmed dev-flow doc preserves the unimplemented A4-A8/D1-D2 milestones and the technical interface boundary table; only the completed B0/A1/A2/A3 rows were condensed.
- Confirmed the broken `docs/superpowers/specs|plans` references were replaced with pointers to the three new design docs.

**Remaining verification:**

- The three design docs are plans only; no implementation code was written this round. A4/A5/A6 implementation must follow their step/file lists and pass the acceptance criteria stated in each doc.
- `plan.updated` event is defined in the orchestration doc but not yet in frontend `agentEvents.ts`; needs synchronized addition during A6 implementation.
- A2 email verification / password reset and A3 `test_provider` remain stubs pending real SMTP and model connectivity.

## [2026-07-27 20:52] A4 provider adapter contract hardening

**Changed files:**

- `server/bhzd_py/providers/chat_completions.py`
- `server/bhzd_py/providers/anthropic_messages.py`
- `server/bhzd_py/providers/xunfei_xingchen.py`
- `server/bhzd_py/providers/xunfei_spark.py`
- `server/tests/test_providers_contract.py`
- `docs/logs/document-changelog.md`

**Reason:**

- Complete A4 offline contract: unified ModelEvent parsing, tool-call aggregation, error classes, Spark route separation, and mockable connection tests.

**Verification:**

- `python -m pytest tests/test_providers_contract.py tests/test_auth_admin_provider.py tests/test_conversations_agent.py tests/test_agent_graph.py -q` → 21 passed

**Remaining verification:**

- Real-network desensitized smoke tests still require admin-configured credentials per protocol.

## [2026-07-27 21:20] Add XingChen platform deployment architecture section

**Changed files:**

- `docs/标航智导.md` (added §13.5)
- `docs/logs/document-changelog.md` (appended)

**Reason:**

- User requested documenting the architecture for publishing the 标航智导 agent to the 讯飞星辰 (iFlytek XingChen) Agent platform, based on actual screenshots of the workflow canvas node palette (workflow ID 652929, custom ID 07e522).
- The new section covers platform paradigm constraints, three deployment topology comparisons, tool exposure layer positioning, platform-side build checklist, API publish format, and retained/lost capability mapping.
- Explicitly distinguishes "using iFlytek model as LLM brain" (Phase 3 A4) from "publishing agent to platform" (this section), a recurring point of confusion.

**Verification:**

- Confirmed insertion point between Phase 4 (line 849) and 十四 (line 853); new section numbered 13.5 with 6 subsections.
- Node palette categories verified against 3 user-provided screenshots: 基础节点(3), 工具(4), 知识&数据(5), 逻辑(4), 转换(3), 其他(1).
- Canvas state confirmed as empty skeleton (Start → End only).
- Cross-references to existing docs (第五章 prompt, Phase 3 A4/A5/A6, 第十章 knowledge base, `chat_completions.py`) are consistent with current file contents.

**Remaining verification:**

- Agent智能决策 node's exact configuration fields (role setting, knowledge base binding, tool binding) require screenshot of the node's detail panel — not yet provided.
- Publish tab details (API key generation, channel selection checkboxes) require screenshot of the 发布 tab — not yet provided.
- Tool HTTP interface signatures are design-stage proposals; final contracts depend on A5/A6 implementation.

## [2026-07-30 00:26] Add product requirements document (PRD)

**Changed files:**

- `docs/标航智导-PRD.md` (new)
- `docs/logs/document-changelog.md` (appended)

**Reason:**

- User requested a product requirements document that consolidates existing architecture, features, content, and roadmap.
- The new PRD is positioned as an internal development/product counterpart to the existing competition-facing `docs/标航智导.md`.
- It explicitly separates the already-verified deterministic teaching baseline from the still-to-be-implemented Agent platform capabilities (A4–A8, D1–D2), avoiding the common risk of describing planned features as completed.
- Includes reasoning for key design choices (graph-driven architecture, deterministic tool vs. LLM split, scenario overlay model, confirmation gate) and a phased roadmap.

**Verification:**

- `docs/标航智导-PRD.md` created with 12 sections covering product overview, user profiles, core concepts, functional/non-functional requirements, data/content architecture, technical architecture, user journeys, roadmap, risks, and appendix.
- Cross-references to existing docs (`docs/标航智导.md`, implementation plans, content spec) are consistent with current repository contents.
- Current baseline commands and test counts copied from latest known passing state (2026-07-27).

**Remaining verification:**

- PRD should be reviewed by the product/team lead for accuracy of user needs and priority assignments.
- Update PRD after each major milestone (A5/A6/A7 completion) to keep baseline/status statements accurate.

## [2026-07-30 00:30] Rewrite PRD in professional product-manager style

**Changed files:**

- `docs/标航智导-PRD.md` (rewritten)
- `docs/logs/document-changelog.md` (appended)

**Reason:**

- User requested a professional product-management-style PRD with direct content rather than file references.
- Rewrote the document from a development-oriented summary into a full PRD including: document control, market background, user personas, value proposition, product goals and success metrics, user story matrix, detailed functional requirements with acceptance criteria, non-functional requirements, information architecture, user journeys, data model, API requirements, data tracking/analytics, competitive analysis, risk/dependency matrix, and phased go-to-market milestones.
- Removed in-document references to other markdown files; all required content is now self-contained.
- Maintained strict separation between verified baseline and still-to-be-implemented capabilities.

**Verification:**

- `docs/标航智导-PRD.md` rewritten to ~43 KB, 17 sections, with consistent internal cross-references only.
- All functional requirements include priority (P0/P1/P2) and acceptance criteria.
- Data model, API overview, event stream, and tool-call permission table align with existing implementation plans.

**Remaining verification:**

- Success metric target values should be validated against actual pilot data once A8 user trials begin.
- Data tracking event schema should be reviewed against frontend instrumentation capabilities before A7 implementation.

## [2026-08-01 05:55] 按 PRD v3.1 全权重构前后端（蓝图 + 配套文档与配置）

**Changed files:**

- `docs/dev/rewrite-blueprint.md`（新建：全权重构单一事实来源——技术决策、目录布局、DB schema、API/DTO 契约、SSE 事件、工具契约、Agent 编排规则、诊断/掌握度规则、种子数据、前端信息架构、权限矩阵、测试计划、实施波次）
- `.env.example`（重写：匹配新配置项 BHZD_*，保留兼容旧名，中文注释）
- `.gitignore`（新增 `.env.local`、`var/` 忽略项——本地敏感配置与运行时产物不再入库）
- `tests/e2e/smoke.spec.ts`（新建：PRD 主线 e2e 冒烟，替换全部面向旧页面的 6 个旧 spec 与 helpers）
- `tests/e2e/playwright-runtime.ts`（补导出 `request`，供 API 登录注入会话）
- `tests/content/test_teaching_units.py`（单个命名空间契约测试改验数据本体，原校验文档已随重构移除）
- `scripts/integration_smoke.py`（新建：AC1–AC13 端到端验收冒烟脚本，临时库可重复执行）

**Reason:**

- 用户要求以 `docs/标航智导-PRD/`（v3.1 六份子 PRD + v3.0 完整版独有内容）为唯一准绳，不参考旧项目结构与旧页面，完全重构前后端。
- 旧前后端代码全部重写：`server/bhzd_py/`（FastAPI + SQLite，13 路由模块 + Agent 编排 + 15 工具契约 + RAG 全链路 + 确定性诊断 + 图谱/掌握度/教师/系统管理域）；`app/src/`（React 19 + react-router v7，学生/教师/RAG 管理/系统管理四端 27 页）。旧实现移至 `server/_legacy/` 备查，待用户确认后删除。
- v3.0 完整版独有内容已并入实现：14 个埋点事件、SourceLedger 字段级 schema、图谱掌握度配色（绿/橙/红）、欢迎态契约占位文案、"内容安全文本审核"预设路径、演示模式种子。

**Verification:**

- 后端：`python -m pytest server/tests -q` → 172 passed。
- 前端：`cd app && npx vitest run` → 77 passed；`npx tsc --noEmit` 零错误；`npm run build` 通过。
- 数据契约：`python -m pytest tests/content tests/graph -q` → 234 passed。
- 端到端：`python scripts/integration_smoke.py` → 23/23（覆盖 AC1–AC13：目标→计划→确认门→任务、预设建任务、RAG 上传→审核→发布→引用、未审核不可召回、拒答、PRE 路径、企业任务发布、诊断+补强+掌握度、密钥不回显、NF9 校验、诊断原文件不落盘、发布写审计）。
- 浏览器：`cd app && npx playwright test --project=chromium` → 6/6（登录→指挥舱 8 入口、AC1 全链、预设、引用/拒答、图谱、教师工作台；后端 8787 + 前端 4173 真实双端）。

**Remaining verification:**

- 讯飞星辰/星火协议适配器经单测验证签名与载荷，未做真实外部调用（无赛事平台凭据）。
- 演示模式的完整比赛演示主线（PRD-05 §9）需人工按脚本过一遍验收。
- `server/_legacy/` 旧代码目录待用户确认后物理删除；`var/bhzd.sqlite.pre-rewrite.bak` 为重构前空库备份，可自行清理。

## [2026-08-01 13:23] 学习/个人中心域增强（A2：入学测评闭环 + 收藏 + CSRF 稳定化 + 诊断缓存 DB 化 + 批量归档 + 掌握度趋势）

**Changed files:**

- `server/bhzd_py/migrations/008_learning_social.sql`（新建：`favorites` 表、`diagnostic_cache` 表、`user_sessions`/`admin_sessions` 增 `csrf_token` 可空列；ALTER ADD COLUMN 对存量库平滑）
- `server/bhzd_py/seed/assessment.py`（新建：8 道中文入学测评题，cap_id 全部为图谱真实 CAP 节点，含下发脱敏/确定性评分/图谱校验）
- `server/bhzd_py/routers/profile.py`（新增 `GET/POST /api/onboarding/assessment`、`POST /api/onboarding/skip`、`GET/POST/DELETE /api/profile/favorites[/{id}]`、`GET /api/profile/mastery/trend`；`GET /api/profile` 收藏桩替换为真实数据）
- `server/bhzd_py/routers/auth.py`（登录把原始 CSRF 令牌落会话行；`GET /api/auth/session` 不再轮换，legacy 会话首次读取时补发升级）
- `server/bhzd_py/deps.py`（`CurrentUser` 增 `csrf_token_raw`；`csrf_protect` 优先比对原始令牌，NULL 回退旧哈希列保持向后兼容）
- `server/bhzd_py/routers/diagnostics.py`（报告缓存由进程内 dict 改为 `diagnostic_cache` 表，30 分钟过期语义不变、读取惰性删除；`get_cached_report(token)` 签名不变，上传原文件仍不落盘）
- `server/bhzd_py/routers/tasks.py`（新增 `POST /api/tasks/batch` 批量归档，逐条部分成功回报）
- `server/tests/test_learning_enhancements.py`（新建 12 测试）、`server/tests/test_auth.py`（轮换期断言更新为稳定令牌契约 + legacy 升级路径，13 测试）、`server/tests/test_migrations.py`（清单含 007/008/009，新增 csrf_token 列断言）

**Reason:**

- PRD v3.0 §11.1 首次使用流程缺"入学测评→初始能力地图"闭环；PRD-01 §9 收藏资料原为 P1 桩；`GET /api/auth/session` 每次轮换 CSRF 导致多标签页互顶；诊断报告进程内缓存多实例/重启即失效；PRD-01 §6.1 批量操作缺实现；成长趋势图缺时间序列端点。

**Verification:**

- `python -m pytest server/tests -q` → 188 passed（原 174 全绿 + 新增 14）。
- 迁移在含 001-007 数据的库上顺序应用 008/009 无冲突；`test_rerun_is_idempotent` 验证执行器重跑零副作用。
- 测评 mastery 落库核对：8 行 source='assessment'、答对 0.4/答错 0.1、clamp[0,1]；下发题目不含 answer_index。
- 诊断缓存：上传后 `diagnostic_cache` 有行、过期 410 中文提示 + 惰性删除、他人 token 403。

**Remaining verification:**

- 前端 onboarding/收藏/批量归档界面尚未接入（本批仅后端契约；前端属其它任务书范围）。
- 批量操作目前仅实现 archive；PRD-01 §6.1 的"标记"动作待后续批次。

## [2026-08-01 18:30] PRD 全量补齐：增强包（后端三包 + 前端三包 + 验证扩展）

**Changed files:**

- 后端增强（代码，经蓝图既定归属实施）：migrations 007_recall_logs/008_learning_social/009_notifications；`rag/`（provider 嵌入经 run_coro_sync 真实接入、重排接入、表格策略、CSV/XLSX 解析、批量操作、召回记录、评测历史端点）；`routers/profile.py`（入学测评、收藏、掌握度趋势、诊断分享开关 PATCH /api/profile）；`routers/notifications.py`（站内通知）；`routers/teacher.py`（发布/改期通知、诊断授权查看、AI 任务卡生成、逐学生学情明细）；`alerts.py`（PRD-06 §13.2 五项告警评估）+ `GET /api/admin/alerts`；诊断缓存 DB 化；CSRF 令牌稳定化（不再每次轮换）
- 前端增强（代码）：`pages/student/OnboardingPage.tsx`（三步向导+测评门禁）、StudentLayout 通知铃铛、TasksPage 批量归档、ProfilePage 收藏/授权开关/掌握度趋势、RagQaPage 引用收藏；`pages/teacher/`（AI 生成任务卡回填、已发布任务改期、学情逐学生明细、班级诊断授权查看）；`pages/rag/`（资料批量操作、召回记录、评测历史 API 化、CSV/XLSX 上传）；`pages/admin/SecurityPage.tsx`（系统告警卡）
- `scripts/load_test.py`（新建：NF9/NF10/NF11/NF14 压测）、`scripts/demo_walkthrough.py`（新建：AC14 演示主线彩排）、`scripts/integration_smoke.py`（扩展新特性链路至 38 项）
- `tests/e2e/enhancements.spec.ts`（新建：入学测评/通知/RAG 治理/批量归档 4 条浏览器链路）
- `.env.example`（追加 BHZD_LOGIN_RATE_LIMIT_PER_MINUTE 说明）
- 邮件韧性改造：`routers/auth.py` SMTP 故障不再 500（三态投递：smtp/outbox/failed，失败写 outbox 存档 + mail_delivered=false，不泄露令牌）；`security.py` 登录限流阈值支持环境变量覆盖（默认 5 不变）

**Reason:**

- 用户要求"全量完成"上一轮差距清单：入学测评、批量操作、收藏、召回记录、教师 Agent 生成、学情明细、通知与诊断授权、告警、表格策略、CSV/XLSX、provider 嵌入真实接入、CSRF 稳定化、诊断缓存 DB 化，以及性能压测、e2e 扩展、AC14 彩排。PRD 自划 P2（OCR/音视频/网页抓取/多校区/Docker）按 PRD 不做。
- e2e 联调暴露的两个真实缺陷已修：SMTP 配置但不可达导致注册 500（改韧性降级）；e2e 高频登录触发 NF5 限流（阈值环境变量化，测试环境放宽）。

**Verification:**

- `python -m pytest server/tests -q` → 228 passed（含新增 54 项增强测试）。
- `cd app && npx vitest run` → 100 passed；`npm run build` 通过；tsc 零错误。
- `python -m pytest tests/content tests/graph -q` → 234 passed。
- `python scripts/integration_smoke.py` → 38/38（AC1-AC13 + 测评/收藏/通知/批量/AI 生成/授权/召回记录/CSV/评测历史/告警）。
- `python scripts/load_test.py` → 全部达标：NF9 p95≤0.057s（阈 3s）、NF10 p95 0.29s（阈 2s）、NF11 p95 0.12s（阈 1s）、NF14 12/12 并发会话零异常。
- `python scripts/demo_walkthrough.py` → AC14 演示主线 9/9 步通过。
- `cd app && npx playwright test --project=msedge` → 10/10（smoke 6 + enhancements 4）。

**Remaining verification:**

- provider 嵌入/重排的真实外部调用仍依赖用户在系统管理端配置有效供应商后回归；讯飞协议同理。
- NF10 在接入真实 LLM 后取决于供应商延迟，压测数字为离线模板合成口径。

## [2026-08-01 20:55] Agent 指挥舱布局优化：方案对比稿 + 方案 A（三栏精修）实施

**Changed files:**

- `docs/dev/cockpit-layout-options.html`（新建：A 三栏精修 / B 沉浸单栏+抽屉 / C 指挥台双栏 三版高保真对比稿，经用户评审选定 A）
- `app/src/pages/student/cockpit/cockpit.css`（网格 200/自适应/250、对话区 920px 居中、对话流整页滚动、折叠竖条与折叠按钮样式、确认门脉冲圆点、响应式适配）
- `app/src/pages/student/CockpitPage.tsx`（折叠状态 localStorage 持久化、确认门出现自动展开右栏）
- `app/src/pages/student/cockpit/LeftRail.tsx`、`RightRail.tsx`（可折叠：48px 竖条 + 展开按钮；右栏竖条带确认门提醒圆点）

**Reason:**

- 用户要求优化指挥舱排版布局并先要对比方案选择；原三栏（250/290）挤压对话区、对话流内嵌滚动条、确认门不够抢眼。方案 A 为用户在 A/B/C 对比稿中的选定项：保留 PRD-01 §3.2 三栏骨架、改动最小、回归风险最低。

**Verification:**

- `cd app && npx tsc --noEmit` 零错误；`npx vitest run` 100/100（含 cockpit 16 例全过）。
- 真实浏览器（Edge + 双端）截图验证三态：欢迎态（左右栏收窄、对话区居中）、左栏折叠态（48px 竖条、对话区变宽）、运行态+确认门（右栏置顶确认卡、执行轨迹、整页滚动）。

**Remaining verification:**

- 窄屏（<900px）实机手感建议演示前过一遍；方案 B/C 的对比稿保留在案，后续若改方向可直接复用。

## [2026-08-01 21:10] 指挥舱左右栏重组（用户指定）

**Changed files:**

- `app/src/pages/student/cockpit/LeftRail.tsx`（移除「正在学习/教师发布任务」区块与相关 props；「最近会话」列表迁入 rail-scroll-box 盒内滚动；顶部注释同步）
- `app/src/pages/student/cockpit/RightRail.tsx`（承接「正在学习/教师发布任务」两区块，位于引用来源之后、当前能力定位之前；新增 learning/teacherTasks props）
- `app/src/pages/student/CockpitPage.tsx`（learning/teacherTasks 数据传递由 LeftRail 改接 RightRail）
- `app/src/pages/student/cockpit/cockpit.css`（新增 .rail-scroll-box：限高 260px + 盒内滚动 + 边框）

**Reason:**

- 用户指定：左栏聚焦"今日推荐 + 最近会话"，任务类信息并入右栏状态区；会话列表限高盒内滚动，避免把左栏顶长。

**Verification:**

- `npx tsc --noEmit` 零错误；`npx vitest run` 100/100。
- 真实浏览器截图核对：左栏今日推荐+会话滚动盒，右栏正在学习（进行中徽标）/教师发布任务/能力定位，均正确渲染。

**Remaining verification:** 无。

## [2026-08-01 21:25] 指挥舱固定为视口高度

**Changed files:**

- `app/src/pages/student/cockpit/cockpit.css`（.cockpit 高度 = 100vh − 顶栏 − 主区留白、overflow hidden；左右栏栏内滚动；中栏栏内滚动；.composer margin-top:auto 短内容时顶到栏底、长内容时 sticky 吸附；≤1200px 回落自然流；文件头注释同步）

**Reason:**

- 用户指定：固定 Agent 指挥舱高度为视口高度（应用式满屏框架，页面本身不滚动）。

**Verification:**

- `npx tsc --noEmit` 零错误；`npx vitest run` 100/100。
- 真实浏览器断言：documentElement 无页面级滚动（page-scrollable=false）、中栏内部滚动（center-scrollable=true）；截图核对欢迎态/运行态：框架恰好满屏、输入区钉在栏底、确认门右栏置顶。

**Remaining verification:** ≤1200px/≤900px 回落自然流的实机表现建议演示前过一遍。

## [2026-08-01 21:40] 指挥舱整体背景卡片

**Changed files:**

- `app/src/pages/student/cockpit/cockpit.css`（.cockpit 增加浅灰面板背景 + 边框 + 圆角 + 内边距：三栏统一收纳进一张背景卡片，内部白色卡片仍保持对比）

**Reason:**

- 用户指定：给指挥舱中间整个区域加背景卡片，提升整体感与层次。

**Verification:**

- 真实浏览器截图核对：整舱收纳于一张圆角面板内，左右栏与中部层次清晰，视口固定高度与钉底输入区不受影响。

**Remaining verification:** 无。

## [2026-08-01 21:48] 撤销指挥舱整体背景卡片

**Changed files:**

- `app/src/pages/student/cockpit/cockpit.css`（回退上一条背景卡片改动：.cockpit 恢复透明底，无面板边框/内边距）

**Reason:**

- 用户要求取消刚加的整体背景卡片，恢复无背景面板的三栏布局。

**Verification:**

- CSS 回退至上一条之前的状态，视口固定高度/栏内滚动/钉底输入区保持。

**Remaining verification:** 无。

## [2026-08-02 14:12] 同步重构蓝图的 P0 安全与状态契约

**Changed files:**

- `docs/dev/rewrite-blueprint.md`（认证 DTO、密码信封协议、确认过期语义、Provider 角色化最小测试与生产配置约束）
- `docs/logs/document-changelog.md`（本次记录）

**Reason:**

- 旧蓝图仍以明文 `password` 描述注册、登录和重置密码，且未覆盖密码公钥、确认倒计时收敛与角色化 Provider 测试的已实现契约。
- 补充生产 fail-closed 配置边界，避免将仅限开发环境的临时密钥、邮件 outbox 和 token 回显误读为生产行为。

**Verification:**

- 对照 `server/bhzd_py/routers/auth.py`、`security.py`、`config.py`、`routers/confirmations.py`、`agent/confirmation_state.py`、`routers/admin.py` 与 `agent/providers.py` 核对端点、DTO 字段、状态码、事务终态、角色映射和安全结果字段。
- 复核 `docs/dev/rewrite-blueprint.md`，确认不再出现认证请求的明文 `{email,password}` 或 `{token,password}` DTO 描述。

**Remaining verification:**

- 最终集成测试应复核文档中的端点响应与当前实现一致；真实 Provider smoke 仍须在已启用且已分配角色的有效配置上执行，且只保留脱敏结果。

## [2026-08-02 14:37] 完成 P0 文档验证闭环

**Changed files:**

- `docs/logs/document-changelog.md`（补记上一条 P0 契约同步的最终验证结果）

**Reason:**

- 将已完成的集成、浏览器和 Provider 验证固化为可审计证据，避免上一条记录继续显示为待验证。

**Verification:**

- 隔离后端回归 `258 passed`；内容与图谱测试分别 `8 passed`、`37 passed`；集成冒烟 `39/39`。
- `pnpm --dir app install --frozen-lockfile`、前端测试 `104 passed`、生产构建及隔离 Chromium E2E `10 passed` 均通过。
- 已启用的 `primary` Provider 角色化最小冒烟成功；结果只保留角色、模型、耗时与成功状态，未记录敏感配置或响应内容。

**Remaining verification:** 无。

## [2026-08-02 20:45] 新增项目优化审计报告

**Changed files:**

- `docs/dev/optimization-audit.md`（新建）
- `docs/logs/document-changelog.md`（本次记录）

**Reason:**

- 应用户请求，将当日只读审计结论整理为工程文档，供后续执行参考。
- 审计覆盖：数据库索引、端点安全、RAG 管线、前端 bundle、CI/测试基础设施，共五大维度，分 P0/P1/P2 三级。

**Verification:**

- 报告中每条结论均有对应取证方式（`EXPLAIN QUERY PLAN`、AST 扫描、`TestClient` 端点探测、`pytest`/`vitest` 基线）。
- 已验证无问题的安全项单独列出，防止后续误改。
- `tsc --noEmit` exit 0 · `pytest` 258 passed · `vitest run` 104 passed（基线未变化）。

**Remaining verification:** 无。

## [2026-08-05 23:44] 展示 Agent 安全工作步骤

**Changed files:**

- `app/src/pages/student/CockpitPage.tsx`
- `app/src/pages/student/cockpit/ActivityTimeline.tsx`
- `app/src/pages/student/cockpit/ChatStream.tsx`
- `app/src/pages/student/cockpit/Composer.tsx`
- `app/src/pages/student/cockpit/PlanCard.tsx`
- `app/src/pages/student/cockpit/useCockpitRun.ts`
- `app/src/pages/student/cockpit/types.ts`
- `app/src/api/types.ts`
- `app/src/pages/student/cockpit/cockpit.css`
- `app/tests/cockpit.test.tsx`
- `app/tests/cockpit-flow.test.tsx`
- `server/bhzd_py/agent/events.py`
- `server/bhzd_py/agent/orchestrator.py`
- `server/bhzd_py/routers/runs.py`
- `server/tests/test_agent_direct_chat.py`
- `server/tests/test_agent_orchestrator.py`
- `server/tests/test_agent_progress.py`

**Reason:**

- 将理解、计划、工具执行、确认和回答生成以紧凑的安全工作步骤展示，替代发送按钮的加载动画反馈。
- 只展示有界的用户可读摘要和稳定活动生命周期，继续隐藏原始思维链、RAG 内部过程、工具参数、结果体和凭据。

**Verification:**

- 后端全量 `308 passed`；前端全量 `137 passed`；`pnpm typecheck` 与 `pnpm build` 通过。
- Python `compileall`、`git diff --check` 和本次涉及前端文件的 Prettier 定向检查通过。
- 真实本地页面已验证路由和登录门禁；未猜测或输入凭据，未停止或重启现有 `5173/8787` 服务。

**Remaining verification:**

- 已登录浏览器会话下的真实运行态截图仍需在具备有效测试账号后补做；整仓 Prettier 检查仍受既有无关文件格式差异影响。

## [2026-08-06 00:51] 完善 Agent 实时执行轨迹与安全事件投影

**Changed files:**

- `server/bhzd_py/agent/events.py`
- `server/bhzd_py/agent/orchestrator.py`
- `server/bhzd_py/agent/confirmation_state.py`
- `server/bhzd_py/routers/confirmations.py`
- `server/bhzd_py/routers/runs.py`
- `app/src/api/types.ts`
- `app/src/pages/student/cockpit/types.ts`
- `app/src/pages/student/cockpit/runStream.ts`
- `app/src/pages/student/cockpit/useCockpitRun.ts`
- `app/src/pages/student/cockpit/ActivityTimeline.tsx`
- `app/src/pages/student/cockpit/ChatStream.tsx`
- `app/src/pages/student/cockpit/ExecutionTrace.tsx`
- `app/src/pages/student/cockpit/cockpit.css`
- `server/tests/test_agent_orchestrator.py`
- `server/tests/test_runs_api.py`
- `app/tests/cockpit.test.tsx`

**Reason:**

- 用户确认需要在 Agent 执行期间看到真实工具生命周期、输入/输出安全摘要和确认状态，完成回答后自动折叠工作步骤，而不是只在发送按钮上显示加载动画。
- 防止 SSE、运行恢复接口和确认路径把原始参数、结果、计划内部参数或敏感凭据泄露到浏览器。

**Verification:**

- 后端全量 `543 passed`；前端全量 `137 passed`（16 个测试文件）。
- `pnpm typecheck`、`pnpm build`、Python `compileall`、`git diff --check` 和涉及文件的 Prettier 检查通过。
- 新增测试覆盖工具/命令/文件分类、摘要计数、敏感字段脱敏、实时生命周期更新、终态自动折叠和手动展开。

**Remaining verification:**

- 当前注册表没有真实 shell/terminal/通用文件工具，因此没有伪造命令执行记录；真实登录浏览器会话已验证工作步骤时间线、工具生命周期和终态折叠。

## [2026-08-06 00:57] 校正 Agent 实时轨迹验证记录

**Changed files:**

- `docs/logs/document-changelog.md`

**Reason:**

- 校正上一条记录中的前端测试数量，并同步已完成的真实登录浏览器运行态验证，避免文档继续保留过时的待验证描述。

**Verification:**

- 后端全量 `543 passed`；前端全量 `137 passed`（16 个测试文件）。
- `pnpm typecheck`、`pnpm build`、Python `compileall` 与 `git diff --check` 均通过。
- 已验证工作步骤时间线会在用户消息后展示，工具生命周期原地更新，运行完成后自动折叠且可手动展开。

**Remaining verification:**

- 当前注册表没有真实 shell/terminal/通用文件工具，因此不会伪造命令执行记录；后续接入此类工具后再展示对应的真实命令/文件事件。

## [2026-08-06 11:47] 将 Agent 回复渲染为安全 Markdown 预览

**Changed files:**

- `app/package.json`
- `app/pnpm-lock.yaml`
- `app/src/pages/student/cockpit/MessageBubble.tsx`
- `app/src/pages/student/cockpit/cockpit.css`
- `app/tests/message-bubble.test.tsx`
- `docs/logs/document-changelog.md`

**Reason:**

- 修复 Agent 回复把 Markdown 源码作为纯文本显示的问题，使流式、历史与恢复回答共用的消息气泡能预览标题、列表、代码块和 GFM 表格。
- 保持原始 HTML、远程图片和非安全链接不进入学生端渲染面，避免模型输出造成脚本执行、远程跟踪或版面风险。

**Verification:**

- 新增 Markdown 气泡测试 `3 passed`；既有指挥舱流式/历史/恢复测试 `42 passed`；前端全量 `17 files / 141 passed`。
- `pnpm typecheck`、`pnpm build`、定向 ESLint、定向 Prettier 与 `git diff --check` 均通过。
- 已核对现有 `5173` 前端和 `8787` 后端服务归属；浏览器会话未登录，未输入或猜测任何凭据。

**Remaining verification:**

- 真实登录会话下的人工视觉验收未执行；代码路径由同一 `MessageBubble` 覆盖实时、历史和恢复回答，且已由上述测试验证。

## [2026-08-06 16:43] 重构学生端 Agent 执行记录

**Changed files:**

- `app/src/pages/student/cockpit/ActivityTimeline.tsx`
- `app/src/pages/student/cockpit/PlanCard.tsx`
- `app/src/pages/student/cockpit/ChatStream.tsx`
- `app/src/pages/student/cockpit/RightRail.tsx`
- `app/src/pages/student/cockpit/useCockpitRun.ts`
- `app/src/pages/student/cockpit/cockpit.css`
- `server/bhzd_py/agent/orchestrator.py`
- `server/bhzd_py/routers/runs.py`
- `app/tests/cockpit.test.tsx`
- `app/tests/cockpit-flow.test.tsx`
- `docs/logs/document-changelog.md`

**Reason:**

- 移除学生端的模型思考摘要，将真实的执行清单、工具／命令／文件调用、确认状态和回答生成统一为一条中央执行记录；运行时展开，终态自动折叠并允许再次查看。
- 继续屏蔽原始思维链、检索细节、RAG 内部事件、工具原始参数与结果，避免将不可核验或敏感内容投射到界面。

**Verification:**

- 后端定向验证 `59 passed`，Ruff、`compileall` 和差异空白检查通过。
- 前端 `pnpm typecheck`、`pnpm build`、全量 `17 files / 141 passed`、定向 cockpit `42 passed`、定向 Prettier、ESLint 与差异空白检查通过。
- 未重启服务地确认 `5173` 属于当前 BHZD Vite、`8787` 健康检查返回 HTTP 200；未输入或猜测登录凭据。

**Remaining verification:**

- 需要在已有学生登录会话下，以包含计划、真实工具调用（或确认）和 Markdown 回答的一次任务做人工视觉验收；当前无可复用登录态，未越权尝试登录。

## [2026-08-06 23:05] 收紧教师、学生端与 RAG 管理权限

**Changed files:**

- `docs/dev/rewrite-blueprint.md`
- `docs/标航智导-PRD/标航智导-PRD-00总览.md`
- `docs/标航智导-PRD/标航智导-PRD-01学生端页面.md`
- `docs/标航智导-PRD/标航智导-PRD-02教师端页面.md`
- `docs/标航智导-PRD/标航智导-PRD-03RAG知识库管理.md`
- `docs/标航智导-PRD/标航智导-PRD-04系统管理.md`
- `docs/标航智导-PRD/标航智导-PRD-05技术与研发拆解.md`
- `docs/标航智导-PRD/标航智导-PRD-06研发可落地补充与边界条件.md`
- `docs/标航智导-PRD/标航智导-完整PRD-RAG与页面交互版.md`

**Reason:**

- 同步实施后的权限边界：教师只能使用教师端，不能访问学生端或 RAG 管理；RAG 管理门户、HTTP API 和 Agent 资料管理工具仅允许 `system_admin`。
- 保留 `content_admin` 与 `system_admin` 的学生端访问，并将教师资料选择收敛为已发布、学生可见、授权有效且未过期的只读目录；教师资源审核入口已移除。

**Verification:**

- 后端完整测试 `351 passed`，权限定向测试 `75 passed`；新增测试覆盖教师直调学生端 API、RAG HTTP/Agent 管理能力均返回 403，以及管理员保留学生端。
- 前端类型检查、完整 `142` 项测试和生产构建通过；`ruff`、`compileall` 与 `git diff --check` 通过。

**Remaining verification:**

- 当前 `5173` 前端与 `8787` 后端均健康，但未停止或重启现有后端进程；非自动重载的后端需要在正常重启后才会加载本次权限代码。

## [2026-08-07 10:18] 新增 GSAP 动效预览演示

**Changed files:**

- `docs/dev/gsap-motion-preview.html`
- `docs/logs/document-changelog.md`

**Reason:**

- 提供独立、可直接在浏览器打开的动效预览，先验证“安静的操作型动效”在路由内容、弹窗、抽屉、Toast 和执行活动中的节奏，再决定是否接入生产前端。
- 演示仅使用静态学习工作台数据，不接入业务 API、SSE 或真实会话内容。

**Verification:**

- `pnpm --dir app exec prettier --check ../docs/dev/gsap-motion-preview.html` 通过，`git diff --check` 未发现已跟踪差异中的空白问题。
- JSDOM 使用 GSAP 兼容测试桩执行初始渲染、路由、Modal、Drawer、Toast、活动新增和减少动态效果，共 10 项断言通过。
- 官方 npm GSAP CDN `https://cdn.jsdelivr.net/npm/gsap@3.12.7/dist/gsap.min.js` HEAD 请求返回 HTTP 200。

**Remaining verification:**

- Codex 内置浏览器的 URL 安全策略阻止 `file://` 加载，未绕过该限制；仍需在本机浏览器直接打开演示文件进行最终人工视觉验收。

## [2026-08-07 11:02] 落地全局交互动效并移除预览草案

**Changed files:**

- `docs/dev/gsap-motion-preview.html` (deleted)
- `app/src/index.css`
- `app/src/components/usePresence.ts`
- `app/src/components/Modal.tsx`
- `app/src/components/Drawer.tsx`
- `app/src/components/Toast.tsx`
- `app/src/layouts/ShellLayout.tsx`
- `app/src/layouts/StudentLayout.tsx`
- `app/src/pages/student/cockpit/ActivityTimeline.tsx`
- `app/src/pages/student/cockpit/cockpit.css`
- `app/tests/interaction-presence.test.tsx`
- `docs/logs/document-changelog.md`

**Reason:**

- 以现有 React 与 CSS 体系实现短时、功能导向的页面进入、按钮反馈、弹层、抽屉、下拉、Toast、侧栏、Tabs、进度条和实时活动入场反馈；不新增动效库，也不采用已删除预览稿的实现。
- 对系统“减少动态效果”偏好即时降级，退出期保留视觉内容与焦点回归，避免直接卸载造成突兀闪断或焦点丢失。

**Verification:**

- 前端全量 `pnpm test:run` 通过：`18 files / 148 tests`；新增 presence 用例覆盖 Modal、Drawer、Toast、减少动态和 Tabs。
- `pnpm build`、`pnpm lint`（0 errors，42 项既有 warning）和业务源文件的定向 Prettier 检查通过；变更日志全文件的 Prettier 基线存在既有格式差异，未重排该历史文档。
- 本地 `127.0.0.1:5173/login` 在 `390x844` 视口下无横向溢出，认证卡可见且计算样式为 `motion-surface-enter`、`200ms`；未使用登录凭据。

**Remaining verification:**

- 未在真实登录会话中人工触发 Cockpit 的实时活动、确认弹层及各类菜单，因此该部分仅由组件/流程测试和静态样式覆盖；未尝试读取、猜测或使用任何浏览器凭据。

## [2026-08-07 16:57] 全局自定义组合框与交互收尾

**Changed files:**

- `app/src/components/Select.tsx`
- `app/src/components/Field.tsx`
- `app/src/components/useFocusTrap.ts`
- `app/src/components/Modal.tsx`
- `app/src/components/Drawer.tsx`
- `app/src/index.css`
- `app/src/pages/admin/ProvidersPage.tsx`
- `app/src/pages/teacher/TaskPublishPage.tsx`
- `app/tests/select.test.tsx`
- `app/tests/interaction-presence.test.tsx`
- `app/tests/admin-pages.test.tsx`
- `app/tests/rag-admin-pages.test.tsx`
- `app/tests/student-enhancements.test.tsx`
- `app/tests/student-pages.test.tsx`
- `app/tests/teacher-enhancements.test.tsx`
- `tests/e2e/enhancements.spec.ts`
- `docs/logs/document-changelog.md`

**Reason:**

- 将全局单选控件替换为按钮触发、Portal `listbox` 呈现的自定义组合框，避免浏览器原生选项列表样式；保留隐藏原生 `select` 作为现有表单值和 `onChange` 事件桥接。
- 统一选项的高亮、选中标记、键盘导航、外部点击关闭、向上/向下定位和短时进退场，并补齐 Field 标签关联、嵌套弹层焦点约束和关闭遮罩交互保护。
- 不引入或引用 GSAP；此前预览草案继续保持删除状态。

**Verification:**

- 前端完整 `pnpm --dir app test:run` 通过：`19 files / 158 tests`；组合框定向用例覆盖 Portal、表单桥接、Field 关联、键盘、外部关闭、定位及禁用状态。
- `pnpm --dir app typecheck`、`pnpm --dir app build` 通过；`pnpm --dir app lint` 为 `0 errors / 42 warnings`，均为现有 Fast Refresh、未使用变量和空白字符警告。
- 本次相关源文件与测试的 Prettier 定向检查通过。浏览器在 `390x844` 下验证注册页组合框为 `body` Portal、`position: fixed`、`z-index: 75`，选项列表完全位于视口内，选中后正确关闭并更新显示。

**Remaining verification:**

- Provider 管理抽屉中的真实登录会话人工验收未执行，因当前浏览器没有可授权复用的登录状态；未输入、读取或猜测任何凭据。

## [2026-08-07 17:53] 供应商模型发现与抽屉角色配置

**Changed files:**

- `app/src/api/types.ts`
- `app/src/index.css`
- `app/src/pages/admin/ProvidersPage.tsx`
- `app/tests/admin-pages.test.tsx`
- `server/bhzd_py/agent/providers.py`
- `server/bhzd_py/routers/admin.py`
- `server/tests/test_admin.py`
- `server/tests/test_providers.py`
- `docs/logs/document-changelog.md`

**Reason:**

- 新建供应商时，管理员填写协议、Base URL 与 API Key 后可安全获取模型目录，并以全局自定义组合框选择模型；不支持目录的协议与失败情况保留手工模型名输入。
- 编辑已保存的供应商时，模型发现只使用数据库中的协议、地址和加密密钥，浏览器不需要重新填写 API Key；连接字段变更后必须先保存，避免将存储密钥发送到未保存地址。
- 移除表格操作列中的角色设置，将角色调整收敛到编辑抽屉，并在替换同角色已有供应商前确认后走正常保存事务。

**Verification:**

- 后端定向 `pytest tests/test_admin.py tests/test_providers.py -q`：`50 passed`；完整后端套件：`365 passed`。`ruff check` 通过。
- 前端完整 `pnpm --dir app test:run`：`19 files / 161 tests` 通过；`typecheck`、生产构建、相关 Prettier 检查和 ESLint（`0 errors / 42` 条既有 warning）通过。
- 覆盖临时与已保存发现路径、HTTPS/userinfo/内网限制、CSRF、请求体覆盖拒绝、密钥与日志脱敏、目录限制、讯飞手工输入态、角色替换确认与连接字段失效。

**Remaining verification:**

- 当前 `8787` 后端进程未启用自动重载，按用户约束未停止或重启；需在正常发布重启后才会载入新接口。浏览器没有可复用的管理员会话，因此未进行真实凭据的人工发现请求。

---

## [2026-08-08 23:22] 新增侧栏标题避让三版 Companion 演示

**Changed files:**

- `docs/dev/companion-sidebar-title-options.html`
- `docs/logs/document-changelog.md`

**Reason:**

- 按用户确认，制作三版桌面侧栏收起后页面标题避让方案，供 Companion 面板交互评估；会话界面作为现有例外保留。

**Verification:**

- 静态演示服务器返回 `200 text/html`。
- `git diff --check` 通过；演示页支持页面语境切换、侧栏展开/收起和候选方案标记。
- 已将 `http://127.0.0.1:5190/companion-sidebar-title-options.html` 推送到当前 Codex Companion 面板。

**Remaining verification:**

- 浏览器截图运行组件缺少 `browser-client.mjs`，尚未完成自动截图级视觉回归；需在 Companion 面板中人工比较三版。

---

## [2026-08-07 18:34] 精简模型供应商编辑抽屉说明

**Changed files:**

- `app/src/pages/admin/ProvidersPage.tsx`
- `app/tests/admin-pages.test.tsx`
- `docs/logs/document-changelog.md`

**Reason:**

- 删除编辑抽屉中 base_url、API Key、超时、角色和常规模型获取的固定说明，降低表单噪音；保留连接字段变更、模型发现失败和表单校验等可操作反馈。

**Verification:**

- `pnpm --dir app test:run -- admin-pages.test.tsx` 通过（2 files / 36 tests）。
- `pnpm --dir app typecheck`、`pnpm --dir app build`、定向 ESLint、定向 Prettier 与 `git diff --check` 通过。

**Remaining verification:**

- 未在真实管理员会话中人工验收抽屉，未读取、输入或使用任何凭据；本次 DOM 测试覆盖固定说明隐藏及连接字段变更后的动态提示。

---

## [2026-08-07 18:56] 收紧模型获取控件与密钥状态

**Changed files:**

- `app/src/pages/admin/ProvidersPage.tsx`
- `app/src/index.css`
- `app/tests/admin-pages.test.tsx`
- `docs/logs/document-changelog.md`

**Reason:**

- 将模型发现动作收敛为模型控件右侧的无文字导入图标按钮，减少抽屉中的独立操作行；编辑态以“已保存”状态替代旧密钥回显，继续保持密钥只在服务端保存。

**Verification:**

- `pnpm --dir app test:run -- admin-pages.test.tsx` 通过（2 files / 36 tests）。
- `pnpm --dir app typecheck`、`pnpm --dir app build`、定向 ESLint、定向 Prettier 与 `git diff --check` 通过。
- 未在浏览器中提交或使用任何凭据；真实管理员会话人工验收未执行。

**Remaining verification:**

- 待真实管理员会话中确认导入按钮的最终视觉效果；功能、可访问名称、禁用态、加载态与发现请求已由前端测试覆盖。

---

## [2026-08-07 19:08] 对齐模型导入图标按钮尺寸

**Changed files:**

- `app/src/index.css`
- `app/src/pages/admin/ProvidersPage.tsx`
- `app/tests/admin-pages.test.tsx`
- `docs/logs/document-changelog.md`

**Reason:**

- 将模型发现的导入图标改为模型控件右侧专用的圆角正方形按钮，并让手工模型输入、自定义组合框触发器和按钮统一为 `40px` 高，避免沿用全局 `32px` 表格图标尺寸。
- 专用样式包含边框、悬停和键盘聚焦态，不影响其他页面的全局 `.icon-btn`。

**Verification:**

- `pnpm --dir app test:run -- admin-pages.test.tsx` 通过（2 files / 36 tests）。
- `pnpm --dir app typecheck`、`pnpm --dir app build`、定向 ESLint、定向 Prettier 与 `git diff --check` 通过。
- 生产构建产物包含专用类及 `40px` 尺寸规则。

**Remaining verification:**

- 未在真实管理员会话中人工验收抽屉视觉效果；未读取、输入或使用任何凭据。

---

## [2026-08-07 19:32] 增加安全的 API Key 输入可见性切换

**Changed files:**

- `app/src/pages/admin/ProvidersPage.tsx`
- `app/src/index.css`
- `app/tests/admin-pages.test.tsx`
- `docs/logs/document-changelog.md`

**Reason:**

- 为新建和替换 API Key 输入增加显示/隐藏图标，只作用于管理员当前输入的临时值。
- 编辑已有供应商仍不请求、不解密、不回传已保存密钥；关闭抽屉时清理临时输入和可见状态。

**Verification:**

- `pnpm --dir app test:run -- admin-pages.test.tsx` 通过（2 files / 38 tests）。
- `pnpm --dir app typecheck`、`pnpm --dir app build`、定向 ESLint、定向 Prettier 与 `git diff --check` 通过。
- 回归覆盖空替换值不携带 `api_key`、显示/隐藏切换及已保存密钥不渲染。

**Remaining verification:**

- 未在真实管理员会话中人工验收；未读取、输入或使用任何真实 API Key。

---

## [2026-08-07 19:54] 缩短供应商连接测试预算

**Changed files:**

- `app/src/pages/admin/ProvidersPage.tsx`
- `app/tests/admin-pages.test.tsx`
- `server/bhzd_py/agent/providers.py`
- `server/tests/test_providers.py`
- `docs/logs/document-changelog.md`

**Reason:**

- 连接测试此前会复用供应商最多 `300` 秒的运行时超时，聊天与讯飞探测也可能按较大的输出预算等待，导致管理员操作长时间无响应。
- 为测试路径单独设置 `8` 秒总预算与 `16` tokens 输出上限；前端使用 `9` 秒请求保护，正常 Agent 调用仍保留供应商配置的超时和输出参数。

**Verification:**

- `uv run pytest server/tests/test_providers.py server/tests/test_admin.py -q` 通过（`54 passed`）。
- `uv run python -m compileall -q server/bhzd_py`、`pnpm --dir app build`、定向 ESLint、定向 Prettier 与 `git diff --check` 通过。
- `pnpm --dir app test:run -- admin-pages.test.tsx` 通过（`2 files / 38 tests`）；覆盖 HTTP、Anthropic、Embedding、讯飞和总墙钟超时边界。

**Remaining verification:**

- 未使用真实供应商凭据或发起真实网络测试；当前后端进程未按本任务重启，需在下一次受控发布/重启后加载此后端变更。
- 当前 Python 环境未提供 Ruff 可执行文件，因此未执行 Ruff；已由编译检查和定向测试覆盖本次 Python 改动。

---

## [2026-08-07 20:19] 稳定供应商连接测试加载按钮布局

**Changed files:**

- `app/src/pages/admin/ProvidersPage.tsx`
- `app/src/index.css`
- `app/tests/admin-pages.test.tsx`
- `docs/logs/document-changelog.md`

**Reason:**

- 连接测试进入加载态时，通用按钮会将 Spinner 作为额外 Flex 子项插入，导致按钮变宽并挤动操作列中的相邻按钮。
- 为该局部按钮保留原有文字宽度，并将 Spinner 绝对定位在按钮中央，避免改变通用按钮及其他页面的加载行为。

**Verification:**

- `pnpm --dir app test:run -- admin-pages.test.tsx` 通过（`2 files / 39 tests`），新增覆盖加载态禁用、`aria-busy`、可访问状态指示器和文字宽度占位。
- `pnpm --dir app build`、全仓 ESLint（`0 errors`）和本次三文件的 Prettier 检查通过；`git diff --check` 通过。

**Remaining verification:**

- 全仓 Prettier 检查仍报告 `69` 个既有未格式化文件；本次变更文件均已通过定向格式检查。
- 未在真实管理员会话中人工触发连接测试，也未读取、输入或使用任何真实 API Key。

---

## [2026-08-07 20:49] 加速供应商连接测试并放开无角色配置

**Changed files:**

- `server/bhzd_py/agent/providers.py`
- `server/bhzd_py/routers/admin.py`
- `server/tests/test_admin.py`
- `server/tests/test_providers.py`
- `docs/logs/document-changelog.md`

**Reason:**

- 已启用但未分配角色的供应商此前被管理端拒绝测试，阻碍管理员在完成角色配置前验证连接。
- 聊天供应商测试会等待完整生成；改为取得首个非空流式文本即成功，并以一个 token 的最小输出预算缩短交互等待。

**Verification:**

- `uv run pytest tests/test_admin.py tests/test_providers.py -q` 通过（`56 passed`）。
- `uv run ruff check bhzd_py/agent/providers.py bhzd_py/routers/admin.py tests/test_admin.py tests/test_providers.py`、`uv run python -m compileall -q bhzd_py` 与 `git diff --check` 通过。
- 已核验现有 `8787` 服务由 `PID 3620` 监听，`GET /api/health` 返回 `200`；本次源代码尚未经受控重启加载。

**Remaining verification:**

- 未使用真实供应商凭据或发起真实网络测试；实际耗时仍受供应商首 token 延迟、网络和排队影响。
- 待单独授权重启已确认归属的 `8787` 后端后，在真实管理员会话中复测连接测试。

---

## [2026-08-07 23:25] 新增学生端工作台视觉演示

**Changed files:**

- `docs/dev/student-workbench-layout-demo.html`
- `docs/logs/document-changelog.md`

**Reason:**

- 根据用户确认，新增独立可查看的学生端工作台原型，用于先审阅 MiniMax Code / Kimi Code 参考图所要求的常驻侧栏、居中单一输入器、快捷入口和会话态信息层级。
- 原型不接入正式路由、Agent 接口或学生端生产组件，避免在视觉方向尚未验收前影响现有业务行为。

**Verification:**

- `pnpm --dir app exec prettier --check ../docs/dev/student-workbench-layout-demo.html` 通过，覆盖内嵌 HTML、CSS 和 JavaScript 的格式解析。
- 已核对页面包含产品 Logo、左侧新建会话/最近会话、欢迎态主输入器、快捷入口与可切换会话态。

**Remaining verification:**

- 浏览器安全策略阻止自动打开本地 `file://` 演示文件，需由用户直接打开该 HTML 文件进行最终视觉审阅。
- 正式学生端重构仍待用户基于此原型确认，不在本次演示文件内实施。

---

## [2026-08-08 00:39] 产出学生工作台设计规范与样式对照页

**Changed files:**

- `docs/design/student-workbench-design-spec.md` (new)
- `docs/design/student-workbench-design-tokens.html` (new)
- `docs/logs/document-changelog.md`

**Reason:**

- 用户在确认范围（Agent 指挥舱 + 会话视图）后，要求基于演示原型 `docs/dev/student-workbench-layout-demo.html` 出一份可交付给前端的设计规范，并附一个可对照查看的样式总览页。
- 新建 `docs/design/` 目录统一收纳设计交付物；规范覆盖 Token、布局、组件、交互态、动效、响应式、可访问性，并提供 demo 行号对照表用于评审追溯。

**Verification:**

- 5 个抽样 Token / 数值（`--accent #2477d6` / `--radius-input 16px` / `@media (max-width: 900px)` / `font-size: clamp(30px, 3.2vw, 48px)` / `.send-button` 默认 `background: #d9dde2`）在 demo 中通过 `Select-String` 精确定位，行号与规范对照表一致（demo L17 / L24 / L789 / L452 / L555）。
- 规范文档中以可读形式记录同 5 项数值（`#2477d6` / `16px` / `≤ 900px` / `clamp(30px, 3.2vw, 48px)` / `#d9dde2`），与 demo 一致。
- 规范文档的 Token 章节、组件章节、响应式章节分别给出 demo 行号，可用于评审追溯。

**Remaining verification:**

- 设计规范基于单文件静态原型反推；演示中的侧栏折叠、视图切换、Toast 行为仅在 JS 中定义，未做实际浏览器截图比对，仅根据"代码声明的样式 + 注释里写明的意图"推导，需用户在实际浏览器中打开 demo 与对照页确认最终视觉。
- 对照页 `student-workbench-design-tokens.html` 是独立静态页，未嵌入真实路由或构建产物；上线前需与前端构建链路确认挂载位置。
- 五个未实现子模块（预设学习 / 能力图谱 / 学习任务 / 标注诊断 / 知识问答）暂未做内部规范，待各自落地时按本规范 Token 与组件库扩展。
- 暗色模式未在规范范围内（demo 为亮色中性灰白系统）。

---

## [2026-08-08 04:00] 方案 C 跨端工作台收尾

**Changed files:**

- `app/src/layouts/StudentWorkbenchShellContext.tsx`
- `app/src/layouts/StudentLayout.tsx`
- `app/src/layouts/ShellLayout.tsx`
- `app/src/layouts/TeacherLayout.tsx`
- `app/src/layouts/RagAdminLayout.tsx`
- `app/src/layouts/AdminLayout.tsx`
- `app/src/index.css`
- `app/src/pages/teacher/teacher-workbench.css`
- `app/src/pages/rag/ChunkEditorPage.tsx`
- `app/tests/student-enhancements.test.tsx`
- `app/tests/rag-admin-pages.test.tsx`
- `docs/design/student-workbench-design-spec.md`
- `docs/design/student-workbench-design-tokens.html`
- `docs/dev/student-workbench-layout-demo.html`

**Reason:**

- 将学生会话提升为全局左侧工作台能力，补齐个人中心、运行中导航保护和触屏删除可见性。
- 统一学生、教师、RAG 管理和系统管理的浅色运营壳层；将 RAG 切片编辑器从固定内联三栏改为可响应式回落的语义布局。
- 同步方案 C 设计规范、演示页和显式暗色主题约束。

**Verification:**

- `pnpm --dir app test:run`：21 个测试文件、181 项通过。
- `pnpm --dir app typecheck`、`pnpm --dir app build`、任务范围 Prettier、`git diff --check` 通过。
- 静态响应式审查确认运营抽屉、教师 Grid、表格局部横滚和 RAG 切片布局断点；现有 `5173`/`8787` 监听进程保持不变。

**Remaining verification:**

- 当前浏览器无授权测试会话，只能到 `/login`；需在已有授权学生/员工会话中人工复核四视口真实截图、账户菜单和 SSE 运行锁。
- 全仓 `pnpm --dir app format:check` 仍有 62 份既有未格式化文件，未在本任务中批量改写。

---

## [2026-08-08 04:06] 方案 C 最终格式与验证收口

**Changed files:**

- `docs/dev/student-workbench-layout-demo.html`
- `docs/logs/document-changelog.md`

**Reason:**

- 将演示稿统一为项目 Prettier 格式，避免设计原型在后续评审或改动时产生无关格式差异。
- 记录最终回归、运行服务归属和未能在当前会话完成的人工验收边界。

**Verification:**

- `pnpm --dir app test:run` 通过（`21` 个测试文件、`181` 项测试）。
- `pnpm --dir app typecheck`、`pnpm --dir app build`、任务范围 Prettier 与 `git diff --check` 通过。
- `127.0.0.1:5173`（本仓库 Vite）与 `127.0.0.1:8787/api/health` 均返回 HTTP `200`，未停止或重启任何服务。

**Remaining verification:**

- 当前浏览器没有已有授权的学生或员工测试会话，仍需在该会话中人工核验四个视口、账户菜单、门户切换和 SSE 运行锁。
- 全量 `pnpm --dir app format:check` 仍报告 `54` 个本任务范围外的既有未格式化文件；本次未进行批量无关改写。

---

## [2026-08-08 17:14] 收口学生工作台对话与供应商抽屉布局

**Changed files:**

- `docs/design/student-workbench-design-spec.md`
- `docs/design/student-workbench-design-tokens.html`
- `docs/dev/student-workbench-layout-demo.html`
- `docs/logs/document-changelog.md`

**Reason:**

- 同步学生端实现后的场景选择器位置、会话信息栏、固定 Composer、侧栏宽度/滚动行为和紧凑断点规则，避免设计交付物与正式工作台脱节。
- 修正静态演示在窄视口下可能继承桌面网格列的风险；即使侧栏先前处于折叠态，`900px` 以下也会回落到全宽主区和抽屉导航。

**Verification:**

- `pnpm --dir app test:run` 通过（`21` 个测试文件、`183` 项测试）。
- `pnpm --dir app typecheck`、`pnpm --dir app build`、任务范围 Prettier 与 `git diff --check` 通过。
- 已检查现有 `390px` 演示截图所暴露的横向裁切，并以紧凑断点下的显式全宽/溢出约束修正其根因。

**Remaining verification:**

- 当前浏览器没有已授权的学生或管理员测试会话，只能验证到登录页；仍需在实际会话中人工复核桌面和移动端的真实对话态与供应商抽屉。
- 浏览器安全策略阻止自动访问本地 `file://` 演示文件，修正后的静态演示仍需由用户在本机浏览器直接打开后完成视觉复核。

---

## [2026-08-08 17:34] 通知铃铛迁移至学生页面右上角

**Changed files:**

- `app/src/layouts/ShellLayout.tsx`
- `app/src/layouts/StudentLayout.tsx`
- `app/src/index.css`
- `app/tests/student-enhancements.test.tsx`
- `docs/design/student-workbench-design-spec.md`
- `docs/logs/document-changelog.md`

**Reason:**

- 按用户批准，将学生工作台通知铃铛从侧栏迁移到覆盖全部学生子路由的共享页面 toolbar 右侧。
- 页面操作栏采用正常 flex 流，为通知下拉面板和 Cockpit Composer 保留明确的垂直空间；移动端同时限制面板宽度，避免窄屏向左溢出。

**Verification:**

- `pnpm --dir app test:run` 通过（`21` 个测试文件、`183` 项测试）。
- `pnpm --dir app typecheck`、`pnpm --dir app build`、任务范围 Prettier 与 `git diff --check` 通过。
- 回归测试覆盖铃铛不属于侧栏、位于页面操作栏、具备 tooltip，以及跳转到任务详情后仍保留在该操作栏。

**Remaining verification:**

- 当前浏览器没有已授权学生会话，真实桌面和移动端页面的人工视觉验收仍需在该会话中完成。

---

## [2026-08-08 17:54] 修订学生端通知浮层与对话输入尺寸

**Changed files:**

- `docs/design/student-workbench-design-spec.md`
- `docs/logs/document-changelog.md`

**Reason:**

- 用户澄清学生端不应新增顶部通知操作栏；通知铃铛改为固定在视口右上角的浮层，脱离正常布局流，同时保留未读数、下拉面板、移动端可见性和窄屏宽度约束。
- 用户要求仅压缩已有对话态 Composer，目标约 `144px` 总高和 `64px` 文本区；欢迎页 Hero Prompt 维持既有尺寸。

**Verification:**

- 已逐项复核设计规范中的通知定位、移动端约束、Composer 变体和验收条款，确认 v7 明确取代 v6 的当前实现方案而未改写 v6 历史记录。

**Remaining verification:**

- 本次仅修改项目文档，未执行应用代码、测试、构建或浏览器视觉验证；实现完成后仍需验证固定浮层不占布局高度，以及桌面和窄屏下的通知面板与两种 Prompt 尺寸。

---

## [2026-08-08 18:11] 完成学生工作台布局修订实现

**Changed files:**

- `app/src/layouts/ShellLayout.tsx`
- `app/src/layouts/StudentLayout.tsx`
- `app/src/index.css`
- `app/src/pages/student/CockpitPage.tsx`
- `app/src/pages/student/cockpit/ChatStream.tsx`
- `app/src/pages/student/cockpit/Composer.tsx`
- `app/src/pages/student/cockpit/cockpit.css`
- `app/src/pages/admin/ProvidersPage.tsx`
- `app/tests/student-enhancements.test.tsx`
- `app/tests/cockpit.test.tsx`
- `app/tests/admin-pages.test.tsx`
- `docs/design/student-workbench-design-spec.md`

**Reason:**

- 完成场景选择器迁移、学生端通知固定浮层、帮助入口删除、侧栏收窄与滚动条隐藏、非对话子路由顶部留白、已有对话信息栏、独立消息滚动与固定 Composer，以及供应商抽屉测试连接行布局优化。
- 按最终修订要求保留通知功能，不新增学生端顶部操作栏；仅压缩已有对话态输入框，欢迎态 Hero 尺寸保持不变。

**Verification:**

- `pnpm --dir app test:run` 通过：21 个测试文件、183 项测试。
- `pnpm --dir app typecheck`、`pnpm --dir app build`、任务范围 Prettier 与 `git diff --check` 均通过。

**Remaining verification:**

- 当前浏览器没有授权学生会话，真实桌面/移动端对话态和供应商抽屉的视觉验收仍需在授权会话中完成。

---

## [2026-08-08 18:43] 固定会话信息栏并清理图谱标签滚动条

**Changed files:**

- `app/src/pages/student/CockpitPage.tsx`
- `app/src/pages/student/cockpit/ChatStream.tsx`
- `app/src/pages/student/cockpit/Composer.tsx`
- `app/src/pages/student/cockpit/cockpit.css`
- `app/src/pages/student/GraphPage.tsx`
- `app/src/index.css`
- `app/tests/cockpit.test.tsx`
- `app/tests/student-pages.test.tsx`
- `docs/design/student-workbench-design-spec.md`
- `docs/logs/document-changelog.md`

**Reason:**

- 按用户确认，将已有对话的信息栏移至 `.cockpit-content-scroll` 外的页面顶部常驻区域，保证标题与继续场景不随历史消息滚动；同时为移动端菜单和右上通知浮层保留安全间距。
- 移除 Composer 场景选择控件左侧的 FolderOpen 装饰图标；能力图谱的视图标签仅隐藏视觉滚动条，继续保留窄屏横向滚动，并避免影响教师端和 RAG 的共享 Tabs。

**Verification:**

- 定向 Vitest：`tests/cockpit.test.tsx`、`tests/student-pages.test.tsx` 共 `34` 项通过。
- 全量 `pnpm --dir app test:run` 通过：`21` 个测试文件、`183` 项测试。
- `pnpm --dir app typecheck`、`pnpm --dir app build`、任务范围 Prettier 与 `git diff --check` 通过。

**Remaining verification:**

- 当前浏览器没有授权学生会话；真实桌面和移动端下的信息栏、通知浮层和图谱筛选行视觉验收仍需人工完成。

---

## [2026-08-08 18:57] 精简会话信息栏与场景选择器

**Changed files:**

- `docs/design/student-workbench-design-spec.md`
- `docs/logs/document-changelog.md`

**Reason:**

- 按用户最终确认，已有对话的页面级信息栏只保留当前对话标题，移除“继续场景：通用”标签；继续场景仍由 Composer 中的选择器承载。
- 将 Composer 的继续场景选择器最大宽度收窄至 `160px`，保持长名称省略与原有 `title` 提示，避免挤占输入区。

**Verification:**

- 定向 Vitest：`tests/cockpit.test.tsx`、`tests/student-enhancements.test.tsx` 共 `35` 项通过。
- 全量 `pnpm --dir app test:run` 通过：`21` 个测试文件、`183` 项测试。
- `pnpm --dir app typecheck`、`pnpm --dir app build`、任务范围 Prettier 与 `git diff --check` 通过。

**Remaining verification:**

- 当前浏览器没有授权学生会话；真实桌面和移动端下的标题栏与长场景名称截断效果仍需人工视觉验收。

---

## [2026-08-08 19:08] 扩展对话顶部栏并纳入通知入口

**Changed files:**

- `docs/design/student-workbench-design-spec.md`
- `docs/logs/document-changelog.md`

**Reason:**

- 按用户确认，将对话信息栏扩展到侧边栏之外的完整主区顶部，并将通知铃铛及其下拉通知列表视觉归入顶部栏右侧。
- 其他学生子路由继续使用右上固定通知入口，不新增独立操作栏。

**Verification:**

- 定向 Vitest：`tests/cockpit.test.tsx`、`tests/student-enhancements.test.tsx` 共 `35` 项通过。
- 全量 `pnpm --dir app test:run` 通过：`21` 个测试文件、`183` 项测试。
- `pnpm --dir app typecheck`、`pnpm --dir app build`、任务范围 Prettier 与 `git diff --check` 通过。

**Remaining verification:**

- 当前浏览器没有授权学生会话；真实桌面和移动端下顶部栏与通知列表的视觉对齐仍需人工验收。

---

## [2026-08-08 19:22] 修复对话顶部标题栏裁切

**Changed files:**

- `app/src/pages/student/CockpitPage.tsx`
- `app/src/pages/student/cockpit/cockpit.css`
- `app/tests/cockpit.test.tsx`
- `docs/design/student-workbench-design-spec.md`
- `docs/logs/document-changelog.md`

**Reason:**

- 修复顶部栏使用负顶部外边距后被主内容 `overflow: hidden` 裁切、标题贴近视口边缘的问题。
- 将信息栏提升到 Cockpit 页面级节点，仅扩展左右宽度，避免受居中对话列最大宽度限制。

**Verification:**

- 定向 Vitest：`tests/cockpit.test.tsx`、`tests/student-enhancements.test.tsx` 共 `35` 项通过。
- 全量 `pnpm --dir app test:run` 通过：`21` 个测试文件、`183` 项测试。
- `pnpm --dir app typecheck`、`pnpm --dir app build`、任务范围 Prettier 与 `git diff --check` 通过。

**Remaining verification:**

- 当前浏览器没有授权学生会话；截图对应的真实桌面/移动端视觉验收仍需人工完成。

---

## [2026-08-08 19:38] 调整对话滚动边界与顶部留白

**Changed files:**

- `app/src/pages/student/CockpitPage.tsx`
- `app/src/pages/student/cockpit/cockpit.css`
- `app/tests/cockpit.test.tsx`
- `docs/logs/document-changelog.md`

**Reason:**

- 按用户确认，将对话区域的纵向滚动条固定在外层 `.cockpit-content-scroll`，新增 `.cockpit-content-inner` 仅负责消息内容排版，避免中间消息盒产生第二滚动边界。
- 移除标题栏与首条消息之间的额外底部留白，同时保留消息之间的阅读间距和 Composer 固定可见布局。

**Verification:**

- 定向 Vitest：`tests/cockpit.test.tsx`、`tests/cockpit-flow.test.tsx` 共 `46` 项通过。
- 全量 `pnpm --dir app test:run` 通过：`21` 个测试文件、`183` 项测试。
- `pnpm --dir app typecheck`、`pnpm --dir app build`、任务范围 Prettier 与 `git diff --check` 通过。

**Remaining verification:**

- 浏览器当前无授权学生会话，真实桌面/移动端下的长对话截图级视觉验收仍需在登录后完成；已确认未登录访问会被 `/api/auth/session` 的 401 重定向到 `/login`。

---

## [2026-08-08 23:40] RAG 库现状盘点与缺口评估

**Changed files:**
- docs/logs/document-changelog.md
- E:/ObsidianWorkSpace/logs/codex/Work Log 2026-08-08.md

**Reason:**
- 按用户要求评估当前 RAG 库的搭建进度、已覆盖项与剩余缺口，作为下一步实施的 task brief 依据。本次仅做只读调研与文档记录，未修改任何项目代码。

**Verification:**
- 通读 PRD-00/PRD-03/PRD-06 章节，与 server/bhzd_py/rag/、server/bhzd_py/routers/rag_*.py、server/bhzd_py/tools/rag_*.py、pp/src/pages/rag/、pp/src/pages/student/RagQaPage.tsx、server/bhzd_py/migrations/005_rag.sql 现状对账，结论：RAG 后端核心基本就绪（管线/检索/拒答/重排/管理/评测/发布/重试/敏感信息检测/多版本去重/台账联动均已实现），前端 RAG 管理 9 个页面 + 学生端 QA 页面均已落地，迁移与种子数据齐备。
- python -m pytest -q -p no:cacheprovider 在 server/ 下 377 passed。
- pnpm test:run 在 pp/ 下 159 用例通过、3 个测试文件（	ests/router.test.tsx、	ests/shell-layout.test.tsx、	ests/student-enhancements.test.tsx）因 pp/src/layouts/ShellLayout.tsx:592 未闭合的 <DesktopSidebarContext.Provider> 而 transform 失败——与 RAG 无关，属于"现状中需用户决策"的另一项。

**Remaining verification:**
- 是否进入 RAG 增强（重排模型接入、文档版本对比 UI、批量重处理、评测集自动运行等）以及是否一并修复 ShellLayout.tsx 标签错配，需要用户对当前 task brief 做明确决策后再继续。

## [2026-08-08 23:50] 修复 ShellLayout 标签错配并纠正 RAG 缺口评估

**Changed files:**
- pp/src/layouts/ShellLayout.tsx
- docs/logs/document-changelog.md
- E:/ObsidianWorkSpace/logs/codex/Work Log 2026-08-08.md

**Reason:**
- 修复合并失误：pp/src/layouts/ShellLayout.tsx:592 闭合了一个未正确开启的 </DesktopSidebarContext.Provider>（317 行开启但 591 行只关了一个外层 div、没有 wrapper 包裹）。补上正确的开闭顺序（Provider 在 317 行开，div 嵌入 Provider 内部，591 关 div、592 关 Provider），同时清理 className 重复的 "shell" 项。
- 用户原本要求评估 RAG 库搭建进度与剩余缺口；调研后发现 PRD-03 大部分 P0 项（含评测闭环、重排 E2E、版本历史 UI、批量重处理）实际上都已实现，前面给出的 brief 误判了多个"缺口"。本次仅修正一处真实代码问题，并按用户决定今天到此为止。

**Verification:**
- pnpm test:run 在 pp/ 下 21 个测试文件、183 个用例全过（含之前因 transform 失败挂掉的 	ests/router.test.tsx、	ests/shell-layout.test.tsx、	ests/student-enhancements.test.tsx）。
- python -m pytest -q -p no:cacheprovider 在 server/ 下 377 个用例全过，无回归。
- 重新核对了 server/bhzd_py/routers/rag_admin.py 31 个 RAG 管理端点 + ag_query.py 1 个学生端点，覆盖 PRD-03 §3–§13 全部 P0 范围；eval_runs 表、5 个评测指标、POST /api/rag/eval-runs、/api/rag/documents/batch、DocumentDetailPage 版本历史、EvalCasesPage 5 指标 + 历史对比 UI、test_rerank_provider_changes_order_and_reports_model 等关键能力均已存在并有测试覆盖。

**Remaining verification:**
- 真实"深度对账"（PRD-03 全部 13 节 + PRD-06 §4/§5 逐项勾叉）尚未完成，留作下一轮工作。
- 是否需要做端到端演示验收（AC3/4/5/6 走一遍上传→解析→送审→发布→学生问答→拒答+引用）由用户后续决定。

## [2026-08-08 23:51] 按方案 B 实现侧栏收起后的标题行展开入口

**Changed files:**
- app/src/components/PageHeader.tsx
- app/src/layouts/DesktopSidebarContext.tsx
- app/src/layouts/ShellLayout.tsx
- app/src/index.css
- app/tests/shell-layout.test.tsx
- docs/dev/companion-sidebar-title-options.html
- docs/logs/document-changelog.md

**Reason:**
- 用户确认采用方案 B：桌面侧栏完全收起后，非会话页面把 `PanelLeft` 展开按钮放在标题行第一列，标题从第二列开始；会话界面保留左上角例外按钮。
- 通过共享上下文、标题行三列布局和焦点回移，避免展开按钮覆盖页面标题，并同步学生端、教师端、系统管理端与 RAG 管理端的桌面工作台行为。

**Verification:**
- `pnpm vitest run tests/shell-layout.test.tsx`：5 个用例通过。
- `pnpm tsc --noEmit`：通过。
- `pnpm build`：通过，Vite 生产构建完成。
- 任务相关文件 `git diff --check`：通过；工作区其他既有文档改动保留未动。

**Remaining verification:**
- Companion 演示页可通过 `http://127.0.0.1:5190/companion-sidebar-title-options.html` 进行人工评估；自动截图因环境缺少 `browser-client.mjs` 未完成。

---
