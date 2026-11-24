CREATE TABLE IF NOT EXISTS credentials (
    digest TEXT PRIMARY KEY,
    owner TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS quotes (
    id TEXT PRIMARY KEY, owner TEXT NOT NULL, paise INTEGER NOT NULL CHECK(paise > 0),
    rate INTEGER NOT NULL CHECK(rate > 0), units INTEGER NOT NULL CHECK(units > 0),
    expires TEXT NOT NULL, created TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS quotes_by_owner ON quotes(owner, created DESC);
CREATE TABLE IF NOT EXISTS ledger (
    id TEXT PRIMARY KEY, owner TEXT NOT NULL, paise INTEGER NOT NULL CHECK(paise > 0),
    rate INTEGER NOT NULL CHECK(rate > 0), units INTEGER NOT NULL CHECK(units > 0),
    created TEXT NOT NULL, quote_id TEXT UNIQUE REFERENCES quotes(id),
    sip_id TEXT, due TEXT,
    CHECK ((quote_id IS NOT NULL AND sip_id IS NULL AND due IS NULL)
        OR (quote_id IS NULL AND sip_id IS NOT NULL AND due IS NOT NULL)),
    UNIQUE(sip_id, due)
);
CREATE INDEX IF NOT EXISTS ledger_by_owner ON ledger(owner, created DESC);
CREATE TABLE IF NOT EXISTS requests (
    owner TEXT NOT NULL, key TEXT NOT NULL, fingerprint TEXT NOT NULL, result TEXT NOT NULL,
    PRIMARY KEY(owner, key)
);
CREATE TABLE IF NOT EXISTS events (
    seq INTEGER PRIMARY KEY, time TEXT NOT NULL, owner TEXT NOT NULL,
    event TEXT NOT NULL, details TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_by_owner ON events(owner, seq);
CREATE TABLE IF NOT EXISTS sips (
    id TEXT PRIMARY KEY, owner TEXT NOT NULL, paise INTEGER NOT NULL CHECK(paise>0),
    frequency TEXT NOT NULL CHECK(frequency IN ('daily','weekly','monthly')),
    anchor INTEGER NOT NULL CHECK(anchor BETWEEN 1 AND 31),
    due TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('active','paused','cancelled'))
);
CREATE INDEX IF NOT EXISTS sips_due ON sips(state, due);
CREATE INDEX IF NOT EXISTS sips_owner ON sips(owner);
