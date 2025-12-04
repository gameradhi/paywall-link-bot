import os
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import Optional
import random
import string

DATABASE_URL = os.getenv("DATABASE_URL")


def get_conn():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    # creators table
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

    # links table
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS links (
            id SERIAL PRIMARY KEY,
            creator_id BIGINT NOT NULL,
            original_url TEXT NOT NULL,
            price INTEGER NOT NULL,
            code TEXT UNIQUE NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            clicks INTEGER DEFAULT 0,
            earnings INTEGER DEFAULT 0
        );
        """
    )

    conn.commit()
    cur.close()
    conn.close()


def upsert_creator(
    tg_id: int,
    username: str,
    full_name: str,
    phone: str,
    referred_by: Optional[str],
):
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


def _generate_code(length: int = 8) -> str:
    chars = string.ascii_uppercase + string.digits
    return "".join(random.choice(chars) for _ in range(length))


def create_paid_link(creator_tg_id: int, original_url: str, price: int) -> str:
    """
    Creates a new paid link, returns the unique code used in /start.
    """
    conn = get_conn()
    cur = conn.cursor()

    # make sure code is unique
    while True:
        code = _generate_code(8)
        cur.execute("SELECT id FROM links WHERE code = %s;", (code,))
        row = cur.fetchone()
        if row is None:
            break

    cur.execute(
        """
        INSERT INTO links (creator_id, original_url, price, code)
        VALUES (%s, %s, %s, %s)
        RETURNING id;
        """,
        (creator_tg_id, original_url, price, code),
    )

    conn.commit()
    cur.close()
    conn.close()
    return code


def get_link_by_code(code: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM links WHERE code = %s;", (code,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row


def increment_link_click(code: str, amount: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE links
        SET clicks = clicks + 1,
            earnings = earnings + %s
        WHERE code = %s;
        """,
        (amount, code),
    )
    conn.commit()
    cur.close()
    conn.close()
