"""
TransitFlow — PostgreSQL / Relational Database Layer
=====================================================
This module handles all queries to PostgreSQL.

TWO ROLES ARE SERVED HERE:
  1. Relational  → dual-network transit (metro + national rail),
                   availability, fares, bookings, seat selection
  2. Vector      → policy document similarity search (pgvector)

STUDENT TASK
------------
Design your schema in databases/relational/schema.sql, seed it with
skeleton/seed_postgres.py, then implement the query functions below.

Functions prefixed with `query_`  are read-only lookups called by the agent.
Functions prefixed with `execute_` are write operations (booking/cancellation).

The vector functions (query_policy_vector_search, store_policy_document)
are already implemented — do not modify them.
"""

from __future__ import annotations

import json
import random
import string
from datetime import datetime, timezone
from typing import Optional

import psycopg2
import psycopg2.extras

from skeleton.config import PG_DSN, VECTOR_TOP_K, VECTOR_SIMILARITY_THRESHOLD


def _connect():
    """Return a new psycopg2 connection with autocommit enabled."""
    conn = psycopg2.connect(PG_DSN)
    conn.autocommit = True
    return conn


def _gen_booking_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"BK-{suffix}"


def _gen_payment_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"PM-{suffix}"


# ── Example ───────────────────────────────────────────────────────────────────
# The block below shows the query pattern: open a cursor, run SQL, return rows.
# Use _connect() for read-only queries; for write operations use a manual
# connection with conn.commit() / conn.rollback() (see execute_booking below).

def example_query() -> dict:
    """Example: returns the name of the connected database."""
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT current_database() AS db;")
            return dict(cur.fetchone())

# ── NATIONAL RAIL AVAILABILITY ────────────────────────────────────────────────

