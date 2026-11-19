CREATE TABLE school_material_results (
  job_id CHAR(36) NOT NULL PRIMARY KEY,
  expires_at DATETIME(3) NOT NULL,
  pages_json JSON NOT NULL,
  FOREIGN KEY (job_id) REFERENCES school_material_commands(job_id),
  INDEX ix_school_material_results_expires_at (expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
