# Task 6 Optional Extension — Disruption and Delay Impact Recording System

This document outlines the design, implementation, and testing of the Disruption and Delay Impact Recording System (Task 6), which secures optional extension/bonus marks.

## 1. Motivation
In real-world transit systems, delays and disruptions are dynamic. Passive scheduling data is insufficient. This extension bridges our relational database (PostgreSQL) and graph database (Neo4j) to:
- Log historical and active disruption events with causes for auditing.
- Dynamically recalculate pathfinding weights (travel times) in Neo4j so that routing queries (`find_route`) automatically avoid or route around disrupted stations in real-time.

---

## 2. File Modifcations and Comment Markers
All files modified for this task contain the `# TASK 6 EXTENSION` comment marker to satisfy rubric requirements:
1. **`databases/relational/schema.sql`**: Added `delay_records` table structure.
2. **`databases/relational/queries.py`**: Added `report_delay_record` and `query_active_delays` Python functions.
3. **`skeleton/seed_neo4j.py`**: Added `base_travel_time_min` to relationships, `delay_minutes` to nodes, and initialized them.
4. **`databases/graph/queries.py`**: Added `update_neo4j_station_delay` to propagate Postgres delay inputs to Neo4j, recalculate relationship weights, and updated shortest/cheapest routing.
5. **`skeleton/agent.py`**: Integrated `report_disruption` and `get_active_delays` tools into LLM schemas.

---

## 3. Schema Changes

### 3.1 PostgreSQL
```sql
CREATE TABLE delay_records (
    delay_id         SERIAL       PRIMARY KEY,
    station_id       VARCHAR(10)  NOT NULL, -- Polymorphic reference (MSxx or NRxx)
    line             VARCHAR(10)  NULL,
    delay_minutes    INTEGER      NOT NULL CHECK (delay_minutes >= 0),
    disruption_cause TEXT         NOT NULL,
    reported_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    is_active        BOOLEAN      NOT NULL DEFAULT TRUE
);
```

### 3.2 Neo4j Graph
- **Station Nodes (`:MetroStation`, `:NationalRailStation`)**: Added `delay_minutes` property (default `0`).
- **Relationships (`:METRO_LINK`, `:RAIL_LINK`, `:INTERCHANGE_TO`)**:
  - Added `base_travel_time_min` (baseline time).
  - Added `travel_time_min` (dynamic, updated as `base_travel_time_min + stationA.delay_minutes + stationB.delay_minutes`).

---

## 4. Query Implementation

### 4.1 PostgreSQL Logging
```sql
INSERT INTO delay_records (station_id, line, delay_minutes, disruption_cause)
VALUES ($1, $2, $3, $4)
RETURNING delay_id;
```

### 4.2 Neo4j Delay Propagation
```cypher
MATCH (s {station_id: $station_id})
SET s.delay_minutes = $delay_minutes
WITH s
MATCH (s)-[r:METRO_LINK|RAIL_LINK|INTERCHANGE_TO]-(other)
SET r.travel_time_min = coalesce(r.base_travel_time_min, r.travel_time_min) 
                        + $delay_minutes 
                        + coalesce(other.delay_minutes, 0)
```

---

## 5. Verification & Testing Evidence
The system was verified using the automated test suite `scratch/test_hardening.py` with the following results:
- **Baseline time for NR03**: 15 mins.
- **Reporting delay of 15 mins**: Node updated to `15`, relationship `travel_time_min` automatically propagated to `30`.
- **Clearing delay**: Node reset to `0`, relationship `travel_time_min` automatically restored to baseline `15`.
- **Integration**: The Gradio Agent can automatically call the `report_disruption` tool and route around delayed segments.