def query_national_rail_availability(
    origin_id: str,
    destination_id: str,
    travel_date: Optional[str] = None,
) -> list[dict]:
    """
    Return national rail schedules that serve both origin and destination stations
    in the correct order, along with seat occupancy for the requested travel date.
    """
    day_of_week = None
    if travel_date:
        try:
            dt = datetime.strptime(travel_date, "%Y-%m-%d")
            day_of_week = dt.strftime("%a").lower()
        except ValueError:
            pass

    sql = """
        SELECT 
            s.schedule_id,
            s.line,
            s.service_type,
            s.direction,
            s.first_train_time,
            st_origin.stop_order AS origin_order,
            st_origin.travel_time_from_origin_min AS origin_time,
            st_dest.stop_order AS dest_order,
            st_dest.travel_time_from_origin_min AS dest_time,
            (st_dest.stop_order - st_origin.stop_order) AS stops_travelled
        FROM national_rail_schedules s
        JOIN national_rail_stops st_origin ON s.schedule_id = st_origin.schedule_id AND st_origin.station_id = %s AND st_origin.is_stop = TRUE
        JOIN national_rail_stops st_dest ON s.schedule_id = st_dest.schedule_id AND st_dest.station_id = %s AND st_dest.is_stop = TRUE
        WHERE st_origin.stop_order < st_dest.stop_order
    """
    
    params = [origin_id, destination_id]
    if day_of_week:
        sql += """
            AND EXISTS (
                SELECT 1 FROM national_rail_schedule_days d 
                WHERE d.schedule_id = s.schedule_id AND d.day_of_week = %s
            )
        """
        params.append(day_of_week)

    results = []
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            schedules = cur.fetchall()
            
            for sch in schedules:
                sch_id = sch["schedule_id"]
                stops = sch["stops_travelled"]
                
                # Calculate time
                first_train_time = sch["first_train_time"]
                origin_min = sch["origin_time"]
                dest_min = sch["dest_time"]
                
                origin_sec = first_train_time.hour * 3600 + first_train_time.minute * 60 + first_train_time.second + origin_min * 60
                dep_hour, dep_min = (origin_sec // 3600) % 24, (origin_sec // 60) % 60
                departure_time = f"{dep_hour:02d}:{dep_min:02d}"
                
                dest_sec = first_train_time.hour * 3600 + first_train_time.minute * 60 + first_train_time.second + dest_min * 60
                arr_hour, arr_min = (dest_sec // 3600) % 24, (dest_sec // 60) % 60
                arrival_time = f"{arr_hour:02d}:{arr_min:02d}"
                
                # Fetch fares
                cur.execute(
                    "SELECT fare_class, base_fare_usd, per_stop_rate_usd FROM national_rail_fares WHERE schedule_id = %s",
                    (sch_id,)
                )
                fares = cur.fetchall()
                fare_classes = {}
                for f in fares:
                    total_fare = float(f["base_fare_usd"]) + float(f["per_stop_rate_usd"]) * stops
                    fare_classes[f["fare_class"]] = {
                        "base_fare_usd": float(f["base_fare_usd"]),
                        "per_stop_rate_usd": float(f["per_stop_rate_usd"]),
                        "total_fare_usd": round(total_fare, 2)
                    }
                
                # Seat occupancy
                total_seats = 0
                available_seats = 0
                occupancy_rate = 0.0
                
                if travel_date:
                    cur.execute("SELECT count(*) AS cnt FROM seat_layouts WHERE schedule_id = %s", (sch_id,))
                    total_seats = cur.fetchone()["cnt"]
                    
                    cur.execute(
                        """
                        SELECT count(*) AS cnt FROM bookings 
                        WHERE schedule_id = %s AND travel_date = %s AND status IN ('confirmed', 'completed')
                        """,
                        (sch_id, travel_date)
                    )
                    booked_seats = cur.fetchone()["cnt"]
                    available_seats = max(0, total_seats - booked_seats)
                    occupancy_rate = round(booked_seats / total_seats, 2) if total_seats > 0 else 0.0
                
                results.append({
                    "schedule_id": sch_id,
                    "line": sch["line"],
                    "service_type": sch["service_type"],
                    "direction": sch["direction"],
                    "stops_travelled": stops,
                    "departure_time": departure_time,
                    "arrival_time": arrival_time,
                    "fare_classes": fare_classes,
                    "total_seats": total_seats,
                    "available_seats": available_seats,
                    "occupancy_rate": occupancy_rate
                })
                
    return results


def query_national_rail_fare(
    schedule_id: str,
    fare_class: str,
    stops_travelled: int,
) -> Optional[dict]:
    """
    Calculate the fare for a national rail journey.
    """
    sql = """
        SELECT base_fare_usd, per_stop_rate_usd 
        FROM national_rail_fares 
        WHERE schedule_id = %s AND fare_class = %s
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (schedule_id, fare_class))
            row = cur.fetchone()
            if not row:
                return None
            
            base_fare = float(row["base_fare_usd"])
            per_stop = float(row["per_stop_rate_usd"])
            total_fare = base_fare + per_stop * stops_travelled
            return {
                "fare_class": fare_class,
                "base_fare_usd": base_fare,
                "per_stop_rate_usd": per_stop,
                "total_fare_usd": round(total_fare, 2)
            }


# ── METRO SCHEDULES & FARE ────────────────────────────────────────────────────

def query_metro_schedules(origin_id: str, destination_id: str) -> list[dict]:
    """
    Return metro schedules that serve both origin and destination in the correct order.
    """
    sql = """
        SELECT 
            s.schedule_id,
            s.line,
            s.direction,
            s.first_train_time,
            s.last_train_time,
            s.base_fare_usd,
            s.per_stop_rate_usd,
            s.frequency_min,
            st_origin.stop_order AS origin_order,
            st_origin.travel_time_from_origin_min AS origin_time,
            st_dest.stop_order AS dest_order,
            st_dest.travel_time_from_origin_min AS dest_time,
            (st_dest.stop_order - st_origin.stop_order) AS stops_travelled
        FROM metro_schedules s
        JOIN metro_schedule_stops st_origin ON s.schedule_id = st_origin.schedule_id AND st_origin.station_id = %s
        JOIN metro_schedule_stops st_dest ON s.schedule_id = st_dest.schedule_id AND st_dest.station_id = %s
        WHERE st_origin.stop_order < st_dest.stop_order
    """
    results = []
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (origin_id, destination_id))
            rows = cur.fetchall()
            for r in rows:
                stops = r["stops_travelled"]
                base_fare = float(r["base_fare_usd"])
                per_stop = float(r["per_stop_rate_usd"])
                total_fare = base_fare + per_stop * stops
                
                first_train_time = r["first_train_time"]
                origin_min = r["origin_time"]
                dest_min = r["dest_time"]
                
                origin_sec = first_train_time.hour * 3600 + first_train_time.minute * 60 + first_train_time.second + origin_min * 60
                dep_hour, dep_min = (origin_sec // 3600) % 24, (origin_sec // 60) % 60
                departure_time = f"{dep_hour:02d}:{dep_min:02d}"
                
                dest_sec = first_train_time.hour * 3600 + first_train_time.minute * 60 + first_train_time.second + dest_min * 60
                arr_hour, arr_min = (dest_sec // 3600) % 24, (dest_sec // 60) % 60
                arrival_time = f"{arr_hour:02d}:{arr_min:02d}"
                
                results.append({
                    "schedule_id": r["schedule_id"],
                    "line": r["line"],
                    "direction": r["direction"],
                    "first_train_time": str(first_train_time),
                    "last_train_time": str(r["last_train_time"]),
                    "frequency_min": r["frequency_min"],
                    "stops_travelled": stops,
                    "departure_time": departure_time,
                    "arrival_time": arrival_time,
                    "fare_usd": round(total_fare, 2)
                })
    return results


def query_metro_fare(schedule_id: str, stops_travelled: int) -> Optional[dict]:
    """
    Calculate the metro fare for a single-ticket journey.
    """
    sql = "SELECT base_fare_usd, per_stop_rate_usd FROM metro_schedules WHERE schedule_id = %s"
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (schedule_id,))
            row = cur.fetchone()
            if not row:
                return None
            
            base_fare = float(row["base_fare_usd"])
            per_stop = float(row["per_stop_rate_usd"])
            total_fare = base_fare + per_stop * stops_travelled
            return {
                "base_fare_usd": base_fare,
                "per_stop_rate_usd": per_stop,
                "total_fare_usd": round(total_fare, 2)
            }


# ── SEAT SELECTION ────────────────────────────────────────────────────────────

def query_available_seats(
    schedule_id: str,
    travel_date: str,
    fare_class: str,
) -> list[dict]:
    """
    Return available seats for a national rail journey on a given date.
    """
    sql_all = """
        SELECT seat_id, coach, row_number, column_letter
        FROM seat_layouts
        WHERE schedule_id = %s AND fare_class = %s
    """
    sql_booked = """
        SELECT seat_id
        FROM bookings
        WHERE schedule_id = %s AND travel_date = %s AND fare_class = %s
          AND status IN ('confirmed', 'completed')
    """
    results = []
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql_all, (schedule_id, fare_class))
            all_seats = cur.fetchall()
            
            cur.execute(sql_booked, (schedule_id, travel_date, fare_class))
            booked_seat_ids = {row["seat_id"] for row in cur.fetchall()}
            
            for s in all_seats:
                if s["seat_id"] not in booked_seat_ids:
                    results.append({
                        "seat_id": s["seat_id"],
                        "coach": s["coach"],
                        "row": s["row_number"],
                        "column": s["column_letter"]
                    })
    return sorted(results, key=lambda x: (x["coach"], x["row"], x["column"]))


def auto_select_adjacent_seats(available_seats: list[dict], count: int) -> list[str]:
    """
    Select `count` seats that are as close together as possible (same row preferred,
    then adjacent rows). Returns a list of seat_ids.
    """
    if not available_seats or count <= 0:
        return []
    if count >= len(available_seats):
        return [s["seat_id"] for s in available_seats[:count]]

    from collections import defaultdict
    rows = defaultdict(list)
    for seat in available_seats:
        rows[seat["row"]].append(seat)

    for row_seats in sorted(rows.values(), key=lambda s: s[0]["row"]):
        if len(row_seats) >= count:
            return [s["seat_id"] for s in row_seats[:count]]

    sorted_seats = sorted(available_seats, key=lambda s: (s["row"], s["column"]))
    return [s["seat_id"] for s in sorted_seats[:count]]


# ── USER & BOOKING QUERIES ────────────────────────────────────────────────────

def query_user_profile(user_email: str) -> Optional[dict]:
    """Return a user's profile by email."""
    sql = """
        SELECT user_id, full_name, email, phone, date_of_birth, secret_question, secret_answer, registered_at, is_active
        FROM users
        WHERE email = %s
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (user_email,))
            row = cur.fetchone()
            if not row:
                return None
            r = dict(row)
            if r.get("date_of_birth"):
                r["date_of_birth"] = str(r["date_of_birth"])
            r["registered_at"] = r["registered_at"].isoformat()
            
            names = r["full_name"].split(" ", 1)
            r["first_name"] = names[0]
            r["surname"] = names[1] if len(names) > 1 else ""
            
            return r


def query_user_bookings(user_email: str) -> dict:
    """
    Return a user's combined booking history (national rail + metro).
    """
    profile = query_user_profile(user_email)
    if not profile:
        return {"national_rail": [], "metro": []}
    
    user_id = profile["user_id"]
    
    sql_rail = """
        SELECT booking_id, schedule_id, origin_station_id, destination_station_id,
               travel_date, departure_time, ticket_type, fare_class, coach, seat_id,
               stops_travelled, amount_usd, status, booked_at, travelled_at
        FROM bookings
        WHERE user_id = %s
        ORDER BY travel_date DESC, departure_time DESC
    """
    
    sql_metro = """
        SELECT trip_id, schedule_id, origin_station_id, destination_station_id,
               travel_date, ticket_type, day_pass_ref, stops_travelled, amount_usd,
               status, purchased_at, travelled_at
        FROM metro_travel_history
        WHERE user_id = %s
        ORDER BY travel_date DESC, travelled_at DESC
    """
    
    results = {"national_rail": [], "metro": []}
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql_rail, (user_id,))
            for row in cur.fetchall():
                r = dict(row)
                r["travel_date"] = str(r["travel_date"])
                r["departure_time"] = str(r["departure_time"])
                r["booked_at"] = r["booked_at"].isoformat()
                if r.get("travelled_at"):
                    r["travelled_at"] = r["travelled_at"].isoformat()
                r["amount_usd"] = float(r["amount_usd"])
                results["national_rail"].append(r)
                
            cur.execute(sql_metro, (user_id,))
            for row in cur.fetchall():
                r = dict(row)
                r["travel_date"] = str(r["travel_date"])
                if r.get("purchased_at"):
                    r["purchased_at"] = r["purchased_at"].isoformat()
                if r.get("travelled_at"):
                    r["travelled_at"] = r["travelled_at"].isoformat()
                r["amount_usd"] = float(r["amount_usd"])
                results["metro"].append(r)
                
    return results


def query_payment_info(booking_id: str) -> Optional[dict]:
    """Return payment record for a booking or metro trip."""
    sql = """
        SELECT payment_id, booking_id_rail, booking_id_metro, amount_usd, method, status, paid_at
        FROM payments
        WHERE booking_id_rail = %s OR booking_id_metro = %s
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (booking_id, booking_id))
            row = cur.fetchone()
            if not row:
                return None
            r = dict(row)
            r["amount_usd"] = float(r["amount_usd"])
            r["paid_at"] = r["paid_at"].isoformat()
            return r


# ── TRANSACTIONAL OPERATIONS ──────────────────────────────────────────────────

def execute_booking(
    user_id: str,
    schedule_id: str,
    origin_station_id: str,
    destination_station_id: str,
    travel_date: str,
    fare_class: str,
    seat_id: str,
    ticket_type: str = "single",
) -> tuple[bool, dict | str]:
    """
    Create a national rail booking for a logged-in user.
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT stop_order, travel_time_from_origin_min
                FROM national_rail_stops
                WHERE schedule_id = %s AND station_id = %s AND is_stop = TRUE
                """,
                (schedule_id, origin_station_id)
            )
            origin_stop = cur.fetchone()
            
            cur.execute(
                """
                SELECT stop_order, travel_time_from_origin_min
                FROM national_rail_stops
                WHERE schedule_id = %s AND station_id = %s AND is_stop = TRUE
                """,
                (schedule_id, destination_station_id)
            )
            dest_stop = cur.fetchone()
            
            if not origin_stop or not dest_stop:
                return False, "Origin or destination station not found on this schedule"
            
            stops = dest_stop["stop_order"] - origin_stop["stop_order"]
            if stops <= 0:
                return False, "Invalid station travel order"
            
            cur.execute("SELECT first_train_time FROM national_rail_schedules WHERE schedule_id = %s", (schedule_id,))
            sch_row = cur.fetchone()
            if not sch_row:
                return False, "Schedule not found"
            
            first_train_time = sch_row["first_train_time"]
            origin_min = origin_stop["travel_time_from_origin_min"]
            origin_sec = first_train_time.hour * 3600 + first_train_time.minute * 60 + first_train_time.second + origin_min * 60
            dep_hour, dep_min = (origin_sec // 3600) % 24, (origin_sec // 60) % 60
            departure_time = f"{dep_hour:02d}:{dep_min:02d}"
            
            fare_info = query_national_rail_fare(schedule_id, fare_class, stops)
            if not fare_info:
                return False, "Fare structure not found for this schedule"
            amount_usd = fare_info["total_fare_usd"]
            
            available_seats = query_available_seats(schedule_id, travel_date, fare_class)
            if not available_seats:
                return False, "No available seats on this train for the specified date"
                
            selected_seat = None
            if seat_id == "any":
                selected_seat = available_seats[0]
            else:
                selected_seat = next((s for s in available_seats if s["seat_id"] == seat_id), None)
                if not selected_seat:
                    return False, f"Seat {seat_id} is not available on this date"
            
            conn.autocommit = False
            try:
                new_booking_id = _gen_booking_id()
                new_payment_id = _gen_payment_id()
                
                cur.execute(
                    """
                    INSERT INTO bookings (
                        booking_id, user_id, schedule_id, origin_station_id, destination_station_id,
                        travel_date, departure_time, ticket_type, fare_class, coach, seat_id,
                        stops_travelled, amount_usd, status, booked_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'confirmed', NOW())
                    """,
                    (
                        new_booking_id,
                        user_id,
                        schedule_id,
                        origin_station_id,
                        destination_station_id,
                        travel_date,
                        departure_time,
                        ticket_type,
                        fare_class,
                        selected_seat["coach"],
                        selected_seat["seat_id"],
                        stops,
                        amount_usd
                    )
                )
                
                cur.execute(
                    """
                    INSERT INTO payments (
                        payment_id, booking_id_rail, booking_id_metro, amount_usd, method, status, paid_at
                    ) VALUES (%s, %s, NULL, %s, 'credit_card', 'paid', NOW())
                    """,
                    (new_payment_id, new_booking_id, amount_usd)
                )
                
                conn.commit()
                return True, {
                    "booking_id": new_booking_id,
                    "schedule_id": schedule_id,
                    "origin_station_id": origin_station_id,
                    "destination_station_id": destination_station_id,
                    "travel_date": travel_date,
                    "departure_time": departure_time,
                    "ticket_type": ticket_type,
                    "fare_class": fare_class,
                    "coach": selected_seat["coach"],
                    "seat_id": selected_seat["seat_id"],
                    "amount_usd": amount_usd,
                    "payment_id": new_payment_id
                }
            except Exception as e:
                conn.rollback()
                return False, f"Database transaction failed: {e}"


def execute_cancellation(booking_id: str, user_id: str) -> tuple[bool, dict | str]:
    """
    Cancel a national rail booking owned by the given user.
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT b.booking_id, b.user_id, b.schedule_id, b.travel_date, b.departure_time, b.amount_usd, b.status,
                       s.service_type
                FROM bookings b
                JOIN national_rail_schedules s ON b.schedule_id = s.schedule_id
                WHERE b.booking_id = %s
                """,
                (booking_id,)
            )
            bk = cur.fetchone()
            if not bk:
                return False, "Booking not found"
            if bk["user_id"] != user_id:
                return False, "This booking does not belong to the requesting user"
            if bk["status"] != "confirmed":
                return False, f"Booking status is {bk['status']}, cannot cancel"
            
            try:
                travel_date_str = str(bk["travel_date"])
                dep_time_str = str(bk["departure_time"])
                departure_dt = datetime.strptime(f"{travel_date_str} {dep_time_str}", "%Y-%m-%d %H:%M:%S")
            except Exception:
                try:
                    departure_dt = datetime.strptime(f"{travel_date_str} {dep_time_str}", "%Y-%m-%d %H:%M")
                except Exception:
                    departure_dt = datetime.now()
            
            cur.execute("SELECT booked_at FROM bookings WHERE booking_id = %s", (booking_id,))
            booked_at = cur.fetchone()["booked_at"]
            
            cancellation_time = datetime.now(timezone.utc)
            departure_dt_tz = departure_dt.replace(tzinfo=timezone.utc)
            if departure_dt_tz < cancellation_time:
                cancellation_time = booked_at + timedelta(hours=1)
                
            hours_diff = (departure_dt_tz - cancellation_time).total_seconds() / 3600.0
            
            service_type = bk["service_type"]
            refund_rate = 1.0
            policy_note = ""
            
            if service_type == "express":
                if hours_diff > 24:
                    refund_rate = 1.0
                    policy_note = "Express Refund Policy (RF002): >24 hours prior. 100% refund."
                elif hours_diff >= 6:
                    refund_rate = 0.5
                    policy_note = "Express Refund Policy (RF002): 6-24 hours prior. 50% refund."
                else:
                    refund_rate = 0.0
                    policy_note = "Express Refund Policy (RF002): <6 hours prior. 0% refund."
            else:
                if hours_diff > 24:
                    refund_rate = 1.0
                    policy_note = "Regular Refund Policy (RF001): >24 hours prior. 100% refund."
                elif hours_diff >= 12:
                    refund_rate = 0.75
                    policy_note = "Regular Refund Policy (RF001): 12-24 hours prior. 75% refund."
                elif hours_diff >= 6:
                    refund_rate = 0.5
                    policy_note = "Regular Refund Policy (RF001): 6-12 hours prior. 50% refund."
                else:
                    refund_rate = 0.0
                    policy_note = "Regular Refund Policy (RF001): <6 hours prior. 0% refund."
            
            refund_amount = round(float(bk["amount_usd"]) * refund_rate, 2)
            
            conn.autocommit = False
            try:
                cur.execute(
                    "UPDATE bookings SET status = 'cancelled' WHERE booking_id = %s",
                    (booking_id,)
                )
                cur.execute(
                    "UPDATE payments SET status = 'refunded' WHERE booking_id_rail = %s",
                    (booking_id,)
                )
                conn.commit()
                return True, {
                    "booking_id": booking_id,
                    "refund_amount_usd": refund_amount,
                    "refund_rate": refund_rate,
                    "policy_note": policy_note
                }
            except Exception as e:
                conn.rollback()
                return False, f"Cancellation failed: {e}"


