"""
Seed PostgreSQL with all TransitFlow mock data from train-mock-data/.

Usage:
    python skeleton/seed_postgres.py

Run AFTER docker-compose up -d.
You must first design and create your tables in databases/relational/schema.sql.
Safe to re-run: implement your inserts with ON CONFLICT DO NOTHING.
"""

import json
import os
import sys

import psycopg2
from psycopg2.extras import execute_values

# ── resolve paths ────────────────────────────────────────────────────────────
SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
DATA_DIR    = os.path.join(PROJECT_DIR, "train-mock-data")

sys.path.insert(0, PROJECT_DIR)
from skeleton import config as cfg


def load(filename):
    with open(os.path.join(DATA_DIR, filename), encoding="utf-8") as f:
        return json.load(f)


def connect():
    return psycopg2.connect(
        host=cfg.PG_HOST,
        port=cfg.PG_PORT,
        dbname=cfg.PG_DB,
        user=cfg.PG_USER,
        password=cfg.PG_PASSWORD,
    )


def insert_many(cur, table, columns, rows):
    """Bulk insert with ON CONFLICT DO NOTHING. Returns row count inserted."""
    if not rows:
        return 0
    sql = (
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES %s "
        f"ON CONFLICT DO NOTHING"
    )
    execute_values(cur, sql, rows)
    return cur.rowcount


# ── seeders ──────────────────────────────────────────────────────────────────

def seed_metro_stations(cur):
    data = load("metro_stations.json")
    print(f"  Metro stations: seeding {len(data)} stations...")
    for s in data:
        cur.execute(
            """
            INSERT INTO metro_stations (
                station_id, name, is_interchange_metro, is_interchange_national_rail, interchange_national_rail_station_id
            ) VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (station_id) DO NOTHING
            """,
            (
                s["station_id"],
                s["name"],
                s["is_interchange_metro"],
                s["is_interchange_national_rail"],
                s["interchange_national_rail_station_id"]
            )
        )
        for line in s["lines"]:
            cur.execute(
                """
                INSERT INTO metro_station_lines (station_id, line)
                VALUES (%s, %s)
                ON CONFLICT (station_id, line) DO NOTHING
                """,
                (s["station_id"], line)
            )


def seed_national_rail_stations(cur):
    data = load("national_rail_stations.json")
    print(f"  National rail stations: seeding {len(data)} stations...")
    for s in data:
        cur.execute(
            """
            INSERT INTO national_rail_stations (
                station_id, name, is_interchange_national_rail, is_interchange_metro, interchange_metro_station_id
            ) VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (station_id) DO NOTHING
            """,
            (
                s["station_id"],
                s["name"],
                s["is_interchange_national_rail"],
                s["is_interchange_metro"],
                s["interchange_metro_station_id"]
            )
        )


def seed_metro_schedules(cur):
    data = load("metro_schedules.json")
    print(f"  Metro schedules: seeding {len(data)} schedules...")
    for sch in data:
        cur.execute(
            """
            INSERT INTO metro_schedules (
                schedule_id, line, direction, origin_station_id, destination_station_id,
                first_train_time, last_train_time, base_fare_usd, per_stop_rate_usd, frequency_min
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (schedule_id) DO NOTHING
            """,
            (
                sch["schedule_id"],
                sch["line"],
                sch["direction"],
                sch["origin_station_id"],
                sch["destination_station_id"],
                sch["first_train_time"],
                sch["last_train_time"],
                sch["base_fare_usd"],
                sch["per_stop_rate_usd"],
                sch["frequency_min"]
            )
        )
        for day in sch["operates_on"]:
            cur.execute(
                """
                INSERT INTO metro_schedule_days (schedule_id, day_of_week)
                VALUES (%s, %s)
                ON CONFLICT (schedule_id, day_of_week) DO NOTHING
                """,
                (sch["schedule_id"], day)
            )
        for idx, station_id in enumerate(sch["stops_in_order"]):
            stop_order = idx + 1
            travel_time = sch["travel_time_from_origin_min"][station_id]
            cur.execute(
                """
                INSERT INTO metro_schedule_stops (schedule_id, station_id, stop_order, travel_time_from_origin_min)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (schedule_id, station_id) DO NOTHING
                """,
                (sch["schedule_id"], station_id, stop_order, travel_time)
            )


