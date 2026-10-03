-- Search channels (X44 F2): a passage is searched among the passages of its channel.
-- Company content (the site's pages, Lime Green's own documents) fills an answer's
-- places; pictures and general guidance (GOV.UK, titled with its publisher first) are
-- ranked apart and added after it, never in its place. Each picture keeps its SigLIP2
-- vector, so pictures are also ranked by what they show.

-- migrate:up
ALTER TABLE passages ADD COLUMN channel text NOT NULL DEFAULT 'company'
    CHECK (channel IN ('company', 'picture', 'guidance'));
UPDATE passages SET channel = 'picture' WHERE image IS NOT NULL;
UPDATE passages SET channel = 'guidance' WHERE image IS NULL AND title LIKE 'GOV.UK — %';
ALTER TABLE images ADD COLUMN siglip vector(1152);

-- migrate:down
ALTER TABLE images DROP COLUMN siglip;
ALTER TABLE passages DROP COLUMN channel;
