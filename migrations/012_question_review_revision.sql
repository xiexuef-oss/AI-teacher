-- ADMIN recovery: independent monotonic review epoch, old rows establish baseline 1.
ALTER TABLE questions ADD COLUMN review_revision BIGINT NOT NULL DEFAULT 1;
