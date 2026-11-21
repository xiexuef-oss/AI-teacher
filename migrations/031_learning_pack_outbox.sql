CREATE TABLE learning_pack_outbox (
  job_id CHAR(36) NOT NULL PRIMARY KEY,
  created_at DATETIME(3) NOT NULL,
  delivered_at DATETIME(3) NULL,
  FOREIGN KEY (job_id) REFERENCES learning_pack_commands(job_id) ON DELETE CASCADE,
  INDEX ix_learning_pack_outbox_pending (delivered_at, created_at, job_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
