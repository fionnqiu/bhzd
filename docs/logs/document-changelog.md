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
- `E:\\ObsidianWorkSpace\\codex\\Work Log 2026-07-13.md`

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
