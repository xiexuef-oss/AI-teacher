CREATE TABLE learning_pack_commands (
  job_id CHAR(36) NOT NULL PRIMARY KEY,
  input_json JSON NOT NULL,
  plan_json JSON NULL,
  FOREIGN KEY (job_id) REFERENCES learning_jobs(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
