import os
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import Optional
import random
import string
from datetime import datetime

DATABASE_URL = os.getenv("DATABASE_URL")


def get_conn():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


# ---------- INIT DB ----------

def init_db():
    conn = get_conn()
    cur = conn.cursor()

    # Creators table
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS creators (
            id SERIAL PRIMARY KEY,
            tg_id BIGINT UNIQUE NOT NULL,
            username TEXT,
            full_name TEXT,
            phone TEXT,
            referral_code TEXT UNIQUE,
            referred_by_code TEXT,
            wallet_balance INTEGER DEFAULT 0,        -- ₹ available to withdraw
            total_earned INTEGER DEFAULT 0,          -- all time creator earnings
            referral_earned INTEGER DEFAULT 0,       -- all time from referrals
            upi_id TEXT,
            bank_account TEXT,
            bank_ifsc TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        """
    )

    # Links table
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS links (
            id SERIAL PRIMARY KEY,
            creator_tg_id BIGINT NOT NULL,
            original_url TEXT NOT NULL,
            price INTEGER NOT NULL,
            code TEXT UNIQUE NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            clicks INTEGER DEFAULT 0,          -- total unlocks
            earnings INTEGER DEFAULT 0         -- total paid by users for this link
        );
        """
    )

    # Transactions (unlock payments)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS transactions (
            id SERIAL PRIMARY KEY,
            user_tg_id BIGINT,
            link_code TEXT,
            amount INTEGER NOT NULL,           -- total user paid
            creator_tg_id BIGINT,
            creator_amount INTEGER NOT NULL,
            platform_amount INTEGER NOT NULL,
            referrer_tg_id BIGINT,
            referrer_amount INTEGER NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        """
    )

    # Platform stats (single row, id = 1)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS platform_stats (
            id INTEGER PRIMARY KEY,
            total_earnings INTEGER DEFAULT 0,
            total_referral_paid INTEGER DEFAULT 0
        );
        """
    )
    cur.execute(
        "INSERT INTO platform_stats (id) VALUES (1) ON CONFLICT (id) DO NOTHING;"
    )

    # Withdrawals
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS withdrawals (
            id SERIAL PRIMARY KEY,
            creator_tg_id BIGINT NOT NULL,
            amount INTEGER NOT NULL,
            method_type TEXT,          -- 'upi' or 'bank'
            upi_id TEXT,
            bank_account TEXT,
            bank_ifsc TEXT,
            status TEXT DEFAULT 'pending',   -- 'pending','approved','rejected'
            created_at TIMESTAMPTZ DEFAULT NOW(),
            processed_at TIMESTAMPTZ,
            processed_by BIGINT
        );
        """
    )

    conn.commit()
    cur.close()
    conn.close()


# ---------- HELPERS ----------

def _generate_code(length: int = 8) -> str:
    chars = string.ascii_uppercase + string.digits
    return "".join(random.choice(chars) for _ in range(length))


def _generate_referral_code() -> str:
    return _generate_code(6)


# ---------- CREATORS ----------

def upsert_creator(
    tg_id: int,
    username: str,
    full_name: str,
    phone: str,
    referred_by_code: Optional[str],
):
    """
    Create or update creator.
    If new, generate unique referral_code.
    """
    conn = get_conn()
    cur = conn.cursor()

    # check if creator already exists
    cur.execute("SELECT * FROM creators WHERE tg_id = %s;", (tg_id,))
    existing = cur.fetchone()

    if existing is None:
        # generate unique referral_code
        while True:
            rcode = _generate_referral_code()
            cur.execute(
                "SELECT id FROM creators WHERE referral_code = %s;", (rcode,)
            )
            if cur.fetchone() is None:
                break

        cur.execute(
            """
            INSERT INTO creators
            (tg_id, username, full_name, phone, referral_code, referred_by_code)
            VALUES (%s, %s, %s, %s, %s, %s);
            """,
            (tg_id, username, full_name, phone, rcode, referred_by_code),
        )
    else:
        cur.execute(
            """
            UPDATE creators SET
                username = %s,
                full_name = %s,
                phone = %s,
                referred_by_code = COALESCE(%s, referred_by_code)
            WHERE tg_id = %s;
            """,
            (username, full_name, phone, referred_by_code, tg_id),
        )

    conn.commit()
    cur.close()
    conn.close()


def get_creator_by_tg_id(tg_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM creators WHERE tg_id = %s;", (tg_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row


def get_creator_by_referral_code(code: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM creators WHERE referral_code = %s;", (code,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row


def set_creator_payout_details(
    tg_id: int,
    upi_id: Optional[str],
    bank_account: Optional[str],
    bank_ifsc: Optional[str],
):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE creators SET
            upi_id = %s,
            bank_account = %s,
            bank_ifsc = %s
        WHERE tg_id = %s;
        """,
        (upi_id, bank_account, bank_ifsc, tg_id),
    )
    conn.commit()
    cur.close()
    conn.close()


