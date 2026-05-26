-- ============================================================
--  TransitFlow — PostgreSQL 15 完整 Schema
--  LLM Provider : Ollama (embedding dimension: 768)
--  設計決策摘要：
--    · metro_stations.lines  → 正規化為 metro_station_lines 表
--    · bookings.status       → ENUM (confirmed / cancelled / completed)
--    · seat_layouts          → 每座位一行（正規化）
--    · payments & feedback   → 雙 FK 方案（booking_id_rail / booking_id_metro）
--                              + CHECK CONSTRAINT 確保恰好一個非 NULL
--    · 密碼儲存              → 獨立 user_credentials 表；
--                              Argon2id hash 字串已內嵌 salt，
--                              格式: $argon2id$v=...$<salt_b64>$<hash_b64>
--  Seed 資料由 skeleton/seed_postgres.py 另外載入
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
--  地鐵 Metro
-- ============================================================

-- 地鐵站
CREATE TABLE metro_stations (
    station_id                           VARCHAR(10)  PRIMARY KEY,
    name                                 VARCHAR(100) NOT NULL,
    is_interchange_metro                 BOOLEAN      NOT NULL DEFAULT FALSE,
    is_interchange_national_rail         BOOLEAN      NOT NULL DEFAULT FALSE,
    -- FK 到 national_rail_stations，因為該表尚未建立，以 ALTER TABLE 補加（見下方）
    interchange_national_rail_station_id VARCHAR(10)  NULL
);

-- 地鐵站所屬路線（一站可跨多條線，正規化）
CREATE TABLE metro_station_lines (
    station_id  VARCHAR(10)  NOT NULL
                    REFERENCES metro_stations(station_id) ON DELETE CASCADE,
    line        VARCHAR(10)  NOT NULL,
    PRIMARY KEY (station_id, line)
);

-- 地鐵班表
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

-- 地鐵班表運行日（正規化，避免陣列）
CREATE TABLE metro_schedule_days (
    schedule_id  VARCHAR(20)  NOT NULL
                     REFERENCES metro_schedules(schedule_id) ON DELETE CASCADE,
    day_of_week  VARCHAR(3)   NOT NULL
                     CHECK (day_of_week IN ('mon','tue','wed','thu','fri','sat','sun')),
    PRIMARY KEY (schedule_id, day_of_week)
);

-- 地鐵班表停靠站（正規化，儲存停靠順序與行駛時間）
CREATE TABLE metro_schedule_stops (
    schedule_id                  VARCHAR(20)  NOT NULL
                                     REFERENCES metro_schedules(schedule_id) ON DELETE CASCADE,
    station_id                   VARCHAR(10)  NOT NULL
                                     REFERENCES metro_stations(station_id),
    stop_order                   INTEGER      NOT NULL,  -- 1-based，1 = 起點
    travel_time_from_origin_min  INTEGER      NOT NULL CHECK (travel_time_from_origin_min >= 0),
    PRIMARY KEY (schedule_id, station_id)
);


-- ============================================================
--  國鐵 National Rail
-- ============================================================

-- 國鐵站
CREATE TABLE national_rail_stations (
    station_id                  VARCHAR(10)  PRIMARY KEY,
    name                        VARCHAR(100) NOT NULL,
    is_interchange_national_rail BOOLEAN     NOT NULL DEFAULT FALSE,
    is_interchange_metro        BOOLEAN      NOT NULL DEFAULT FALSE,
    interchange_metro_station_id VARCHAR(10) NULL     -- 語意參考，不加 FK（避免跨 DB 循環）
);

-- 現在補上地鐵站 → 國鐵站的外鍵（metro_stations 先建，national_rail_stations 後建）
ALTER TABLE metro_stations
    ADD CONSTRAINT fk_metro_interchange_nr
        FOREIGN KEY (interchange_national_rail_station_id)
            REFERENCES national_rail_stations(station_id)
            ON DELETE SET NULL;

-- 國鐵班表
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

-- 國鐵班表運行日
CREATE TABLE national_rail_schedule_days (
    schedule_id  VARCHAR(20)  NOT NULL
                     REFERENCES national_rail_schedules(schedule_id) ON DELETE CASCADE,
    day_of_week  VARCHAR(3)   NOT NULL
                     CHECK (day_of_week IN ('mon','tue','wed','thu','fri','sat','sun')),
    PRIMARY KEY (schedule_id, day_of_week)
);

-- 國鐵停靠站（含 pass-through 站，is_stop=FALSE 代表特快通過但不停靠）
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

-- 國鐵票價（每班次兩個艙等）
CREATE TABLE national_rail_fares (
    schedule_id        VARCHAR(20)       NOT NULL
                           REFERENCES national_rail_schedules(schedule_id) ON DELETE CASCADE,
    fare_class         fare_class_enum   NOT NULL,
    base_fare_usd      NUMERIC(8,2)      NOT NULL CHECK (base_fare_usd >= 0),
    per_stop_rate_usd  NUMERIC(8,2)      NOT NULL CHECK (per_stop_rate_usd >= 0),
    PRIMARY KEY (schedule_id, fare_class)
);


