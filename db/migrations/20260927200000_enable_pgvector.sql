-- The vector type and its indexes, used for passage embeddings.

-- migrate:up
CREATE EXTENSION IF NOT EXISTS vector;

-- migrate:down
DROP EXTENSION IF EXISTS vector;
