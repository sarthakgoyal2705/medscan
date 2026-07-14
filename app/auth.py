"""Minimal account system: SQLite + PBKDF2 password hashes + session tokens.

No external dependencies. Tokens are stored hashed (SHA-256) so a leaked DB
doesn't leak usable sessions; the raw token lives only in the user's cookie.
"""

import hashlib
import re
import secrets
import sqlite3
import time
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "users.db"
SESSION_DAYS = 30

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init() -> None:
    with _db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                pw_hash BLOB NOT NULL,
                pw_salt BLOB NOT NULL,
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                expires_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS scans (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                source TEXT NOT NULL,
                result TEXT NOT NULL,
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS user_meds (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                brand TEXT NOT NULL,
                salt TEXT NOT NULL,
                salt_keys TEXT NOT NULL,
                added_at INTEGER NOT NULL,
                UNIQUE (user_id, brand)
            );
        """)


def _hash_pw(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class AuthError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def signup(name: str, email: str, password: str) -> str:
    """Create account, return a fresh session token."""
    name, email = name.strip(), email.strip().lower()
    if not name:
        raise AuthError("Please enter your name.")
    if not _EMAIL_RE.match(email):
        raise AuthError("That doesn't look like a valid email address.")
    if len(password) < 6:
        raise AuthError("Password must be at least 6 characters.")
    salt = secrets.token_bytes(16)
    try:
        with _db() as conn:
            cur = conn.execute(
                "INSERT INTO users (name, email, pw_hash, pw_salt, created_at) VALUES (?,?,?,?,?)",
                (name, email, _hash_pw(password, salt), salt, int(time.time())))
            return _new_session(conn, cur.lastrowid)
    except sqlite3.IntegrityError:
        raise AuthError("An account with this email already exists — sign in instead.", 409)


def login(email: str, password: str) -> str:
    """Verify credentials, return a fresh session token."""
    email = email.strip().lower()
    with _db() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if row is None or not secrets.compare_digest(
                _hash_pw(password, row["pw_salt"]), row["pw_hash"]):
            raise AuthError("Wrong email or password.", 401)
        return _new_session(conn, row["id"])


def _new_session(conn: sqlite3.Connection, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    conn.execute("INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?,?,?)",
                 (_token_hash(token), user_id, int(time.time()) + SESSION_DAYS * 86400))
    return token


def user_for_token(token: str | None) -> dict | None:
    if not token:
        return None
    with _db() as conn:
        row = conn.execute(
            "SELECT u.id, u.name, u.email FROM sessions s JOIN users u ON u.id = s.user_id "
            "WHERE s.token_hash = ? AND s.expires_at > ?",
            (_token_hash(token), int(time.time()))).fetchone()
        return dict(row) if row else None


def logout(token: str | None) -> None:
    if token:
        with _db() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))


# --------------------------------------------------------------- history ----

def save_scan(user_id: int, source: str, result: dict) -> int:
    import json
    with _db() as conn:
        cur = conn.execute(
            "INSERT INTO scans (user_id, source, result, created_at) VALUES (?,?,?,?)",
            (user_id, source, json.dumps(result, ensure_ascii=False), int(time.time())))
        return cur.lastrowid


def list_scans(user_id: int) -> list[dict]:
    import json
    with _db() as conn:
        rows = conn.execute(
            "SELECT id, source, result, created_at FROM scans "
            "WHERE user_id = ? ORDER BY id DESC LIMIT 100", (user_id,)).fetchall()
    out = []
    for r in rows:
        res = json.loads(r["result"])
        out.append({
            "id": r["id"],
            "source": r["source"],
            "created_at": r["created_at"],
            "medicines": [m.get("brand") or m.get("query") for m in res.get("medicines", [])],
            "saving": res.get("totals", {}).get("saving", 0),
            "warnings": len(res.get("interactions", [])),
        })
    return out


def get_scan(user_id: int, scan_id: int) -> dict | None:
    import json
    with _db() as conn:
        row = conn.execute("SELECT result FROM scans WHERE id = ? AND user_id = ?",
                           (scan_id, user_id)).fetchone()
    return json.loads(row["result"]) if row else None


def delete_scan(user_id: int, scan_id: int) -> None:
    with _db() as conn:
        conn.execute("DELETE FROM scans WHERE id = ? AND user_id = ?", (scan_id, user_id))


def total_saving(user_id: int) -> float:
    import json
    with _db() as conn:
        rows = conn.execute("SELECT result FROM scans WHERE user_id = ?", (user_id,)).fetchall()
    return round(sum(json.loads(r["result"]).get("totals", {}).get("saving", 0) for r in rows), 2)


# ---------------------------------------------------------- my medicines ----

def add_med(user_id: int, brand: str, salt: str, salt_keys: list[str]) -> None:
    import json
    with _db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO user_meds (user_id, brand, salt, salt_keys, added_at) "
            "VALUES (?,?,?,?,?)",
            (user_id, brand, salt, json.dumps(salt_keys), int(time.time())))


def list_meds(user_id: int) -> list[dict]:
    import json
    with _db() as conn:
        rows = conn.execute(
            "SELECT id, brand, salt, salt_keys FROM user_meds "
            "WHERE user_id = ? ORDER BY brand", (user_id,)).fetchall()
    return [{"id": r["id"], "brand": r["brand"], "salt": r["salt"],
             "salt_keys": json.loads(r["salt_keys"])} for r in rows]


def delete_med(user_id: int, med_id: int) -> None:
    with _db() as conn:
        conn.execute("DELETE FROM user_meds WHERE id = ? AND user_id = ?", (med_id, user_id))


init()