# ── AUTHENTICATION QUERIES ────────────────────────────────────────────────────

def register_user(
    email: str,
    first_name: str,
    surname: str,
    year_of_birth: int,
    password: str,
    secret_question: str,
    secret_answer: str,
) -> tuple[bool, str]:
    """
    Register a new user.
    """
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM users WHERE email = %s", (email,))
            if cur.fetchone()[0] > 0:
                return False, "Email already registered"
                
            cur.execute("SELECT user_id FROM users WHERE user_id LIKE 'RU%'")
            ids = cur.fetchall()
            max_num = 0
            for row in ids:
                try:
                    num = int(row[0][2:])
                    if num > max_num:
                        max_num = num
                except ValueError:
                    pass
            new_id = f"RU{max_num + 1:02d}"
            
            try:
                from argon2 import PasswordHasher
                ph = PasswordHasher()
                pwd_hash = ph.hash(password)
            except ImportError:
                import hashlib
                h = hashlib.sha256(password.encode()).hexdigest()[:32]
                pwd_hash = f"$argon2id$v=19$m=65536,t=3,p=4$c29tZXNhbHQ${h}"
                
            full_name = f"{first_name} {surname}".strip()
            dob = f"{year_of_birth}-01-01"
            
            conn.autocommit = False
            try:
                cur.execute(
                    """
                    INSERT INTO users (user_id, full_name, email, date_of_birth, secret_question, secret_answer, is_active)
                    VALUES (%s, %s, %s, %s, %s, %s, TRUE)
                    """,
                    (new_id, full_name, email, dob, secret_question, secret_answer)
                )
                cur.execute(
                    "INSERT INTO user_credentials (user_id, password_hash) VALUES (%s, %s)",
                    (new_id, pwd_hash)
                )
                conn.commit()
                return True, new_id
            except Exception as e:
                conn.rollback()
                return False, f"Database error: {e}"


