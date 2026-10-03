-- Conversations (PLAN §0e, ADR 0035): a conversation is a sequence of single-turn
-- answers. The server makes its id, a random UUIDv4 (122 bits; OWASP asks for at least
-- 64), and enforces its limits when a turn is reserved: idle and absolute timeouts and
-- a turn cap, never left to the client. Each answer record keeps its conversation, its
-- turn and the search questions the first request wrote, so the next turn's history is
-- rebuilt from what the user was shown (`answers.shown`). Answers outside a
-- conversation (the command line, in-process evaluation) leave both empty.
-- Conversations fall under the answers' retention period, still to be set.

-- migrate:up
CREATE TABLE conversations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at timestamptz NOT NULL DEFAULT now(),
    last_active_at timestamptz NOT NULL DEFAULT now(),
    turns integer NOT NULL DEFAULT 0  -- turns reserved so far, failed ones included
);

CREATE INDEX conversations_created_at ON conversations (created_at);

ALTER TABLE answers
    ADD COLUMN conversation_id uuid REFERENCES conversations (id),
    ADD COLUMN turn integer,
    ADD COLUMN search_questions jsonb NOT NULL DEFAULT '[]',
    ADD CONSTRAINT answers_turn_with_conversation
        CHECK ((conversation_id IS NULL) = (turn IS NULL));

CREATE UNIQUE INDEX answers_conversation_turn ON answers (conversation_id, turn);

-- migrate:down
ALTER TABLE answers
    DROP COLUMN search_questions,
    DROP COLUMN turn,
    DROP COLUMN conversation_id;
DROP TABLE conversations;
