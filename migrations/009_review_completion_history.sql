-- DRAFT-303B: immutable completion evidence for the actual first submission.
-- Apply with writers stopped. A corrupt last pointer fails closed (NOT NULL),
-- leaving the migration ledger dirty and all original evidence intact.
CREATE TABLE review_completion_history (
  review_id CHAR(36) NOT NULL,
  first_attempt_id CHAR(36) NOT NULL,
  student_id CHAR(36) NOT NULL,
  question_id CHAR(36) NOT NULL,
  state VARCHAR(24) NOT NULL,
  result VARCHAR(16) NULL,
  completed_at DATETIME(3) NULL,
  PRIMARY KEY (review_id, first_attempt_id),
  CONSTRAINT fk_review_history_review FOREIGN KEY (review_id) REFERENCES review_items (id),
  CONSTRAINT fk_review_history_attempt FOREIGN KEY (first_attempt_id) REFERENCES attempts (id),
  CONSTRAINT fk_review_history_student FOREIGN KEY (student_id) REFERENCES users (id),
  CONSTRAINT fk_review_history_question FOREIGN KEY (question_id) REFERENCES questions (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Deliberately fail rather than silently discard an inconsistent last reference.
INSERT INTO review_completion_history
  (review_id, first_attempt_id, student_id, question_id, state, result, completed_at)
SELECT r.id, NULL, r.student_id, r.question_id, 'legacy_unknown', NULL, NULL
FROM review_items r
LEFT JOIN attempts a ON a.id = r.last_attempt_id
LEFT JOIN study_sessions s ON s.id = a.session_id
WHERE r.last_attempt_id IS NOT NULL AND NOT COALESCE(
  s.review_item_id = r.id AND s.student_id = r.student_id
  AND s.question_id = r.question_id AND s.origin = 'review'
  AND a.submission_no = 1 AND a.status = 'submitted'
  AND a.evaluation_state = 'verified'
  AND r.last_result = CASE WHEN a.is_correct = 1 AND a.independent = 1
    THEN 'passed' ELSE 'failed' END, 0);

-- updated_at can have changed after completion: never invent its completion time.
-- Other eligible legacy submissions may or may not have been consumed.
INSERT INTO review_completion_history
  (review_id, first_attempt_id, student_id, question_id, state, result, completed_at)
SELECT r.id, a.id, r.student_id, r.question_id,
  CASE WHEN r.last_attempt_id = a.id THEN 'completed' ELSE 'legacy_unknown' END,
  CASE WHEN r.last_attempt_id = a.id THEN r.last_result ELSE NULL END, NULL
FROM review_items r
JOIN study_sessions s ON s.review_item_id = r.id AND s.student_id = r.student_id
  AND s.question_id = r.question_id AND s.origin = 'review'
JOIN attempts a ON a.session_id = s.id AND a.submission_no = 1
  AND a.status = 'submitted' AND a.evaluation_state = 'verified';