-- ============================================================
--  座位配置 Seat Layouts（國鐵）
-- ============================================================

-- 每一筆 = 一個座位
-- seat_id (e.g. 'A01') 在同一班次內唯一，但不同班次可重複，故以 (schedule_id, seat_id) 為 PK
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
--  使用者 Users
-- ============================================================

-- 使用者個人資料（不含密碼）
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

-- 獨立認證表（安全性分離）
-- password_hash 使用 Argon2id，格式已內嵌 salt：
--   $argon2id$v=19$m=65536,t=3,p=4$<salt_base64>$<hash_base64>
-- 不需額外欄位儲存 salt
CREATE TABLE user_credentials (
    user_id        VARCHAR(10)  PRIMARY KEY
                       REFERENCES users(user_id) ON DELETE CASCADE,
    password_hash  TEXT         NOT NULL
);


-- ============================================================
--  國鐵訂票 Bookings
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
    -- 複合 FK：座位必須屬於同一班次
    FOREIGN KEY (schedule_id, seat_id)
        REFERENCES seat_layouts(schedule_id, seat_id)
);


-- ============================================================
--  地鐵乘車歷史 Metro Travel History
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
    -- 若 ticket_type = 'day_pass'，day_pass_ref 指向同日 amount_usd > 0 的那筆紀錄
    -- 衍生行程（$0）會有 day_pass_ref；主購票紀錄的 day_pass_ref 為 NULL
    day_pass_ref            VARCHAR(20)
                                REFERENCES metro_travel_history(trip_id) ON DELETE SET NULL,
    stops_travelled         INTEGER,               -- single ticket 有值；day_pass 為 NULL
    amount_usd              NUMERIC(8,2)           NOT NULL,
    status                  trip_status_enum       NOT NULL,
    purchased_at            TIMESTAMPTZ,           -- day_pass 衍生行程無購買時間
    travelled_at            TIMESTAMPTZ
);


-- ============================================================
--  付款 Payments
--  booking_id_rail / booking_id_metro 恰好一個非 NULL（XOR）
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
--  乘客評價 Feedback
--  booking_id_rail / booking_id_metro 恰好一個非 NULL（XOR）
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
--  政策文件向量表 Policy Documents（RAG）
--  此區塊由 skeleton/seed_vectors.py 負責填入資料，勿修改欄位定義
-- ============================================================

CREATE TABLE IF NOT EXISTS policy_documents (
    id           SERIAL        PRIMARY KEY,
    title        VARCHAR(200)  NOT NULL,
    category     VARCHAR(50)   NOT NULL,   -- 'refund' / 'booking' / 'conduct' / ...
    content      TEXT          NOT NULL,
    -- Ollama nomic-embed-text → 768 維
    -- 若切換 Gemini，請改為 vector(3072) 並重建資料庫
    embedding    vector(768),
    source_file  VARCHAR(200),
    created_at   TIMESTAMPTZ   DEFAULT NOW()
);


-- ============================================================
--  Indexes（提升常用查詢效能）
-- ============================================================

-- 訂票：依使用者、班次+日期、狀態查詢
CREATE INDEX idx_bookings_user_id       ON bookings(user_id);
CREATE INDEX idx_bookings_schedule_date ON bookings(schedule_id, travel_date);
CREATE INDEX idx_bookings_status        ON bookings(status);

-- 地鐵歷史：依使用者、班次+日期查詢
CREATE INDEX idx_metro_hist_user_id     ON metro_travel_history(user_id);
CREATE INDEX idx_metro_hist_sched_date  ON metro_travel_history(schedule_id, travel_date);

-- 付款：快速找出某訂單的付款紀錄
CREATE INDEX idx_payments_rail   ON payments(booking_id_rail)
    WHERE booking_id_rail  IS NOT NULL;
CREATE INDEX idx_payments_metro  ON payments(booking_id_metro)
    WHERE booking_id_metro IS NOT NULL;

-- 評價：依使用者查詢
CREATE INDEX idx_feedback_user_id ON feedback(user_id);
-- 針對 XOR 關係的部分索引，排除空值以節省空間並加速查詢
CREATE INDEX idx_feedback_rail ON feedback(booking_id_rail) WHERE booking_id_rail IS NOT NULL;
CREATE INDEX idx_feedback_metro ON feedback(booking_id_metro) WHERE booking_id_metro IS NOT NULL;
CREATE INDEX idx_payments_status ON payments(status);

-- 地鐵班表：依路線查詢
CREATE INDEX idx_metro_sched_line ON metro_schedules(line);

-- 國鐵班表：依路線、服務類型查詢
CREATE INDEX idx_nr_sched_line_type ON national_rail_schedules(line, service_type);

-- 政策文件：pgvector HNSW 近似最近鄰索引（cosine distance）
CREATE INDEX idx_policy_embedding
    ON policy_documents
    USING hnsw (embedding vector_cosine_ops);
