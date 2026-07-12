# Project Instructions

## Task Review Gate

Before executing any new task, first provide the user with a detailed task brief for review. The brief must state:

- Objective and expected outcome.
- Scope and explicit non-goals.
- Relevant inputs, proposed files or systems to change, and the intended implementation approach.
- Acceptance criteria, verification method, risks, assumptions, and any decision that needs user input.

Do not modify project files, implement features, create external artifacts, or start long-running work until the user explicitly approves the current task brief. Read-only investigation needed to prepare the brief is allowed.

An approval applies only to the reviewed brief. If the user changes the requirement during planning or execution, stop the affected work, revise the brief and every affected product, design, plan, acceptance, or submission document, then request confirmation before resuming implementation.

## Document Change Logs

For every change to a project document, append an entry to `docs/logs/document-changelog.md` before the final user-facing response. Each entry must state the changed files, the reason for the change, the verification performed, and any remaining factual verification required. Keep this repository log separate from the external task work log.

## Work Logs

For every Codex task, append one entry to `E:\ObsidianWorkSpace\codex\Work Log YYYY-MM-DD.md` before the final user-facing response. Follow the existing daily format:

```markdown
## [HH:mm] Short task title

**What was done:**
- ...

**Key decisions:**
- ...

**Results:**
- ...

---
```
