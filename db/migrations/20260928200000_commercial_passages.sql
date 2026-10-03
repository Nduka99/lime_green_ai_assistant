-- The price fence (experiment X16): a passage that contains a currency amount is
-- stored but never searched, so no answer can quote a price from indexed text. New
-- passages are tagged when written (limespec.prices.CURRENCY_AMOUNT); the passages
-- stored before this migration are tagged here with the same pattern in Postgres's
-- syntax (\y is Postgres's word boundary).

-- migrate:up
ALTER TABLE passages ADD COLUMN commercial boolean NOT NULL DEFAULT false;
UPDATE passages SET commercial = text ~ '[£$€¥]\s?[0-9]|[0-9]\s?(GBP|EUR|USD)\y';

-- migrate:down
ALTER TABLE passages DROP COLUMN commercial;
