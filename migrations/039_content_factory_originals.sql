CREATE TABLE cf_source_originals (
  source_id CHAR(36) NOT NULL,
  region_code CHAR(5) NOT NULL,
  kind VARCHAR(16) NOT NULL,
  content MEDIUMBLOB NOT NULL,
  expires_at DATETIME(3) NOT NULL,
  PRIMARY KEY (source_id, region_code),
  FOREIGN KEY (source_id) REFERENCES cf_sources(id),
  INDEX ix_cf_original_expiry (expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
