CREATE TABLE IF NOT EXISTS sessions (
    session_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    corpus_id    UUID NOT NULL REFERENCES corpora (corpus_id),
    started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor        STRING,
    INDEX idx_sessions_actor (actor, last_seen_at DESC)
);

CREATE TABLE IF NOT EXISTS session_turns (
    turn_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id  UUID NOT NULL REFERENCES sessions (session_id),
    turn_no     INT  NOT NULL,
    role        STRING NOT NULL,        -- 'user' | 'agent'
    content     STRING NOT NULL,
    answer_id   UUID REFERENCES answers (answer_id),  -- agent turns only
    embedding   VECTOR(1024),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (session_id, turn_no),
    INDEX idx_turns_session (session_id, turn_no)
);

CREATE VECTOR INDEX IF NOT EXISTS idx_turns_embedding
    ON session_turns (embedding vector_cosine_ops);
