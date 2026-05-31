-- ============================================================
--  TransitFlow — PostgreSQL 15 Complete Schema
--  LLM Provider : Ollama (embedding dimension: 768)
--  Design Decision Summary:
--    · metro_stations.lines  → Normalized into metro_station_lines table
--    · bookings.status       → ENUM (confirmed / cancelled / completed)
--    · seat_layouts          → One row per seat (normalized)
--    · payments & feedback   → Dual FK scheme (booking_id_rail / booking_id_metro)
--                              + CHECK CONSTRAINT ensuring exactly one is NOT NULL
--    · Password Storage      → Independent user_credentials table;
--                              Argon2id hash string with embedded salt,
--                              Format: $argon2id$v=...$<salt_b64>$<hash_b64>
--  Seed data is loaded separately by skeleton/seed_postgres.py
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
    -- FK to national_rail_stations; added via ALTER TABLE below because the table isn't created yet
    interchange_national_rail_station_id VARCHAR(10)  NULL
);

-- Metro station lines (A station can belong to multiple lines, normalized)
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
    frequency_min          INTEGER      NOT NULL CHECK (frequency_min > 0)
);

-- Metro schedule operating days (Normalized to avoid arrays)
CREATE TABLE metro_schedule_days (
    schedule_id  VARCHAR(20)  NOT NULL
                     REFERENCES metro_schedules(schedule_id) ON DELETE CASCADE,
    day_of_week  VARCHAR(3)   NOT NULL
                     CHECK (day_of_week IN ('mon','tue','wed','thu','fri','sat','sun')),
    PRIMARY KEY (schedule_id, day_of_week)
);

-- Metro schedule stops (Normalized, stores stop order and travel time)
CREATE TABLE metro_schedule_stops (
    schedule_id                  VARCHAR(20)  NOT NULL
                                     REFERENCES metro_schedules(schedule_id) ON DELETE CASCADE,
    station_id                   VARCHAR(10)  NOT NULL
                                     REFERENCES metro_stations(station_id),
    stop_order                   INTEGER      NOT NULL,  -- 1-based, 1 = origin
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
    interchange_metro_station_id VARCHAR(10) NULL     -- Semantic reference, no FK added (to avoid circular dependencies)
);

-- Adding Foreign Key from metro_stations to national_rail_stations (metro_stations created first)
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
    frequency_min          INTEGER            NOT NULL CHECK (frequency_min > 0)
);

-- National Rail Schedule Days
CREATE TABLE national_rail_schedule_days (
    schedule_id  VARCHAR(20)  NOT NULL
                     REFERENCES national_rail_schedules(schedule_id) ON DELETE CASCADE,
    day_of_week  VARCHAR(3)   NOT NULL
                     CHECK (day_of_week IN ('mon','tue','wed','thu','fri','sat','sun')),
    PRIMARY KEY (schedule_id, day_of_week)
);

-- National Rail Stops (Includes pass-through stations; is_stop=FALSE means express train passes without stopping)
CREATE TABLE national_rail_stops (
    schedule_id                  VARCHAR(20)  NOT NULL
                                     REFERENCES national_rail_schedules(schedule_id) ON DELETE CASCADE,
    station_id                   VARCHAR(10)  NOT NULL
                                     REFERENCES national_rail_stations(station_id),
    stop_order                   INTEGER      NOT NULL,
    travel_time_from_origin_min  INTEGER      NOT NULL CHECK (travel_time_from_origin_min >= 0),
    is_stop                      BOOLEAN      NOT NULL DEFAULT TRUE,  -- FALSE = express pass-through station
    PRIMARY KEY (schedule_id, station_id)
);

-- National Rail Fares (Two classes per schedule)
CREATE TABLE national_rail_fares (
    schedule_id        VARCHAR(20)       NOT NULL
                           REFERENCES national_rail_schedules(schedule_id) ON DELETE CASCADE,
    fare_class         fare_class_enum   NOT NULL,
    base_fare_usd      NUMERIC(8,2)      NOT NULL CHECK (base_fare_usd >= 0),
    per_stop_rate_usd  NUMERIC(8,2)      NOT NULL CHECK (per_stop_rate_usd >= 0),
    PRIMARY KEY (schedule_id, fare_class)
);


-- ============================================================
--  Seat Layouts (National Rail)
-- ============================================================

-- One record = one seat
-- seat_id (e.g., 'A01') is unique within a schedule, but can repeat across schedules; thus (schedule_id, seat_id) is the PK
CREATE TABLE seat_layouts (
    schedule_id    VARCHAR(20)        NOT NULL
                       REFERENCES national_rail_schedules(schedule_id) ON DELETE CASCADE,
    seat_id        VARCHAR(10)        NOT NULL,   -- e.g., 'A01', 'B12'
    coach          VARCHAR(5)         NOT NULL,   -- e.g., 'A', 'B'
    fare_class     fare_class_enum    NOT NULL,
    row_number     INTEGER            NOT NULL,
    column_letter  VARCHAR(5)         NOT NULL,
    PRIMARY KEY (schedule_id, seat_id)
);


