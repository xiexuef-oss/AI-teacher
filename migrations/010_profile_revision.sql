-- DRAFT-303C: explicit monotonic compare-and-swap for student profile writes.
ALTER TABLE student_profiles ADD COLUMN revision INT NOT NULL DEFAULT 0;
