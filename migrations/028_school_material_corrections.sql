CREATE TABLE school_material_corrections (
  job_id CHAR(36) NOT NULL,
  page_number INT NOT NULL,
  revision INT NOT NULL,
  text TEXT NOT NULL,
  created_at DATETIME(3) NOT NULL,
  PRIMARY KEY (job_id, page_number, revision),
  FOREIGN KEY (job_id) REFERENCES school_material_results(job_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
