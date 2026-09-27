-- The searchable index: captured pages, index versions, and the passages built from
-- them. An index version is built beside the live one and swapped in by one update,
-- so a failed build never touches what is being served.

-- migrate:up
CREATE TABLE documents (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    url text NOT NULL,
    title text NOT NULL,
    fetched_at timestamptz NOT NULL,
    sha256 text NOT NULL,  -- of the exact fetched bytes
    UNIQUE (url, sha256)   -- the same capture is stored once; a changed page is a new row
);

CREATE TABLE index_versions (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    built_at timestamptz NOT NULL DEFAULT now(),
    corpus_sha256 text NOT NULL,    -- sorted (url, page sha256) pairs
    passages_sha256 text NOT NULL,  -- url and text of every passage: compares builds
    embedding_model text NOT NULL,  -- the API refuses to serve with a different model
    live boolean NOT NULL DEFAULT false
);

-- At most one live version: switching versions is one transaction.
CREATE UNIQUE INDEX index_versions_one_live ON index_versions (live) WHERE live;

CREATE TABLE passages (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    index_version_id bigint NOT NULL REFERENCES index_versions (id) ON DELETE CASCADE,
    document_id bigint NOT NULL REFERENCES documents (id),
    title text NOT NULL,    -- the page title, searched with the text as before
    heading text NOT NULL,  -- the passage text starts with it
    text text NOT NULL,
    -- Unit length (Qwen3-Embedding 0.6B, 1024 dimensions), so the inner product is
    -- the cosine similarity. No approximate index: exact search has perfect recall
    -- and a few hundred passages are fast to scan.
    embedding vector(1024) NOT NULL,
    search tsvector GENERATED ALWAYS AS (to_tsvector('english', title || ' ' || text)) STORED
);

CREATE INDEX passages_index_version ON passages (index_version_id);
CREATE INDEX passages_search ON passages USING gin (search);

-- migrate:down
DROP TABLE passages;
DROP TABLE index_versions;
DROP TABLE documents;
