-- ============================================================
--  TransitFlow — PostgreSQL 15 Complete Schema
--  LLM Provider: Ollama (embedding dimension: 768)
--  Design Decision Summary:
--    · metro_stations.lines  → Normalized into the `metro_station_lines` table
--    · bookings.status       → ENUM ('confirmed', 'cancelled', 'completed')
--    · seat_layouts          → One row per seat (Normalized)
--    · payments & feedback   → Dual-FK strategy (booking_id_rail / booking_id_metro)
--                              + CHECK CONSTRAINT to ensure exactly one is non-NULL
--    · Password Storage      → Isolated into the `user_credentials` table;
--                              The Argon2id hash string contains an embedded salt,
--                              Format: $argon2id$v=...$<salt_b64>$<hash_b64>
--  Seed data is loaded separately via skeleton/seed_postgres.py
-- ============================================================


-- ============================================================
--  Extensions
-- ============================================================

CREATE EXTENSION IF NOT EXISTS vector;


-- ============================================================
--  ENUM Types
-- ============================================================

CREATE TYPE service_type_enum       AS ENUM ('normal', 'express');
CREATE TYPE fare_class_enum         AS ENUM ('standard', 'first');
CREATE TYPE booking_status_enum     AS ENUM ('confirmed', 'cancelled', 'completed');
CREATE TYPE payment_status_enum     AS ENUM ('paid', 'refunded', 'pending');
CREATE TYPE payment_method_enum     AS ENUM ('credit_card', 'debit_card', 'ewallet');
CREATE TYPE metro_ticket_type_enum  AS ENUM ('single', 'day_pass');
CREATE TYPE rail_ticket_type_enum   AS ENUM ('single', 'return');
CREATE TYPE delay_reason_enum       AS ENUM ('operator_fault', 'third_party', 'weather');
CREATE TYPE trip_status_enum        AS ENUM ('completed', 'cancelled');


-- ============================================================
--  Metro
-- ============================================================

-- Metro Stations
CREATE TABLE metro_stations (
    station_id                           VARCHAR(10)  PRIMARY KEY,
    name                                 VARCHAR(100) NOT NULL,
    is_interchange_metro                 BOOLEAN      NOT NULL DEFAULT FALSE,
    is_interchange_national_rail         BOOLEAN      NOT NULL DEFAULT FALSE,
    -- FK to national_rail_stations. Since this table is not yet created, it will be added later via ALTER TABLE (see below).
    interchange_national_rail_station_id VARCHAR(10)  NULL
);

-- Metro station lines (Normalized; one station can span multiple lines)
CREATE TABLE metro_station_lines (
    station_id  VARCHAR(10)  NOT NULL
                    REFERENCES metro_stations(station_id) ON DELETE CASCADE,
    line        VARCHAR(10)  NOT NULL,
    PRIMARY KEY (station_id, line)
);

-- Metro Schedules
CREATE TABLE metro_schedules (
    schedule_id            VARCHAR(20)  PRIMARY KEY,
    line                   VARCHAR(10)  NOT NULL,
    direction              VARCHAR(20)  NOT NULL,   -- northbound / southbound / eastbound / westbound
    origin_station_id      VARCHAR(10)  NOT NULL
                               REFERENCES metro_stations(station_id),
    destination_station_id VARCHAR(10)  NOT NULL
                               REFERENCES metro_stations(station_id),
    first_train_time       TIME         NOT NULL,
    last_train_time        TIME         NOT NULL,
    base_fare_usd          NUMERIC(6,2) NOT NULL CHECK (base_fare_usd >= 0),
    per_stop_rate_usd      NUMERIC(6,2) NOT NULL CHECK (per_stop_rate_usd >= 0),
    frequency_min          INTEGER      NOT NULL CHECK (frequency_min > 0),
    stops_json             JSONB        NOT NULL -- Denormalized ordered list of station IDs
);

-- Metro schedule operating days (Normalized to avoid arrays)
CREATE TABLE metro_schedule_days (
    schedule_id  VARCHAR(20)  NOT NULL
                     REFERENCES metro_schedules(schedule_id) ON DELETE CASCADE,
    day_of_week  VARCHAR(3)   NOT NULL
                     CHECK (day_of_week IN ('mon','tue','wed','thu','fri','sat','sun')),
    PRIMARY KEY (schedule_id, day_of_week)
);

-- Metro schedule stops (Normalized; stores stop sequence and travel times)
CREATE TABLE metro_schedule_stops (
    schedule_id                  VARCHAR(20)  NOT NULL
                                     REFERENCES metro_schedules(schedule_id) ON DELETE CASCADE,
    station_id                   VARCHAR(10)  NOT NULL
                                     REFERENCES metro_stations(station_id),
    stop_order                   INTEGER      NOT NULL,  -- 1-based，1 = Start Station
    travel_time_from_origin_min  INTEGER      NOT NULL CHECK (travel_time_from_origin_min >= 0),
    PRIMARY KEY (schedule_id, station_id)
);


