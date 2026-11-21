CREATE TABLE learning_pack_render_checkpoints (
  job_id CHAR(36) NOT NULL PRIMARY KEY,
  input_sha256 CHAR(64) NOT NULL,
  student_pdf MEDIUMBLOB NOT NULL,
  manifest_json JSON NOT NULL,
  FOREIGN KEY (job_id) REFERENCES learning_pack_commands(job_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