def get_creator_wallet(tg_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT wallet_balance, total_earned, referral_earned,
               upi_id, bank_account, bank_ifsc, referral_code
        FROM creators WHERE tg_id = %s;
        """,
        (tg_id,),
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row


# ---------- LINKS ----------

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
        if cur.fetchone() is None:
            break

    cur.execute(
        """
        INSERT INTO links (creator_tg_id, original_url, price, code)
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


def get_links_for_creator(creator_tg_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT * FROM links
        WHERE creator_tg_id = %s
        ORDER BY created_at DESC;
        """,
        (creator_tg_id,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


# ---------- EARNINGS & TRANSACTIONS ----------

def record_unlock_payment(user_tg_id: int, link_code: str, amount: int):
    """
    Called when a user successfully unlocks a link.
    Splits money:
      - 90% to creator
      - 10% to platform
      - From platform 10%, 5% goes to referrer (if creator has one)
      - Remaining stays with platform
    All amounts in INTEGER ₹, with floor rounding.
    """

    conn = get_conn()
    cur = conn.cursor()

    # Fetch link
    cur.execute("SELECT * FROM links WHERE code = %s;", (link_code,))
    link = cur.fetchone()
    if not link:
        cur.close()
        conn.close()
        return

    creator_tg_id = link["creator_tg_id"]

    # Fetch creator
    cur.execute("SELECT * FROM creators WHERE tg_id = %s;", (creator_tg_id,))
    creator = cur.fetchone()
    if not creator:
        cur.close()
        conn.close()
        return

    # Compute basic shares
    platform_gross = amount * 10 // 100          # 10% of amount
    referrer_share = 0
    platform_net = platform_gross
    creator_share = amount - platform_gross      # remaining 90% by default

    # Handle referrer
    referrer_tg_id = None
    referred_by_code = creator.get("referred_by_code")
    if referred_by_code:
        cur.execute(
            "SELECT * FROM creators WHERE referral_code = %s;",
            (referred_by_code,),
        )
        referrer = cur.fetchone()
        if referrer:
            referrer_tg_id = referrer["tg_id"]
            referrer_share = amount * 5 // 100  # 5% of full amount
            if referrer_share > platform_gross:
                referrer_share = platform_gross
            platform_net = platform_gross - referrer_share
            # Give that 5% to referrer (wallet + referral_earned)
            cur.execute(
                """
                UPDATE creators
                SET wallet_balance = wallet_balance + %s,
                    referral_earned = referral_earned + %s
                WHERE tg_id = %s;
                """,
                (referrer_share, referrer_share, referrer_tg_id),
            )

    # Update creator earnings & wallet
    cur.execute(
        """
        UPDATE creators
        SET wallet_balance = wallet_balance + %s,
            total_earned = total_earned + %s
        WHERE tg_id = %s;
        """,
        (creator_share, creator_share, creator_tg_id),
    )

    # Update link stats
    cur.execute(
        """
        UPDATE links
        SET clicks = clicks + 1,
            earnings = earnings + %s
        WHERE code = %s;
        """,
        (amount, link_code),
    )

    # Update platform stats
    cur.execute(
        """
        UPDATE platform_stats
        SET total_earnings = total_earnings + %s,
            total_referral_paid = total_referral_paid + %s
        WHERE id = 1;
        """,
        (platform_net, referrer_share),
    )

    # Record transaction
    cur.execute(
        """
        INSERT INTO transactions
        (user_tg_id, link_code, amount,
         creator_tg_id, creator_amount,
         platform_amount, referrer_tg_id, referrer_amount)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s);
        """,
        (
            user_tg_id,
            link_code,
            amount,
            creator_tg_id,
            creator_share,
            platform_net,
            referrer_tg_id,
            referrer_share,
        ),
    )

    conn.commit()
    cur.close()
    conn.close()


# ---------- WITHDRAWALS ----------

def create_withdrawal_request(
    creator_tg_id: int,
    amount: int,
    method_type: str,
    upi_id: Optional[str],
    bank_account: Optional[str],
    bank_ifsc: Optional[str],
) -> bool:
    """
    Creates a withdrawal request and deducts from wallet if enough balance.
    Returns True if success, False if not enough balance.
    """
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        "SELECT wallet_balance FROM creators WHERE tg_id = %s;",
        (creator_tg_id,),
    )
    row = cur.fetchone()
    if not row or row["wallet_balance"] < amount:
        cur.close()
        conn.close()
        return False

    # deduct from wallet
    cur.execute(
        """
        UPDATE creators
        SET wallet_balance = wallet_balance - %s
        WHERE tg_id = %s;
        """,
        (amount, creator_tg_id),
    )

    # insert withdrawal row
    cur.execute(
        """
        INSERT INTO withdrawals
        (creator_tg_id, amount, method_type, upi_id, bank_account, bank_ifsc)
        VALUES (%s, %s, %s, %s, %s, %s);
        """,
        (creator_tg_id, amount, method_type, upi_id, bank_account, bank_ifsc),
    )

    conn.commit()
    cur.close()
    conn.close()
    return True


def get_pending_withdrawals():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT * FROM withdrawals
        WHERE status = 'pending'
        ORDER BY created_at ASC;
        """
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def update_withdrawal_status(
    withdrawal_id: int,
    status: str,
    processed_by: Optional[int],
):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE withdrawals
        SET status = %s,
            processed_by = %s,
            processed_at = NOW()
        WHERE id = %s;
        """,
        (status, processed_by, withdrawal_id),
    )
    conn.commit()
    cur.close()
    conn.close()


def get_platform_stats():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM platform_stats WHERE id = 1;")
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row