-- ============================================================
--  National Rail
-- ============================================================

-- National Rail Stations
CREATE TABLE national_rail_stations (
    station_id                  VARCHAR(10)  PRIMARY KEY,
    name                        VARCHAR(100) NOT NULL,
    is_interchange_national_rail BOOLEAN     NOT NULL DEFAULT FALSE,
    is_interchange_metro        BOOLEAN      NOT NULL DEFAULT FALSE,
    interchange_metro_station_id VARCHAR(10) NULL     -- Semantic reference only; no FK constraint applied (to avoid cross-DB circular dependency)
);

-- Add Foreign Key: metro_stations → national_rail_stations(Since `metro_stations` is created first and `national_rail_stations` later)
ALTER TABLE metro_stations
    ADD CONSTRAINT fk_metro_interchange_nr
        FOREIGN KEY (interchange_national_rail_station_id)
            REFERENCES national_rail_stations(station_id)
            ON DELETE SET NULL;

-- National Rail Schedules
CREATE TABLE national_rail_schedules (
    schedule_id            VARCHAR(20)        PRIMARY KEY,
    line                   VARCHAR(10)        NOT NULL,
    service_type           service_type_enum  NOT NULL,   -- normal / express
    direction              VARCHAR(20)        NOT NULL,
    origin_station_id      VARCHAR(10)        NOT NULL
                               REFERENCES national_rail_stations(station_id),
    destination_station_id VARCHAR(10)        NOT NULL
                               REFERENCES national_rail_stations(station_id),
    first_train_time       TIME               NOT NULL,
    last_train_time        TIME               NOT NULL,
    stops_json             JSONB              NOT NULL, -- Denormalized ordered list of station IDs
    frequency_min          INTEGER            NOT NULL CHECK (frequency_min > 0)
);

-- National Rail schedule operating days
CREATE TABLE national_rail_schedule_days (
    schedule_id  VARCHAR(20)  NOT NULL
                     REFERENCES national_rail_schedules(schedule_id) ON DELETE CASCADE,
    day_of_week  VARCHAR(3)   NOT NULL
                     CHECK (day_of_week IN ('mon','tue','wed','thu','fri','sat','sun')),
    PRIMARY KEY (schedule_id, day_of_week)
);

-- National Rail schedule stops (Includes pass-through stations; is_stop=FALSE indicates express train passes through without stopping)
CREATE TABLE national_rail_stops (
    schedule_id                  VARCHAR(20)  NOT NULL
                                     REFERENCES national_rail_schedules(schedule_id) ON DELETE CASCADE,
    station_id                   VARCHAR(10)  NOT NULL
                                     REFERENCES national_rail_stations(station_id),
    stop_order                   INTEGER      NOT NULL,
    travel_time_from_origin_min  INTEGER      NOT NULL CHECK (travel_time_from_origin_min >= 0),
    is_stop                      BOOLEAN      NOT NULL DEFAULT TRUE,  -- FALSE = 快車通過站
    PRIMARY KEY (schedule_id, station_id)
);

-- National Rail Fares (Two cabin classes per schedule)
CREATE TABLE national_rail_fares (
    schedule_id        VARCHAR(20)       NOT NULL
                           REFERENCES national_rail_schedules(schedule_id) ON DELETE CASCADE,
    fare_class         fare_class_enum   NOT NULL,
    base_fare_usd      NUMERIC(8,2)      NOT NULL CHECK (base_fare_usd >= 0),
    per_stop_rate_usd  NUMERIC(8,2)      NOT NULL CHECK (per_stop_rate_usd >= 0),
    PRIMARY KEY (schedule_id, fare_class)
);


-- ============================================================
-- Seat Layouts（National Rail）
-- ============================================================

-- One record = One seat
-- `seat_id` (e.g., 'A01') is unique within the same schedule but can repeat across different schedules; 
-- therefore, (schedule_id, seat_id) is used as the Composite Primary Key (PK).
CREATE TABLE seat_layouts (
    schedule_id    VARCHAR(20)        NOT NULL
                       REFERENCES national_rail_schedules(schedule_id) ON DELETE CASCADE,
    seat_id        VARCHAR(10)        NOT NULL,   -- e.g. 'A01', 'B12'
    coach          VARCHAR(5)         NOT NULL,   -- e.g. 'A', 'B'
    fare_class     fare_class_enum    NOT NULL,
    row_number     INTEGER            NOT NULL,
    column_letter  VARCHAR(5)         NOT NULL,
    PRIMARY KEY (schedule_id, seat_id)
);


