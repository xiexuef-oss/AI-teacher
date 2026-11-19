-- DRAFT-301B: creation order stays in attempt_no; drafts consume no submission number.
ALTER TABLE attempts
  ADD COLUMN submission_no INT NULL,
  ADD COLUMN copied_from_attempt_id CHAR(36) NULL,
  ADD COLUMN copied_from_revision INT NULL;

-- ROW_NUMBER materializes the derived table and makes the legacy backfill deterministic.
UPDATE attempts AS target
JOIN (
  SELECT id, ROW_NUMBER() OVER (
    PARTITION BY session_id ORDER BY submitted_at, attempt_no, id
  ) AS submission_no
  FROM attempts
  WHERE status = 'submitted'
) AS ordered_submissions ON ordered_submissions.id = target.id
SET target.submission_no = ordered_submissions.submission_no;

ALTER TABLE attempts
  ADD UNIQUE KEY uq_attempt_submission (session_id, submission_no),
  ADD CONSTRAINT fk_attempt_copy_source FOREIGN KEY (copied_from_attempt_id) REFERENCES attempts (id);

