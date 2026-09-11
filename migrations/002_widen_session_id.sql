-- PulseWise — widen session_id.
--
-- WHY. session_id was VARCHAR(64). Via names projects by ABSOLUTE PATH and sends
-- the project identifier here, so a 67-character frame
-- (/Users/.../via-projects/paper-trader/state) overflowed the column and every
-- INSERT died with StringDataRightTruncation. Production run #6 lost 85 of 88
-- events this way: the value passed validate_event() (which checks non-empty,
-- never length) and failed at INSERT, surfacing as a 503 rather than a clean
-- rejection.
--
-- Via now sends a bounded uuid5 digest of the frame and carries the full frame in
-- `context`, so 36 characters would suffice for that client. The column is widened
-- anyway: an analytics identifier column should not be the thing that decides what
-- a client may call a session, and the next client will not be Via.
--
-- NOT NULL is kept, and idx_events_session is left in place -- the per-project
-- join this integration exists for depends on that index. Postgres rewrites no
-- rows for a varchar widening and rebuilds no index, so this is metadata-only.
--
-- NOT CHANGED, deliberately: product VARCHAR(32) and event_type VARCHAR(64).
-- Nobody has hit either, and widening a column nobody has overflowed is a silent
-- change to a contract other clients were built against. Reported, not applied.

ALTER TABLE pulse_events
    ALTER COLUMN session_id TYPE VARCHAR(255);
