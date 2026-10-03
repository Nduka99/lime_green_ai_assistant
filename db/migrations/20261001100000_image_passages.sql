-- Pictures (X43): every picture of the site's pages and documents is stored once, as
-- PNG, named by the SHA-256 of those bytes; old answers keep showing theirs, as pages
-- are kept. A passage made from a picture names it: its text is the picture's own
-- words (alt text, text read in it), and the picture is shown beside a claim citing it.

-- migrate:up
CREATE TABLE images (
    id text PRIMARY KEY CHECK (id ~ '^[0-9a-f]{64}$'),
    png bytea NOT NULL
);
ALTER TABLE passages ADD COLUMN image text REFERENCES images (id);

-- migrate:down
ALTER TABLE passages DROP COLUMN image;
DROP TABLE images;
