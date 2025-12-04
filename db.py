import os
import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.getenv("DATABASE_URL")


def get_conn():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    # creators table (basic for now)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS creators (
            id SERIAL PRIMARY KEY,
            tg_id BIGINT UNIQUE NOT NULL,
            username TEXT,
            full_name TEXT,
            phone TEXT,
            referred_by TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        """
    )

    conn.commit()
    cur.close()
    conn.close()


def upsert_creator(tg_id: int, username: str, full_name: str, phone: str, referred_by: str | None):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO creators (tg_id, username, full_name, phone, referred_by)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (tg_id) DO UPDATE
        SET username = EXCLUDED.username,
            full_name = EXCLUDED.full_name,
            phone = EXCLUDED.phone,
            referred_by = EXCLUDED.referred_by;
        """,
        (tg_id, username, full_name, phone, referred_by),
    )

    conn.commit()
    cur.close()
    conn.close()
