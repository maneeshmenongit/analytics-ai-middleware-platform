-- Expression index to serve per-project (Via "frame") queries that filter on
-- context->>'via.frame', a key inside the JSONB context column. Before this,
-- every such query -- "what did this root spend", "is this project captured"
-- -- was a full scan of pulse_events.
--
-- IF NOT EXISTS keeps this safe to re-apply (and safe alongside any other
-- branch that might create an index with a different name on the same
-- expression).
CREATE INDEX IF NOT EXISTS idx_pulse_events_via_frame
    ON pulse_events ((context ->> 'via.frame'));