def seed_national_rail_schedules(cur):
    data = load("national_rail_schedules.json")
    print(f"  National rail schedules: seeding {len(data)} schedules...")
    for sch in data:
        cur.execute(
            """
            INSERT INTO national_rail_schedules (
                schedule_id, line, service_type, direction, origin_station_id, destination_station_id,
                first_train_time, last_train_time, frequency_min
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (schedule_id) DO NOTHING
            """,
            (
                sch["schedule_id"],
                sch["line"],
                sch["service_type"],
                sch["direction"],
                sch["origin_station_id"],
                sch["destination_station_id"],
                sch["first_train_time"],
                sch["last_train_time"],
                sch["frequency_min"]
            )
        )
        for day in sch["operates_on"]:
            cur.execute(
                """
                INSERT INTO national_rail_schedule_days (schedule_id, day_of_week)
                VALUES (%s, %s)
                ON CONFLICT (schedule_id, day_of_week) DO NOTHING
                """,
                (sch["schedule_id"], day)
            )
        for idx, station_id in enumerate(sch["stops_in_order"]):
            stop_order = idx + 1
            travel_time = sch["travel_time_from_origin_min"][station_id]
            cur.execute(
                """
                INSERT INTO national_rail_stops (schedule_id, station_id, stop_order, travel_time_from_origin_min, is_stop)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (schedule_id, station_id) DO NOTHING
                """,
                (sch["schedule_id"], station_id, stop_order, travel_time, True)
            )
        if "passed_through_stations" in sch:
            counterpart_id = None
            if sch["schedule_id"] == "NR_SCH05": counterpart_id = "NR_SCH01"
            elif sch["schedule_id"] == "NR_SCH06": counterpart_id = "NR_SCH02"
            elif sch["schedule_id"] == "NR_SCH07": counterpart_id = "NR_SCH03"
            elif sch["schedule_id"] == "NR_SCH08": counterpart_id = "NR_SCH04"
            
            counterpart = next((x for x in data if x["schedule_id"] == counterpart_id), None)
            if counterpart:
                counterpart_stops = counterpart["stops_in_order"]
                for p_station in sch["passed_through_stations"]:
                    try:
                        stop_order = counterpart_stops.index(p_station) + 1
                        normal_p_time = counterpart["travel_time_from_origin_min"][p_station]
                        normal_dest = counterpart["destination_station_id"]
                        normal_total_time = counterpart["travel_time_from_origin_min"][normal_dest]
                        
                        express_dest = sch["destination_station_id"]
                        express_total_time = sch["travel_time_from_origin_min"][express_dest]
                        
                        travel_time = int(round(normal_p_time * (express_total_time / normal_total_time)))
                    except Exception:
                        stop_order = 99
                        travel_time = 0
                    
                    cur.execute(
                        """
                        INSERT INTO national_rail_stops (schedule_id, station_id, stop_order, travel_time_from_origin_min, is_stop)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (schedule_id, station_id) DO NOTHING
                        """,
                        (sch["schedule_id"], p_station, stop_order, travel_time, False)
                    )
                    
        for fare_class, fare_info in sch["fare_classes"].items():
            cur.execute(
                """
                INSERT INTO national_rail_fares (schedule_id, fare_class, base_fare_usd, per_stop_rate_usd)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (schedule_id, fare_class) DO NOTHING
                """,
                (sch["schedule_id"], fare_class, fare_info["base_fare_usd"], fare_info["per_stop_rate_usd"])
            )


def seed_seat_layouts(cur):
    data = load("national_rail_seat_layouts.json")
    print(f"  Seat layouts: seeding standard/first seats...")
    layout_templates = {}
    
    for entry in data:
        sch_id = entry["schedule_id"]
        coaches = entry["coaches"]
        
        if sch_id in ("NR_SCH01", "NR_SCH03"):
            layout_templates[sch_id] = coaches
            
        for coach_info in coaches:
            coach = coach_info["coach"]
            fare_class = coach_info["fare_class"]
            for seat in coach_info["seats"]:
                cur.execute(
                    """
                    INSERT INTO seat_layouts (schedule_id, seat_id, coach, fare_class, row_number, column_letter)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (schedule_id, seat_id) DO NOTHING
                    """,
                    (sch_id, seat["seat_id"], coach, fare_class, seat["row"], seat["column"])
                )
                
    mapping = {
        "NR_SCH05": "NR_SCH01",
        "NR_SCH06": "NR_SCH01",
        "NR_SCH07": "NR_SCH03",
        "NR_SCH08": "NR_SCH03",
    }
    
    for target_sch, src_sch in mapping.items():
        if src_sch in layout_templates:
            coaches = layout_templates[src_sch]
            for coach_info in coaches:
                coach = coach_info["coach"]
                fare_class = coach_info["fare_class"]
                for seat in coach_info["seats"]:
                    cur.execute(
                        """
                        INSERT INTO seat_layouts (schedule_id, seat_id, coach, fare_class, row_number, column_letter)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (schedule_id, seat_id) DO NOTHING
                        """,
                        (target_sch, seat["seat_id"], coach, fare_class, seat["row"], seat["column"])
                    )


