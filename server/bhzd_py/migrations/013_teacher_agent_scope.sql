-- Teacher Agent conversations are a separate workspace, not an alternate view
-- of the learner cockpit.  Existing rows remain explicitly scoped as student
-- data through the defaults below, while every new teacher row must carry the
-- class whose aggregates it is allowed to access.
ALTER TABLE conversations
  ADD COLUMN agent_scope TEXT NOT NULL DEFAULT 'student';
ALTER TABLE conversations
  ADD COLUMN class_id TEXT REFERENCES classes(id);

ALTER TABLE agent_runs
  ADD COLUMN agent_scope TEXT NOT NULL DEFAULT 'student';
ALTER TABLE agent_runs
  ADD COLUMN class_id TEXT REFERENCES classes(id);

-- SQLite cannot add a CHECK constraint to an existing table.  These triggers
-- keep direct SQL and future routes from creating an unscoped teacher run, and
-- bind a teacher run to the same owned workspace as its conversation.
CREATE TRIGGER validate_teacher_conversation_scope_insert
BEFORE INSERT ON conversations
WHEN NEW.agent_scope NOT IN ('student', 'teacher')
  OR (NEW.agent_scope = 'teacher' AND NEW.class_id IS NULL)
  OR (NEW.agent_scope = 'student' AND NEW.class_id IS NOT NULL)
BEGIN
  SELECT RAISE(ABORT, 'invalid agent conversation scope');
END;

CREATE TRIGGER validate_teacher_conversation_scope_update
BEFORE UPDATE OF agent_scope, class_id ON conversations
WHEN NEW.agent_scope NOT IN ('student', 'teacher')
  OR (NEW.agent_scope = 'teacher' AND NEW.class_id IS NULL)
  OR (NEW.agent_scope = 'student' AND NEW.class_id IS NOT NULL)
BEGIN
  SELECT RAISE(ABORT, 'invalid agent conversation scope');
END;

CREATE TRIGGER validate_teacher_run_scope_insert
BEFORE INSERT ON agent_runs
WHEN NEW.agent_scope NOT IN ('student', 'teacher')
  OR (NEW.agent_scope = 'teacher' AND NEW.class_id IS NULL)
  OR (NEW.agent_scope = 'student' AND NEW.class_id IS NOT NULL)
  OR (
    NEW.agent_scope = 'teacher'
    AND NOT EXISTS (
      SELECT 1
      FROM conversations
      WHERE id = NEW.conversation_id
        AND user_id = NEW.user_id
        AND agent_scope = 'teacher'
        AND class_id = NEW.class_id
    )
  )
BEGIN
  SELECT RAISE(ABORT, 'teacher run must match its conversation scope');
END;

CREATE TRIGGER validate_teacher_run_scope_update
BEFORE UPDATE OF agent_scope, class_id, conversation_id, user_id ON agent_runs
WHEN NEW.agent_scope NOT IN ('student', 'teacher')
  OR (NEW.agent_scope = 'teacher' AND NEW.class_id IS NULL)
  OR (NEW.agent_scope = 'student' AND NEW.class_id IS NOT NULL)
  OR (
    NEW.agent_scope = 'teacher'
    AND NOT EXISTS (
      SELECT 1
      FROM conversations
      WHERE id = NEW.conversation_id
        AND user_id = NEW.user_id
        AND agent_scope = 'teacher'
        AND class_id = NEW.class_id
    )
  )
BEGIN
  SELECT RAISE(ABORT, 'teacher run must match its conversation scope');
END;

-- The teacher UI lists only currently owned class workspaces.  The indexes
-- also keep ownership-rechecked run/replay reads from degrading as histories
-- grow, without changing the learner-Agent hot paths.
CREATE INDEX idx_teacher_agent_conversations_owner_class
  ON conversations (user_id, agent_scope, class_id, deleted_at, updated_at DESC);
CREATE INDEX idx_teacher_agent_runs_owner_class
  ON agent_runs (user_id, agent_scope, class_id, created_at DESC);
