CREATE TABLE cf_generation_jobs (
  id CHAR(36) NOT NULL PRIMARY KEY,
  requested_by CHAR(36) NOT NULL,
  source_id CHAR(36) NULL,
  kind VARCHAR(32) NOT NULL,
  parameters_json JSON NOT NULL,
  status VARCHAR(24) NOT NULL,
  attempts INT NOT NULL,
  available_at DATETIME(3) NOT NULL,
  lease_until DATETIME(3) NULL,
  lease_token CHAR(36) NULL,
  result_json JSON NULL,
  FOREIGN KEY (requested_by) REFERENCES users(id),
  FOREIGN KEY (source_id) REFERENCES cf_sources(id),
  INDEX ix_cf_ready (status, available_at, id),
  INDEX ix_cf_lease (status, lease_until, id),
  CONSTRAINT ck_cf_job_status CHECK (
    status IN ('queued', 'running', 'retry_wait', 'review_required', 'failed', 'cancelled')
  )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
