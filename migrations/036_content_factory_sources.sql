CREATE TABLE cf_sources (
  id CHAR(36) NOT NULL PRIMARY KEY,
  title VARCHAR(255) NOT NULL,
  source_class VARCHAR(24) NOT NULL,
  sha256 CHAR(64) NOT NULL,
  created_by CHAR(36) NOT NULL,
  created_at DATETIME(3) NOT NULL,
  FOREIGN KEY (created_by) REFERENCES users(id),
  CONSTRAINT ck_cf_source_class CHECK (
    source_class IN ('original', 'licensed', 'open', 'public_reference')
  )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE cf_source_permissions (
  source_id CHAR(36) NOT NULL,
  operation VARCHAR(32) NOT NULL,
  region_code CHAR(5) NOT NULL,
  evidence_ref VARCHAR(512) NOT NULL,
  reviewed_by CHAR(36) NOT NULL,
  valid_from DATETIME(3) NOT NULL,
  valid_until DATETIME(3) NOT NULL,
  revoked_at DATETIME(3) NULL,
  PRIMARY KEY (source_id, operation, region_code),
  FOREIGN KEY (source_id) REFERENCES cf_sources(id),
  FOREIGN KEY (reviewed_by) REFERENCES users(id),
  CONSTRAINT ck_cf_source_period CHECK (valid_until > valid_from),
  CONSTRAINT ck_cf_source_evidence CHECK (CHAR_LENGTH(TRIM(evidence_ref)) > 0),
  CONSTRAINT ck_cf_source_operation CHECK (
    operation IN ('read', 'internal_analysis', 'store_original', 'transform',
                  'generate_variants', 'print_pdf', 'commercial_distribution', 'send_to_external_ai')
  )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