-- ============================================================
-- Users
-- ============================================================

-- User Profiles (Excluding password)
CREATE TABLE users (
    user_id          VARCHAR(10)   PRIMARY KEY,
    full_name        VARCHAR(200)  NOT NULL,
    email            VARCHAR(255)  NOT NULL UNIQUE,
    phone            VARCHAR(30),
    date_of_birth    DATE,
    secret_question  TEXT,
    secret_answer    TEXT,
    registered_at    TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    is_active        BOOLEAN       NOT NULL DEFAULT TRUE
);

-- Isolated Authentication Table (Separation of concerns for security)
-- `password_hash` uses Argon2id; the format natively embeds the salt:
-- $argon2id$v=19$m=65536,t=3,p=4$<salt_base64>$<hash_base64>
-- No additional column required to store the salt
CREATE TABLE user_credentials (
    user_id        VARCHAR(10)  PRIMARY KEY
                       REFERENCES users(user_id) ON DELETE CASCADE,
    password_hash  TEXT         NOT NULL
);


-- ============================================================
-- National Rail Bookings
-- ============================================================

CREATE TABLE bookings (
    booking_id              VARCHAR(20)           PRIMARY KEY,
    user_id                 VARCHAR(10)           NOT NULL
                                REFERENCES users(user_id),
    schedule_id             VARCHAR(20)           NOT NULL
                                REFERENCES national_rail_schedules(schedule_id),
    origin_station_id       VARCHAR(10)           NOT NULL
                                REFERENCES national_rail_stations(station_id),
    destination_station_id  VARCHAR(10)           NOT NULL
                                REFERENCES national_rail_stations(station_id),
    travel_date             DATE                  NOT NULL,
    departure_time          TIME                  NOT NULL,
    ticket_type             rail_ticket_type_enum NOT NULL,
    fare_class              fare_class_enum       NOT NULL,
    coach                   VARCHAR(5)            NOT NULL,
    seat_id                 VARCHAR(10)           NOT NULL,
    stops_travelled         INTEGER,
    amount_usd              NUMERIC(8,2)          NOT NULL,
    status                  booking_status_enum   NOT NULL,
    booked_at               TIMESTAMPTZ           NOT NULL DEFAULT NOW(),
    travelled_at            TIMESTAMPTZ,
    -- Composite FK: The seat must belong to the exact same schedule.
    FOREIGN KEY (schedule_id, seat_id)
        REFERENCES seat_layouts(schedule_id, seat_id)
);


-- ============================================================
-- Metro Travel History
-- ============================================================

CREATE TABLE metro_travel_history (
    trip_id                 VARCHAR(20)            PRIMARY KEY,
    user_id                 VARCHAR(10)            NOT NULL
                                REFERENCES users(user_id),
    schedule_id             VARCHAR(20)            NOT NULL
                                REFERENCES metro_schedules(schedule_id),
    origin_station_id       VARCHAR(10)            NOT NULL
                                REFERENCES metro_stations(station_id),
    destination_station_id  VARCHAR(10)            NOT NULL
                                REFERENCES metro_stations(station_id),
    travel_date             DATE                   NOT NULL,
    ticket_type             metro_ticket_type_enum NOT NULL,
    -- If ticket_type = 'day_pass', `day_pass_ref` points to the primary record of the same day where amount_usd > 0.
    -- · Derivative trips ($0) will have a valid `day_pass_ref`.
    -- · The primary purchase record's `day_pass_ref` remains NULL.
    day_pass_ref            VARCHAR(20)
                                REFERENCES metro_travel_history(trip_id) ON DELETE SET NULL,
    stops_travelled         INTEGER,               -- `single_ticket` has a value; `day_pass` is NULL.
    amount_usd              NUMERIC(8,2)           NOT NULL,
    status                  trip_status_enum       NOT NULL,
    purchased_at            TIMESTAMPTZ,           -- Derivative trips under a day_pass do not have a purchase timestamp.
    travelled_at            TIMESTAMPTZ
);


-- ============================================================
--  Payments
--  booking_id_rail / booking_id_metro exactly one must be non-NULL (XOR constraint).
-- ============================================================

CREATE TABLE payments (
    payment_id        VARCHAR(20)           PRIMARY KEY,
    booking_id_rail   VARCHAR(20)           NULL
                          REFERENCES bookings(booking_id) ON DELETE SET NULL,
    booking_id_metro  VARCHAR(20)           NULL
                          REFERENCES metro_travel_history(trip_id) ON DELETE SET NULL,
    amount_usd        NUMERIC(8,2)          NOT NULL,
    method            payment_method_enum   NOT NULL,
    status            payment_status_enum   NOT NULL,
    paid_at           TIMESTAMPTZ           NOT NULL,
    CONSTRAINT chk_payment_booking_xor CHECK (
        (booking_id_rail  IS NOT NULL AND booking_id_metro IS NULL) OR
        (booking_id_rail  IS NULL     AND booking_id_metro IS NOT NULL)
    )
);


