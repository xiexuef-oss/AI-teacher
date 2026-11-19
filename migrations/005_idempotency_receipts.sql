-- DATA-302: durable business receipts; no prototype import/identity tables.
CREATE TABLE idempotency_receipts (
  id CHAR(36) NOT NULL,
  actor_id CHAR(36) NOT NULL,
  key_digest CHAR(64) NOT NULL,
  fingerprint CHAR(64) NOT NULL,
  state VARCHAR(16) NOT NULL,
  status_code SMALLINT NULL,
  response_json JSON NULL,
  created_at DATETIME(3) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_receipt_actor_key (actor_id, key_digest),
  CONSTRAINT fk_receipt_actor FOREIGN KEY (actor_id) REFERENCES users(id),
  CONSTRAINT ck_receipt_state CHECK (state IN ('reserved', 'complete')),
  CONSTRAINT ck_receipt_complete CHECK (state <> 'complete' OR (status_code IS NOT NULL AND response_json IS NOT NULL))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
