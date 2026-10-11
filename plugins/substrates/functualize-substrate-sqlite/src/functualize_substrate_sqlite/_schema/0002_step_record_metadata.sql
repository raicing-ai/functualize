ALTER TABLE workflow_steps ADD COLUMN result_kind TEXT;
ALTER TABLE workflow_steps ADD COLUMN result_type TEXT;
ALTER TABLE workflow_steps ADD COLUMN effecting INTEGER NOT NULL DEFAULT 0 CHECK (effecting IN (0, 1));
