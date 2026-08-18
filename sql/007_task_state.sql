-- Migration 007: Agent task state persistence and resumable execution
-- Stores multi-step agent tasks, step-by-step progress, payload, and results.

CREATE TABLE IF NOT EXISTS agent_tasks (
    task_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id  UUID NOT NULL REFERENCES sessions (session_id),
    kind        STRING NOT NULL,          -- 'corpus_audit' | 'takedown_sweep'
    state       STRING NOT NULL,          -- pending | running | blocked | done | failed
    step_no     INT NOT NULL DEFAULT 0,
    total_steps INT,
    payload     JSONB,
    result      JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    INDEX idx_tasks_session (session_id, created_at DESC),
    INDEX idx_tasks_resumable (state) WHERE state IN ('pending','running','blocked')
);
