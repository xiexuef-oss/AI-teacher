CREATE TABLE learning_pack_corrections (
  job_id CHAR(36) NOT NULL,
  code CHAR(3) NOT NULL,
  revision INT NOT NULL,
  transcript TEXT NOT NULL,
  actor_id CHAR(36) NOT NULL,
  corrected_at DATETIME(3) NOT NULL,
  PRIMARY KEY (job_id, code, revision),
  FOREIGN KEY (job_id, code) REFERENCES learning_pack_returns(job_id, code),
  FOREIGN KEY (actor_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
