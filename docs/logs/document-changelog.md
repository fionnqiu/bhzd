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
