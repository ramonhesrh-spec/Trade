"""Wachtwoord hashing, JWT sessies en het beperken van inlogpogingen.
Meerdere gebruikers mogelijk, elk met een eigen account, maar geen open
registratie: accounts worden toegevoegd via scripts/create_user.py."""
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt

from app import config, db


def hash_password(plain_password: str) -> str:
    return bcrypt.hashpw(plain_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    if not password_hash:
        return False
    return bcrypt.checkpw(plain_password.encode("utf-8"), password_hash.encode("utf-8"))


def create_session_token(user_id: int) -> str:
    payload = {
        "sub": str(user_id),
        "exp": datetime.now(timezone.utc) + timedelta(hours=config.SESSION_HOURS),
    }
    return jwt.encode(payload, config.JWT_SECRET, algorithm=config.JWT_ALGORITHM)


def verify_session_token(token: str) -> Optional[int]:
    try:
        payload = jwt.decode(token, config.JWT_SECRET, algorithms=[config.JWT_ALGORITHM])
        return int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Beperken van inlogpogingen, per gebruikersnaam
# ---------------------------------------------------------------------------

def is_locked_out(username: str) -> bool:
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=config.LOGIN_LOCKOUT_MINUTES)).isoformat()
    with db.session() as conn:
        row = conn.execute(
            """SELECT COUNT(*) AS n FROM login_attempts
               WHERE username = ? AND success = 0 AND attempted_at > ?""",
            (username, cutoff),
        ).fetchone()
    return row["n"] >= config.MAX_LOGIN_ATTEMPTS


def record_login_attempt(username: str, success: bool, ip_address: str = "") -> None:
    with db.session() as conn:
        conn.execute(
            "INSERT INTO login_attempts (username, attempted_at, success, ip_address) VALUES (?, ?, ?, ?)",
            (username, db.now_iso(), int(success), ip_address),
        )
        if success:
            # Reset historie voor deze gebruiker na een geslaagde login.
            conn.execute("DELETE FROM login_attempts WHERE username = ? AND success = 0", (username,))