def seed_users(cur):
    data = load("registered_users.json")
    print(f"  Users: seeding {len(data)} user accounts...")
    try:
        from argon2 import PasswordHasher
        ph = PasswordHasher()
    except ImportError:
        ph = None

    for u in data:
        cur.execute(
            """
            INSERT INTO users (
                user_id, full_name, email, phone, date_of_birth, secret_question, secret_answer, is_active
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id) DO NOTHING
            """,
            (
                u["user_id"],
                u["full_name"],
                u["email"],
                u.get("phone"),
                u.get("date_of_birth"),
                u.get("secret_question"),
                u.get("secret_answer"),
                u.get("is_active", True)
            )
        )
        raw_pwd = u.get("password", "transitflow123")
        if ph:
            password_hash = ph.hash(raw_pwd)
        else:
            import hashlib
            h = hashlib.sha256(raw_pwd.encode()).hexdigest()[:32]
            password_hash = f"$argon2id$v=19$m=65536,t=3,p=4$c29tZXNhbHQ${h}"
            
        cur.execute(
            """
            INSERT INTO user_credentials (user_id, password_hash)
            VALUES (%s, %s)
            ON CONFLICT (user_id) DO NOTHING
            """,
            (u["user_id"], password_hash)
        )


def seed_national_rail_bookings(cur):
    data = load("bookings.json")
    print(f"  Bookings: seeding {len(data)} bookings...")
    for bk in data:
        status = bk["status"]
        if status not in ("confirmed", "cancelled", "completed"):
            status = "confirmed"
            
        cur.execute(
            """
            INSERT INTO bookings (
                booking_id, user_id, schedule_id, origin_station_id, destination_station_id,
                travel_date, departure_time, ticket_type, fare_class, coach, seat_id,
                stops_travelled, amount_usd, status, booked_at, travelled_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (booking_id) DO NOTHING
            """,
            (
                bk["booking_id"],
                bk["user_id"],
                bk["schedule_id"],
                bk["origin_station_id"],
                bk["destination_station_id"],
                bk["travel_date"],
                bk["departure_time"],
                bk["ticket_type"],
                bk["fare_class"],
                bk["coach"],
                bk["seat_id"],
                bk.get("stops_travelled"),
                bk["amount_usd"],
                status,
                bk["booked_at"],
                bk.get("travelled_at")
            )
        )


def seed_metro_travels(cur):
    data = load("metro_travel_history.json")
    print(f"  Metro travels: seeding {len(data)} travel records...")
    for tr in data:
        cur.execute(
            """
            INSERT INTO metro_travel_history (
                trip_id, user_id, schedule_id, origin_station_id, destination_station_id,
                travel_date, ticket_type, day_pass_ref, stops_travelled, amount_usd,
                status, purchased_at, travelled_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (trip_id) DO NOTHING
            """,
            (
                tr["trip_id"],
                tr["user_id"],
                tr["schedule_id"],
                tr["origin_station_id"],
                tr["destination_station_id"],
                tr["travel_date"],
                tr["ticket_type"],
                tr.get("day_pass_ref"),
                tr.get("stops_travelled"),
                tr["amount_usd"],
                tr["status"],
                tr.get("purchased_at"),
                tr.get("travelled_at")
            )
        )


def seed_payments(cur):
    data = load("payments.json")
    print(f"  Payments: seeding {len(data)} payment records...")
    for py in data:
        raw_id = py.get("booking_id", "")
        booking_id_rail = None
        booking_id_metro = None
        if raw_id.startswith("BK"):
            booking_id_rail = raw_id
        elif raw_id.startswith("MT"):
            booking_id_metro = raw_id
            
        cur.execute(
            """
            INSERT INTO payments (
                payment_id, booking_id_rail, booking_id_metro, amount_usd, method, status, paid_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (payment_id) DO NOTHING
            """,
            (
                py["payment_id"],
                booking_id_rail,
                booking_id_metro,
                py["amount_usd"],
                py["method"],
                py["status"],
                py["paid_at"]
            )
        )


def seed_feedback(cur):
    data = load("feedback.json")
    print(f"  Feedback: seeding {len(data)} passenger feedbacks...")
    for fb in data:
        raw_id = fb.get("booking_id", "")
        booking_id_rail = None
        booking_id_metro = None
        if raw_id.startswith("BK"):
            booking_id_rail = raw_id
        elif raw_id.startswith("MT"):
            booking_id_metro = raw_id
            
        cur.execute(
            """
            INSERT INTO feedback (
                feedback_id, booking_id_rail, booking_id_metro, user_id, rating, comment, submitted_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (feedback_id) DO NOTHING
            """,
            (
                fb["feedback_id"],
                booking_id_rail,
                booking_id_metro,
                fb["user_id"],
                fb["rating"],
                fb.get("comment"),
                fb["submitted_at"]
            )
        )


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    print("Connecting to PostgreSQL...")
    conn = connect()
    conn.autocommit = False
    cur = conn.cursor()

    try:
        print("Seeding tables (dependency order):")
        seed_national_rail_stations(cur)
        seed_metro_stations(cur)
        seed_metro_schedules(cur)
        seed_national_rail_schedules(cur)
        seed_seat_layouts(cur)
        seed_users(cur)
        seed_national_rail_bookings(cur)
        seed_metro_travels(cur)
        seed_payments(cur)
        seed_feedback(cur)
        conn.commit()
        print("\nAll done. Database seeded successfully.")
    except Exception as e:
        conn.rollback()
        print(f"\nError: {e}")
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
