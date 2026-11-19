-- Metadata-only cost alerts and an explicit shared durable-dispatch pause.
-- No default policy enables providers; runtime configuration decides whether an overrun pauses.
CREATE TABLE model_budget_incidents (
  id CHAR(32) NOT NULL PRIMARY KEY,
  metadata_json JSON NOT NULL,
  created_at DATETIME(3) NOT NULL,
  KEY ix_model_budget_incidents_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE model_dispatch_gate (
  id VARCHAR(16) NOT NULL PRIMARY KEY,
  paused BOOLEAN NOT NULL,
  incident_id CHAR(32) NULL,
  updated_at DATETIME(3) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
