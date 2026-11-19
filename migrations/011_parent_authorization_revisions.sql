-- DRAFT-303C: separate authorization and invite-generation epochs.
-- Apply with writers stopped; existing rows establish a baseline, not inferred history.
ALTER TABLE parent_student_links ADD COLUMN authorization_revision BIGINT NOT NULL DEFAULT 1;
ALTER TABLE student_profiles ADD COLUMN parent_invite_revision BIGINT NOT NULL DEFAULT 0;
