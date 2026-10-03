-- Passages from PDFs (X9): each records its page, so its link opens the PDF there, and
-- a context (section path, table caption, column headers) that is searched and embedded
-- with the passage but never quoted. Web passages have no page and an empty context.

-- migrate:up
ALTER TABLE passages ADD COLUMN page integer CHECK (page > 0);
ALTER TABLE passages ADD COLUMN context text NOT NULL DEFAULT '';

-- migrate:down
ALTER TABLE passages DROP COLUMN context;
ALTER TABLE passages DROP COLUMN page;
