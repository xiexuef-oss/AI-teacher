-- Fixed three-question plans. Existing sessions own all answers, ink and grading.
CREATE TABLE diagnostic_runs (
  id CHAR(36) NOT NULL PRIMARY KEY,
  student_id CHAR(36) NOT NULL,
  subject VARCHAR(16) NOT NULL,
  scope_json JSON NOT NULL,
  created_at DATETIME(3) NOT NULL,
  abandoned_at DATETIME(3) NULL,
  KEY ix_diagnostic_student_created (student_id, created_at),
  FOREIGN KEY (student_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE diagnostic_states (
  student_id CHAR(36) NOT NULL PRIMARY KEY,
  revision INT NOT NULL DEFAULT 0,
  current_run_id CHAR(36) NULL,
  FOREIGN KEY (student_id) REFERENCES users(id),
  FOREIGN KEY (current_run_id) REFERENCES diagnostic_runs(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE diagnostic_items (
  run_id CHAR(36) NOT NULL,
  position INT NOT NULL,
  question_id CHAR(36) NOT NULL,
  question_version INT NOT NULL,
  summary_json JSON NOT NULL,
  session_id CHAR(36) NULL,
  PRIMARY KEY (run_id, position),
  UNIQUE KEY uq_diagnostic_session (session_id),
  UNIQUE KEY uq_diagnostic_question (run_id, question_id),
  FOREIGN KEY (run_id) REFERENCES diagnostic_runs(id),
  CONSTRAINT fk_diagnostic_question_version FOREIGN KEY (question_id, question_version)
    REFERENCES question_versions(question_id, version),
  FOREIGN KEY (session_id) REFERENCES study_sessions(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