def login_user(email: str, password: str) -> Optional[dict]:
    """
    Verify credentials. Returns a user dict on success or None on failure.
    """
    profile = query_user_profile(email)
    if not profile:
        return None
        
    user_id = profile["user_id"]
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT password_hash FROM user_credentials WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            if not row:
                return None
            pwd_hash = row[0]
            
            is_valid = False
            if pwd_hash.startswith("$argon2id$"):
                try:
                    from argon2 import PasswordHasher
                    ph = PasswordHasher()
                    if "c29tZXNhbHQ" not in pwd_hash:
                        ph.verify(pwd_hash, password)
                        is_valid = True
                    else:
                        import hashlib
                        h = hashlib.sha256(password.encode()).hexdigest()[:32]
                        expected = f"$argon2id$v=19$m=65536,t=3,p=4$c29tZXNhbHQ${h}"
                        is_valid = (pwd_hash == expected)
                except Exception:
                    is_valid = False
            else:
                is_valid = (pwd_hash == password)
                
            if is_valid:
                return profile
            return None


def get_user_secret_question(email: str) -> Optional[str]:
    """Return the secret question for a registered email, or None if not found."""
    sql = "SELECT secret_question FROM users WHERE email = %s"
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (email,))
            row = cur.fetchone()
            return row[0] if row else None