-- ============================================================
--  Feedback
--  booking_id_rail / booking_id_metro exactly one must be non-NULL (XOR constraint).
-- ============================================================

CREATE TABLE feedback (
    feedback_id       VARCHAR(20)  PRIMARY KEY,
    booking_id_rail   VARCHAR(20)  NULL
                          REFERENCES bookings(booking_id) ON DELETE SET NULL,
    booking_id_metro  VARCHAR(20)  NULL
                          REFERENCES metro_travel_history(trip_id) ON DELETE SET NULL,
    user_id           VARCHAR(10)  NOT NULL
                          REFERENCES users(user_id),
    rating            INTEGER      NOT NULL CHECK (rating BETWEEN 1 AND 5),
    comment           TEXT,
    submitted_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_feedback_booking_xor CHECK (
        (booking_id_rail  IS NOT NULL AND booking_id_metro IS NULL) OR
        (booking_id_rail  IS NULL     AND booking_id_metro IS NOT NULL)
    )
);

-- ============================================================
--  Service Delays (For Compensation Verification)
-- ============================================================

CREATE TABLE service_delays (
    delay_id          SERIAL        PRIMARY KEY,
    schedule_id       VARCHAR(20)   NOT NULL, -- Works for both NR and Metro
    travel_date       DATE          NOT NULL,
    delay_minutes     INTEGER       NOT NULL CHECK (delay_minutes >= 0),
    reason_category   delay_reason_enum NOT NULL,
    description       TEXT,
    created_at        TIMESTAMPTZ   DEFAULT NOW(),
    UNIQUE (schedule_id, travel_date)
);

-- ============================================================
--  Policy Documents Vector Table (RAG)
--  This section is populated via `skeleton/seed_vectors.py`; do not modify column definitions.
-- ============================================================

CREATE TABLE IF NOT EXISTS policy_documents (
    id           SERIAL        PRIMARY KEY,
    title        VARCHAR(200)  NOT NULL,
    category     VARCHAR(50)   NOT NULL,   -- 'refund' / 'booking' / 'conduct' / ...
    content      TEXT          NOT NULL,
    -- Ollama `nomic-embed-text` → 768 dimensions
    -- If switching to Gemini, change to `vector(3072)` and rebuild the database.
    embedding    vector(768),
    source_file  VARCHAR(200),
    created_at   TIMESTAMPTZ   DEFAULT NOW()
);


-- ============================================================
--  Indexes（Performance Optimization for Common Queries）
-- ============================================================

-- Bookings: Query by user, schedule + date, or status
CREATE INDEX idx_bookings_user_id       ON bookings(user_id);
CREATE INDEX idx_bookings_schedule_date ON bookings(schedule_id, travel_date);
CREATE INDEX idx_bookings_status        ON bookings(status);

-- Metro History: Query by user, or schedule + date
CREATE INDEX idx_metro_hist_user_id     ON metro_travel_history(user_id);
CREATE INDEX idx_metro_hist_sched_date  ON metro_travel_history(schedule_id, travel_date);

-- Payments: Quickly locate payment records for a specific order
CREATE INDEX idx_payments_rail   ON payments(booking_id_rail)
    WHERE booking_id_rail  IS NOT NULL;
CREATE INDEX idx_payments_metro  ON payments(booking_id_metro)
    WHERE booking_id_metro IS NOT NULL;

-- Feedbacks/Reviews: Query by user
CREATE INDEX idx_feedback_user_id ON feedback(user_id);
-- Partial Indexes for XOR relationships: Exclude NULLs to save space and accelerate queries
CREATE INDEX idx_feedback_rail ON feedback(booking_id_rail) WHERE booking_id_rail IS NOT NULL;
CREATE INDEX idx_feedback_metro ON feedback(booking_id_metro) WHERE booking_id_metro IS NOT NULL;
CREATE INDEX idx_payments_status ON payments(status);

-- Metro Schedules: Query by line
CREATE INDEX idx_metro_sched_line ON metro_schedules(line);

-- National Rail Schedules: Query by line or service type
CREATE INDEX idx_nr_sched_line_type ON national_rail_schedules(line, service_type);

-- Policy Documents: pgvector HNSW Approximate Nearest Neighbor (ANN) index (using cosine distance)
CREATE INDEX idx_policy_embedding
    ON policy_documents
    USING hnsw (embedding vector_cosine_ops);
    