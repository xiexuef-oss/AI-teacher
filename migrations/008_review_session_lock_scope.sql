-- DRAFT-301B: scope review locks by owner and review before locking attempts.
CREATE INDEX ix_sessions_review_owner ON study_sessions (student_id, review_item_id, id);