def verify_secret_answer(email: str, answer: str) -> bool:
    """Return True if the provided answer matches the stored secret answer (case-insensitive)."""
    sql = "SELECT secret_answer FROM users WHERE email = %s"
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (email,))
            row = cur.fetchone()
            if not row or not row[0]:
                return False
            return row[0].strip().lower() == answer.strip().lower()


def update_password(email: str, new_password: str) -> bool:
    """Update the password for a user. Returns True if the row was updated."""
    profile = query_user_profile(email)
    if not profile:
        return False
    user_id = profile["user_id"]
    
    try:
        from argon2 import PasswordHasher
        ph = PasswordHasher()
        pwd_hash = ph.hash(new_password)
    except ImportError:
        import hashlib
        h = hashlib.sha256(new_password.encode()).hexdigest()[:32]
        pwd_hash = f"$argon2id$v=19$m=65536,t=3,p=4$c29tZXNhbHQ${h}"
        
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE user_credentials SET password_hash = %s WHERE user_id = %s",
                (pwd_hash, user_id)
            )
            return cur.rowcount > 0


# ── VECTOR / RAG QUERIES — do not modify ─────────────────────────────────────

def query_policy_vector_search(embedding: list[float], top_k: int = VECTOR_TOP_K) -> list[dict]:
    """
    Find the most relevant policy documents for a given query embedding.

    Args:
        embedding: Query vector from llm.embed(user_question)
        top_k:     Number of results to return

    Returns:
        List of dicts with title, category, content, and similarity score
    """
    sql = """
        SELECT
            title,
            category,
            content,
            1 - (embedding <=> %s::vector) AS similarity
        FROM policy_documents
        WHERE 1 - (embedding <=> %s::vector) > %s
        ORDER BY embedding <=> %s::vector
        LIMIT %s
    """
    vec_str = "[" + ",".join(str(x) for x in embedding) + "]"
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (vec_str, vec_str, VECTOR_SIMILARITY_THRESHOLD, vec_str, top_k))
            return [dict(row) for row in cur.fetchall()]


def store_policy_document(
    title: str,
    category: str,
    content: str,
    embedding: list[float],
    source_file: str = "",
) -> int:
    """
    Insert a policy document with its embedding into the database.
    Used by skeleton/seed_vectors.py — students don't need to call this directly.

    Returns:
        The new document's id
    """
    sql = """
        INSERT INTO policy_documents (title, category, content, embedding, source_file)
        VALUES (%s, %s, %s, %s::vector, %s)
        RETURNING id
    """
    vec_str = "[" + ",".join(str(x) for x in embedding) + "]"
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (title, category, content, vec_str, source_file))
            return cur.fetchone()[0]
