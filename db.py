# db.py
import sqlite3
import threading
from datetime import datetime
from typing import Optional, Tuple, List, Dict, Any

DB_PATH = "telelink.db"

_lock = threading.Lock()


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _lock, _get_conn() as conn:
        cur = conn.cursor()

        # Users (both normal users and creators)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                tg_id          INTEGER PRIMARY KEY,
                username       TEXT,
                role           TEXT DEFAULT 'user', -- 'user' or 'creator' or 'admin'
                ref_code       TEXT,
                referred_by    INTEGER,            -- tg_id of referrer
                created_at     TEXT
            );
            """
        )

        # Paid links created by creators
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS links (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                short_code    TEXT UNIQUE,
                creator_tg_id INTEGER,
                original_url  TEXT,
                price         REAL,
                active        INTEGER DEFAULT 1,
                created_at    TEXT,
                FOREIGN KEY (creator_tg_id) REFERENCES users(tg_id)
            );
            """
        )

        # Payments (each unlock purchase)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS payments (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                user_tg_id         INTEGER,
                link_id            INTEGER,
                amount_paid        REAL,
                platform_fee       REAL,
                cashfree_fee       REAL,
                creator_earning    REAL,
                order_id           TEXT,
                status             TEXT, -- 'success', 'failed', 'pending'
                created_at         TEXT,
                FOREIGN KEY (user_tg_id) REFERENCES users(tg_id),
                FOREIGN KEY (link_id) REFERENCES links(id)
            );
            """
        )

        # Wallets for creators/referrers (we use only creators for now)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS wallets (
                user_tg_id   INTEGER PRIMARY KEY,
                balance      REAL DEFAULT 0,
                total_earned REAL DEFAULT 0,
                updated_at   TEXT,
                FOREIGN KEY (user_tg_id) REFERENCES users(tg_id)
            );
            """
        )

        # Withdrawals
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS withdrawals (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                user_tg_id   INTEGER,
                amount       REAL,
                method       TEXT,     -- 'upi' or 'bank'
                account      TEXT,     -- UPI ID or 'IFSC|ACCOUNT'
                status       TEXT,     -- 'pending', 'processing', 'paid', 'failed', 'rejected'
                created_at   TEXT,
                updated_at   TEXT,
                external_ref TEXT,     -- payout ref from Cashfree
                FOREIGN KEY (user_tg_id) REFERENCES users(tg_id)
            );
            """
        )

        conn.commit()


# ========== USER FUNCTIONS ==========

def get_or_create_user(tg_id: int, username: Optional[str] = None, role: str = "user") -> Dict[str, Any]:
    now = datetime.utcnow().isoformat()
    with _lock, _get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,))
        row = cur.fetchone()
        if row:
            # optionally update username if changed
            if username and row["username"] != username:
                cur.execute("UPDATE users SET username = ? WHERE tg_id = ?", (username, tg_id))
                conn.commit()
            return dict(row)

        # create new
        cur.execute(
            """
            INSERT INTO users (tg_id, username, role, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (tg_id, username, role, now),
        )
        conn.commit()
        return {
            "tg_id": tg_id,
            "username": username,
            "role": role,
            "ref_code": None,
            "referred_by": None,
            "created_at": now,
        }


def set_user_role(tg_id: int, role: str) -> None:
    with _lock, _get_conn() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE users SET role = ? WHERE tg_id = ?", (role, tg_id))
        conn.commit()


def get_user(tg_id: int) -> Optional[Dict[str, Any]]:
    with _lock, _get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,))
        row = cur.fetchone()
        return dict(row) if row else None


# ========== LINKS ==========

