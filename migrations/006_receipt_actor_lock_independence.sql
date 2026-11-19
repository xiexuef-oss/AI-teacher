-- DATA-302: receipt audit identifiers must not share actor-row locks with business writes.
-- 005 is immutable; remove only the FK coupling, keeping actor/key uniqueness and history.
ALTER TABLE idempotency_receipts DROP FOREIGN KEY fk_receipt_actor;
