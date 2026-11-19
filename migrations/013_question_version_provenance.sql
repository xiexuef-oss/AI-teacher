-- CONTENT303A: optional immutable origin metadata; legacy versions remain NULL.
ALTER TABLE question_versions ADD COLUMN provenance_json JSON NULL;
