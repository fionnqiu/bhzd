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

For every Codex task, append one entry to `E:\ObsidianWorkSpace\logs\codex\Work Log YYYY-MM-DD.md` before the final user-facing response. Follow the existing daily format:

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

## Backend Verification and Automatic Restart

When backend code, configuration, dependencies, migrations, or backend tests are changed:

- Run focused tests for the affected behavior, then run the backend suite from `server` with `uv run pytest -q`. Add compile, type, or lint checks when the changed surface requires them.
- Do not restart a backend whose required self-checks fail. Fix only in-scope failures, rerun the checks, and preserve unrelated worktree changes.
- After all required checks pass, identify the listener on `127.0.0.1:8787` with `Get-NetTCPConnection`, then map its PID to `Win32_Process` command line, parent chain, and working directory. Restart only a process confirmed to be this BHZD checkout; never stop a shared or unidentified service.
- Start the latest backend from the project `server` directory. Record the old and new PID, command line, and restart time in the task logs.
- After restarting, verify `GET /api/health` and the API routes affected by the change. If the new listener, health check, or key API check fails, report the failure and retain diagnostic logs; do not claim the service is ready.
- Frontend-only or documentation-only changes do not trigger a backend restart unless the task brief explicitly includes one.
