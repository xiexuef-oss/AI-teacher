-- Metadata-only invocation preparation. Dispatch/budget transaction is not enabled yet.
CREATE TABLE model_invocation_intents (
  id CHAR(32) NOT NULL PRIMARY KEY,
  actor_digest CHAR(64) NOT NULL,
  active_session_digest CHAR(64) NULL,
  state VARCHAR(24) NOT NULL,
  fence INT NOT NULL,
  metadata_json JSON NOT NULL,
  UNIQUE KEY uq_model_invocation_active_session (active_session_digest)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
