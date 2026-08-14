#!/usr/bin/env python3
"""Create `aria_fttest` Postgres database with a hotel-bookings dataset.

This domain is NOT part of the SQL finetune training data, so it tests how
well the fine-tuned models generalise to an unseen schema.

Usage:
    python create_fttest_hotel.py
"""

import random
from datetime import date, timedelta

import psycopg2

DB_NAME = "aria_fttest"
ADMIN_URI = "host=localhost dbname=postgres user=postgres password=12345"
URI = f"host=localhost dbname={DB_NAME} user=postgres password=12345"

DDL = [
    ("hotels", "hotel_id serial primary key, name text, city text, star_rating int, chain text"),
    ("rooms", "room_id serial primary key, hotel_id int references hotel.hotels(hotel_id), room_type text, price_per_night numeric(10,2)"),
    ("guests", "guest_id serial primary key, name text, country text, member_since date"),
    ("bookings", "booking_id serial primary key, guest_id int references hotel.guests(guest_id), room_id int references hotel.rooms(room_id), check_in date, check_out date, total_amt numeric(12,2), status text"),
]


def main():
    rng = random.Random(2026)
    start = date(2022, 1, 1)

    def rand_date(days):
        return start + timedelta(days=rng.randint(0, days))

    def pick(items):
        return rng.choice(items)

    admin = psycopg2.connect(ADMIN_URI)
    admin.set_session(autocommit=True)
    with admin.cursor() as cur:
        cur.execute(f"SELECT 1 FROM pg_database WHERE datname='{DB_NAME}'")
        if not cur.fetchone():
            cur.execute(f"CREATE DATABASE {DB_NAME}")
    admin.close()

    conn = psycopg2.connect(URI)
    conn.set_session(autocommit=True)
    with conn.cursor() as cur:
        cur.execute("DROP SCHEMA IF EXISTS hotel CASCADE")
        cur.execute("CREATE SCHEMA hotel")
        for name, cols in DDL:
            cur.execute(f"CREATE TABLE hotel.{name} ({cols})")

        hotel_ids = []
        cities = ["Paris", "London", "Dubai", "Bangkok", "Rome", "Istanbul", "Barcelona", "Singapore"]
        chains = ["GrandStay", "Atlas", "RoyalNest", "NomadInn"]
        for i in range(20):
            cur.execute("INSERT INTO hotel.hotels(name,city,star_rating,chain) VALUES(%s,%s,%s,%s) RETURNING hotel_id",
                        (f"{pick(chains)} {pick(cities)} {i}", pick(cities), rng.randint(3, 5), pick(chains)))
            hotel_ids.append(cur.fetchone()[0])

        room_ids = []
        room_types = ["standard", "deluxe", "suite", "family", "presidential"]
        for _ in range(150):
            cur.execute("INSERT INTO hotel.rooms(hotel_id,room_type,price_per_night) VALUES(%s,%s,%s) RETURNING room_id",
                        (pick(hotel_ids), pick(room_types), round(rng.uniform(60, 900), 2)))
            room_ids.append(cur.fetchone()[0])

        countries = ["US", "GB", "DE", "FR", "IN", "AE", "TH", "IT", "SG", "ES"]
        for i in range(300):
            cur.execute("INSERT INTO hotel.guests(name,country,member_since) VALUES(%s,%s,%s)",
                        (f"Guest {i}", pick(countries), rand_date(1600)))

        statuses = ["completed", "cancelled", "no_show", "checked_in"]
        for _ in range(4000):
            check_in = rand_date(900)
            nights = rng.randint(1, 14)
            check_out = check_in + timedelta(days=nights)
            base = pick(room_ids)
            nightly = rng.uniform(60, 900)
            total = round(nightly * nights * rng.uniform(0.85, 1.0), 2)
            cur.execute("INSERT INTO hotel.bookings(guest_id,room_id,check_in,check_out,total_amt,status) VALUES(%s,%s,%s,%s,%s,%s)",
                        (rng.randint(1, 300), base, check_in, check_out, total, pick(statuses)))
    conn.close()
    print(f"Created {DB_NAME} (hotel schema, 4000 bookings)")


if __name__ == "__main__":
    main()