-- The audit record of every answer served from Postgres: what was asked, what the
-- reader was shown, what verification removed, and what produced it (passages, index
-- version, embedding model, prompts), so any answer can be reconstructed and reviewed.
-- The shown view keeps its quotes, so a record stays readable after its index version
-- is deleted; hence no foreign keys. Questions can hold personal data: records are
-- deleted by age under a retention period still to be set with Lime Green (UK GDPR
-- storage limitation), using the created_at index.

-- migrate:up
CREATE TABLE answers (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at timestamptz NOT NULL DEFAULT now(),
    question text NOT NULL,
    status text NOT NULL
        CHECK (status IN ('answered', 'insufficient_evidence', 'safety_referral')),
    shown jsonb NOT NULL,           -- the reader's view (view.AnswerView)
    removed jsonb NOT NULL,         -- claims removed by verification: text and reason
    passage_ids bigint[] NOT NULL,  -- the passages the model was given, best first
    index_version_id bigint NOT NULL,
    embedding_model text NOT NULL,
    prompt_sha256 text NOT NULL,    -- the fixed system prompts in use
    seconds real NOT NULL           -- time to answer
);

CREATE INDEX answers_created_at ON answers (created_at);

-- migrate:down
DROP TABLE answers;
