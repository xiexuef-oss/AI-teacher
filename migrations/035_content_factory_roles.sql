CREATE TABLE cf_role_assignments (
  user_id CHAR(36) NOT NULL,
  cf_role VARCHAR(16) NOT NULL,
  assigned_by CHAR(36) NOT NULL,
  assigned_at DATETIME(3) NOT NULL,
  PRIMARY KEY (user_id, cf_role),
  FOREIGN KEY (user_id) REFERENCES users(id),
  FOREIGN KEY (assigned_by) REFERENCES users(id),
  CONSTRAINT ck_cf_role CHECK (cf_role IN ('editor', 'reviewer', 'publisher', 'admin'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
