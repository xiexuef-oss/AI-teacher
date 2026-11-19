CREATE TABLE learning_pack_returns (
  job_id CHAR(36) NOT NULL,
  code CHAR(3) NOT NULL,
  revision INT NOT NULL,
  question_version_id CHAR(36) NOT NULL,
  transcript TEXT NOT NULL,
  confirmed_at DATETIME(3) NOT NULL,
  PRIMARY KEY (job_id, code),
  FOREIGN KEY (job_id) REFERENCES learning_pack_publications(job_id),
  FOREIGN KEY (question_version_id) REFERENCES question_versions(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
