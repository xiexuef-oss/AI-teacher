CREATE TABLE school_material_commands (
  job_id CHAR(36) NOT NULL PRIMARY KEY,
  media_id CHAR(36) NOT NULL,
  FOREIGN KEY (job_id) REFERENCES learning_jobs(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
