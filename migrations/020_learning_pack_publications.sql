CREATE TABLE learning_pack_publications (
  job_id CHAR(36) NOT NULL PRIMARY KEY,
  student_pdf MEDIUMBLOB NOT NULL,
  solution_pdf MEDIUMBLOB NOT NULL,
  manifest_json JSON NOT NULL,
  FOREIGN KEY (job_id) REFERENCES learning_jobs(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
