-- Databasen oprettes automatisk ved første start. Tider er lokal tid: 'YYYY-MM-DD HH:MM'.

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY,
    username      TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    name          TEXT    NOT NULL,
    password_hash TEXT    NOT NULL,
    is_admin      INTEGER NOT NULL DEFAULT 0,
    active        INTEGER NOT NULL DEFAULT 1,
    ical_token    TEXT    NOT NULL UNIQUE,
    created_at    TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS tickets (
    id             INTEGER PRIMARY KEY,
    title          TEXT    NOT NULL,
    description    TEXT    NOT NULL DEFAULT '',
    category       TEXT    NOT NULL,
    location       TEXT    NOT NULL DEFAULT '',
    priority       INTEGER NOT NULL,               -- 1 = Akut ... 4 = Lav
    status         TEXT    NOT NULL DEFAULT 'ny',
    assignee_id    INTEGER REFERENCES users(id),
    created_by     INTEGER NOT NULL REFERENCES users(id),
    estimate_hours REAL,
    due_date       TEXT,                           -- 'YYYY-MM-DD'
    created_at     TEXT    NOT NULL,
    updated_at     TEXT    NOT NULL,
    closed_at      TEXT
);
CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status, priority);

-- Tidsblokke i kalenderen. En opgave kan have flere blokke (fx fejlfinding over to dage).
CREATE TABLE IF NOT EXISTS time_slots (
    id         INTEGER PRIMARY KEY,
    ticket_id  INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    user_id    INTEGER REFERENCES users(id),        -- hvem der udfører
    starts_at  TEXT    NOT NULL,
    ends_at    TEXT    NOT NULL,
    note       TEXT    NOT NULL DEFAULT '',
    created_by INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_slots_start ON time_slots(starts_at);
CREATE INDEX IF NOT EXISTS idx_slots_ticket ON time_slots(ticket_id);

-- Kommentarer og automatisk historik (is_event = 1) på en opgave.
CREATE TABLE IF NOT EXISTS comments (
    id         INTEGER PRIMARY KEY,
    ticket_id  INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    user_id    INTEGER REFERENCES users(id),
    body       TEXT    NOT NULL,
    is_event   INTEGER NOT NULL DEFAULT 0,
    created_at TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_comments_ticket ON comments(ticket_id);
