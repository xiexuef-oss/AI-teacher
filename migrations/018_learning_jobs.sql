CREATE TABLE learning_jobs (
  id CHAR(36) NOT NULL PRIMARY KEY,
  student_id CHAR(36) NOT NULL,
  command_key VARCHAR(128) NOT NULL,
  status VARCHAR(16) NOT NULL,
  attempts INT NOT NULL,
  available_at DATETIME(3) NOT NULL,
  lease_until DATETIME(3) NULL,
  lease_token CHAR(36) NULL,
  CONSTRAINT uq_learning_job_command UNIQUE (student_id, command_key),
  FOREIGN KEY (student_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
