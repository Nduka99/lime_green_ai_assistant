-- Keyword search by BM25 (pg_textsearch), chosen by experiment X2
-- (evaluation/reports/X2-store-parity.md). Each index version gets its own BM25 index,
-- created by store.write_version, so word statistics cover that version alone. The
-- English configuration stems words but keeps stop words, as SQLite's porter tokenizer
-- did: removing them made keyword search worse and can invert meaning ("not").
-- Postgres's built-in ts_rank lost the X2 comparison, so its column goes.

-- migrate:up
CREATE EXTENSION IF NOT EXISTS pg_textsearch;

CREATE TEXT SEARCH DICTIONARY english_stem_keep_stop (TEMPLATE = snowball, Language = english);
CREATE TEXT SEARCH CONFIGURATION english_keep_stop (COPY = english);
ALTER TEXT SEARCH CONFIGURATION english_keep_stop
    ALTER MAPPING REPLACE english_stem WITH english_stem_keep_stop;

DROP INDEX passages_search;
ALTER TABLE passages DROP COLUMN search;

-- migrate:down
ALTER TABLE passages ADD COLUMN search tsvector
    GENERATED ALWAYS AS (to_tsvector('english', title || ' ' || text)) STORED;
CREATE INDEX passages_search ON passages USING gin (search);

DROP TEXT SEARCH CONFIGURATION english_keep_stop;
DROP TEXT SEARCH DICTIONARY english_stem_keep_stop;
DROP EXTENSION IF EXISTS pg_textsearch;
