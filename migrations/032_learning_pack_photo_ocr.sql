CREATE TABLE learning_pack_photo_ocr (
  job_id CHAR(36) NOT NULL PRIMARY KEY,
  pack_id CHAR(36) NOT NULL,
  code CHAR(3) NOT NULL,
  item_json JSON NOT NULL,
  photo_ids_json JSON NOT NULL,
  expires_at DATETIME(3) NOT NULL,
  candidate TEXT NULL,
  INDEX ix_learning_pack_photo_ocr_expires_at (expires_at),
  FOREIGN KEY (job_id) REFERENCES learning_jobs(id) ON DELETE CASCADE,
  FOREIGN KEY (pack_id) REFERENCES learning_pack_publications(job_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