def create_link(short_code: str, creator_tg_id: int, original_url: str, price: float) -> int:
    now = datetime.utcnow().isoformat()
    with _lock, _get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO links (short_code, creator_tg_id, original_url, price, active, created_at)
            VALUES (?, ?, ?, ?, 1, ?)
            """,
            (short_code, creator_tg_id, original_url, price, now),
        )
        conn.commit()
        return cur.lastrowid


def get_link_by_short_code(short_code: str) -> Optional[Dict[str, Any]]:
    with _lock, _get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM links WHERE short_code = ? AND active = 1", (short_code,))
        row = cur.fetchone()
        return dict(row) if row else None


def get_creator_links(creator_tg_id: int) -> List[Dict[str, Any]]:
    with _lock, _get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM links WHERE creator_tg_id = ? ORDER BY created_at DESC",
            (creator_tg_id,),
        )
        rows = cur.fetchall()
        return [dict(r) for r in rows]


# ========== WALLET & PAYMENTS ==========

def _ensure_wallet(cur: sqlite3.Cursor, tg_id: int) -> None:
    cur.execute("SELECT user_tg_id FROM wallets WHERE user_tg_id = ?", (tg_id,))
    if not cur.fetchone():
        cur.execute(
            """
            INSERT INTO wallets (user_tg_id, balance, total_earned, updated_at)
            VALUES (?, 0, 0, ?)
            """,
            (tg_id, datetime.utcnow().isoformat()),
        )


def record_payment(
    user_tg_id: int,
    short_code: str,
    amount_paid: float,
    platform_fee: float,
    cashfree_fee: float,
    creator_earning: float,
    order_id: str,
) -> Optional[int]:
    """
    Save a successful payment, update creator wallet.
    Returns payment_id or None if link not found.
    """
    now = datetime.utcnow().isoformat()
    with _lock, _get_conn() as conn:
        cur = conn.cursor()
        # find link
        cur.execute("SELECT * FROM links WHERE short_code = ?", (short_code,))
        link = cur.fetchone()
        if not link:
            return None

        link_id = link["id"]
        creator_tg_id = link["creator_tg_id"]

        # insert payment
        cur.execute(
            """
            INSERT INTO payments (
                user_tg_id, link_id, amount_paid,
                platform_fee, cashfree_fee, creator_earning,
                order_id, status, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 'success', ?)
            """,
            (
                user_tg_id,
                link_id,
                amount_paid,
                platform_fee,
                cashfree_fee,
                creator_earning,
                order_id,
                now,
            ),
        )
        payment_id = cur.lastrowid

        # update creator wallet
        _ensure_wallet(cur, creator_tg_id)
        cur.execute(
            """
            UPDATE wallets
            SET balance = balance + ?, total_earned = total_earned + ?, updated_at = ?
            WHERE user_tg_id = ?
            """,
            (creator_earning, creator_earning, now, creator_tg_id),
        )

        conn.commit()
        return payment_id


def get_wallet(tg_id: int) -> Dict[str, Any]:
    with _lock, _get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM wallets WHERE user_tg_id = ?", (tg_id,))
        row = cur.fetchone()
        if not row:
            return {"user_tg_id": tg_id, "balance": 0.0, "total_earned": 0.0}
        return {
            "user_tg_id": row["user_tg_id"],
            "balance": row["balance"],
            "total_earned": row["total_earned"],
        }


def get_creator_stats(tg_id: int) -> Dict[str, Any]:
    with _lock, _get_conn() as conn:
        cur = conn.cursor()

        # total payments and sum
        cur.execute(
            """
            SELECT COUNT(p.id) AS total_sales,
                   COALESCE(SUM(p.amount_paid), 0) AS total_revenue,
                   COALESCE(SUM(p.creator_earning), 0) AS total_creator
            FROM payments p
            JOIN links l ON p.link_id = l.id
            WHERE l.creator_tg_id = ? AND p.status = 'success'
            """,
            (tg_id,),
        )
        row = cur.fetchone()
        if not row:
            return {
                "total_sales": 0,
                "total_revenue": 0.0,
                "total_creator": 0.0,
            }
        return {
            "total_sales": row["total_sales"],
            "total_revenue": row["total_revenue"],
            "total_creator": row["total_creator"],
        }


# ========== WITHDRAWALS ==========

def create_withdrawal(
    user_tg_id: int,
    amount: float,
    method: str,
    account: str,
) -> Tuple[bool, str]:
    """
    Creates a withdrawal row and deducts from wallet if enough balance.
    Returns (ok, message).
    """
    now = datetime.utcnow().isoformat()
    MIN_WITHDRAWAL = 100.0

    with _lock, _get_conn() as conn:
        cur = conn.cursor()
        _ensure_wallet(cur, user_tg_id)

        cur.execute("SELECT balance FROM wallets WHERE user_tg_id = ?", (user_tg_id,))
        row = cur.fetchone()
        balance = row["balance"] if row else 0.0

        if balance < MIN_WITHDRAWAL:
            return False, f"Minimum withdrawal is ₹{MIN_WITHDRAWAL:.0f}. Current balance: ₹{balance:.2f}"

        if amount > balance:
            return False, f"You cannot withdraw more than your balance (₹{balance:.2f})."

        # deduct
        new_balance = balance - amount
        cur.execute(
            """
            UPDATE wallets
            SET balance = ?, updated_at = ?
            WHERE user_tg_id = ?
            """,
            (new_balance, now, user_tg_id),
        )

        # create withdrawal
        cur.execute(
            """
            INSERT INTO withdrawals (
                user_tg_id, amount, method, account,
                status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, 'pending', ?, ?)
            """,
            (user_tg_id, amount, method, account, now, now),
        )
        wid = cur.lastrowid
        conn.commit()

    return True, f"Withdrawal request #{wid} created for ₹{amount:.2f}"


def get_user_withdrawals(user_tg_id: int) -> List[Dict[str, Any]]:
    with _lock, _get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT * FROM withdrawals
            WHERE user_tg_id = ?
            ORDER BY created_at DESC
            """,
            (user_tg_id,),
        )
        rows = cur.fetchall()
        return [dict(r) for r in rows]


def get_pending_withdrawals() -> List[Dict[str, Any]]:
    with _lock, _get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT * FROM withdrawals
            WHERE status IN ('pending', 'processing')
            ORDER BY created_at ASC
            """
        )
        rows = cur.fetchall()
        return [dict(r) for r in rows]


def set_withdrawal_status(
    withdrawal_id: int,
    status: str,
    external_ref: Optional[str] = None,
) -> None:
    now = datetime.utcnow().isoformat()
    with _lock, _get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE withdrawals
            SET status = ?, external_ref = ?, updated_at = ?
            WHERE id = ?
            """,
            (status, external_ref, now, withdrawal_id),
        )
        conn.commit()


# Initialize DB automatically on import
init_db()
