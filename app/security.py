"""Wachtwoord hashing, JWT sessies en het beperken van inlogpogingen.
Eén vaste gebruiker, geen open registratie."""
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app import config, db


def hash_password(plain_password: str) -> str:
    return bcrypt.hashpw(plain_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    if not password_hash:
        return False
    return bcrypt.checkpw(plain_password.encode("utf-8"), password_hash.encode("utf-8"))


def create_session_token(username: str) -> str:
    payload = {
        "sub": username,
        "exp": datetime.now(timezone.utc) + timedelta(hours=config.SESSION_HOURS),
    }
    return jwt.encode(payload, config.JWT_SECRET, algorithm=config.JWT_ALGORITHM)


def verify_session_token(token: str) -> bool:
    try:
        payload = jwt.decode(token, config.JWT_SECRET, algorithms=[config.JWT_ALGORITHM])
    except jwt.PyJWTError:
        return False
    return payload.get("sub") == config.DASHBOARD_USERNAME


# ---------------------------------------------------------------------------
# Beperken van inlogpogingen
# ---------------------------------------------------------------------------

def is_locked_out() -> bool:
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=config.LOGIN_LOCKOUT_MINUTES)).isoformat()
    with db.session() as conn:
        row = conn.execute(
            """SELECT COUNT(*) AS n FROM login_attempts
               WHERE success = 0 AND attempted_at > ?""",
            (cutoff,),
        ).fetchone()
    return row["n"] >= config.MAX_LOGIN_ATTEMPTS


def record_login_attempt(success: bool, ip_address: str = "") -> None:
    with db.session() as conn:
        conn.execute(
            "INSERT INTO login_attempts (attempted_at, success, ip_address) VALUES (?, ?, ?)",
            (db.now_iso(), int(success), ip_address),
        )
        if success:
            # Reset historie na een geslaagde login.
            conn.execute("DELETE FROM login_attempts WHERE success = 0")