-- ============================================================
--  Users
-- ============================================================

-- User Profile (Excluding passwords)
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

-- Independent Authentication Table (Security separation)
-- password_hash uses Argon2id with embedded salt:
--   $argon2id$v=19$m=65536,t=3,p=4$<salt_base64>$<hash_base64>
-- No extra column needed for salt
CREATE TABLE user_credentials (
    user_id        VARCHAR(10)  PRIMARY KEY
                       REFERENCES users(user_id) ON DELETE CASCADE,
    password_hash  TEXT         NOT NULL
);


-- ============================================================
--  Bookings
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
    -- Composite FK: Seat must belong to the same schedule
    FOREIGN KEY (schedule_id, seat_id)
        REFERENCES seat_layouts(schedule_id, seat_id)
);


-- ============================================================
--  Metro Travel History
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
    -- If ticket_type = 'day_pass', day_pass_ref points to the record on the same day where amount_usd > 0
    -- Derived trips ($0) will have a day_pass_ref; the primary purchase record's day_pass_ref is NULL
    day_pass_ref            VARCHAR(20)
                                REFERENCES metro_travel_history(trip_id) ON DELETE SET NULL,
    stops_travelled         INTEGER,               -- Value present for single ticket; NULL for day_pass
    amount_usd              NUMERIC(8,2)           NOT NULL,
    status                  trip_status_enum       NOT NULL,
    purchased_at            TIMESTAMPTZ,           -- No purchase time for day_pass derived trips
    travelled_at            TIMESTAMPTZ
);


-- ============================================================
--  Payments
--  booking_id_rail / booking_id_metro: exactly one must be NOT NULL (XOR)
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
--  booking_id_rail / booking_id_metro: exactly one must be NOT NULL (XOR)
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
--  Policy Documents (RAG)
--  This section is populated by skeleton/seed_vectors.py; do not modify field definitions
-- ============================================================

CREATE TABLE IF NOT EXISTS policy_documents (
    id           SERIAL        PRIMARY KEY,
    title        VARCHAR(200)  NOT NULL,
    category     VARCHAR(50)   NOT NULL,   -- 'refund' / 'booking' / 'conduct' / etc.
    content      TEXT          NOT NULL,
    -- Ollama nomic-embed-text → 768 dimensions
    -- If switching to Gemini, change to vector(3072) and rebuild the database
    embedding    vector(768),
    source_file  VARCHAR(200),
    created_at   TIMESTAMPTZ   DEFAULT NOW()
);


-- ============================================================
--  Indexes (Enhance performance for common queries)
-- ============================================================

-- Bookings: Query by user, schedule+date, status
CREATE INDEX idx_bookings_user_id       ON bookings(user_id);
CREATE INDEX idx_bookings_schedule_date ON bookings(schedule_id, travel_date);
CREATE INDEX idx_bookings_status        ON bookings(status);

-- Metro History: Query by user, schedule+date
CREATE INDEX idx_metro_hist_user_id     ON metro_travel_history(user_id);
CREATE INDEX idx_metro_hist_sched_date  ON metro_travel_history(schedule_id, travel_date);

-- Payments: Quickly find payment records for a specific booking
CREATE INDEX idx_payments_rail   ON payments(booking_id_rail)
    WHERE booking_id_rail  IS NOT NULL;
CREATE INDEX idx_payments_metro  ON payments(booking_id_metro)
    WHERE booking_id_metro IS NOT NULL;

-- Feedback: Query by user
CREATE INDEX idx_feedback_user_id ON feedback(user_id);
-- Partial indexes for XOR relationships; excludes NULL values to save space and speed up queries
CREATE INDEX idx_feedback_rail ON feedback(booking_id_rail) WHERE booking_id_rail IS NOT NULL;
CREATE INDEX idx_feedback_metro ON feedback(booking_id_metro) WHERE booking_id_metro IS NOT NULL;
CREATE INDEX idx_payments_status ON payments(status);

-- Metro Schedules: Query by line
CREATE INDEX idx_metro_sched_line ON metro_schedules(line);

-- National Rail Schedules: Query by line and service type
CREATE INDEX idx_nr_sched_line_type ON national_rail_schedules(line, service_type);

-- Policy Documents: pgvector HNSW Approximate Nearest Neighbor index (cosine distance)
CREATE INDEX idx_policy_embedding
    ON policy_documents
    USING hnsw (embedding vector_cosine_ops);
