CREATE TABLE school_material_confirmations (
  job_id CHAR(36) NOT NULL,
  source_revision VARCHAR(64) NOT NULL,
  items_json JSON NOT NULL,
  created_at DATETIME(3) NOT NULL,
  PRIMARY KEY (job_id, source_revision),
  FOREIGN KEY (job_id) REFERENCES school_material_results(job_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
