from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import Cookie, HTTPException, Response

from config import PROJECT_ROOT

DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = Path(os.getenv("WX_AUTH_DB", str(DATA_DIR / "auth.db")))
SECRET_PATH = DATA_DIR / ".secret_key"
SESSION_COOKIE = "wx_session"
SESSION_DAYS = 30
PBKDF2_ITERATIONS = 260_000


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@contextmanager
def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_auth_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                api_key_encrypted TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            )
            """
        )
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(users)").fetchall()
        }
        if "pexels_api_key_encrypted" not in columns:
            conn.execute(
                "ALTER TABLE users ADD COLUMN pexels_api_key_encrypted TEXT NOT NULL DEFAULT ''"
            )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id)")


def _load_secret() -> bytes:
    env_secret = os.getenv("WX_SECRET_KEY", "")
    if env_secret:
        return hashlib.sha256(env_secret.encode("utf-8")).digest()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if SECRET_PATH.exists():
        raw = SECRET_PATH.read_text(encoding="utf-8").strip()
        return base64.urlsafe_b64decode(raw.encode("ascii"))

    secret = secrets.token_bytes(32)
    SECRET_PATH.write_text(base64.urlsafe_b64encode(secret).decode("ascii"), encoding="utf-8")
    try:
        os.chmod(SECRET_PATH, 0o600)
    except OSError:
        pass
    return secret


def _hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
    )
    payload = {
        "alg": "pbkdf2_sha256",
        "iter": PBKDF2_ITERATIONS,
        "salt": base64.b64encode(salt).decode("ascii"),
        "hash": base64.b64encode(digest).decode("ascii"),
    }
    return json.dumps(payload, separators=(",", ":"))


def _verify_password(password: str, stored: str) -> bool:
    try:
        payload = json.loads(stored)
        salt = base64.b64decode(payload["salt"])
        expected = base64.b64decode(payload["hash"])
        iterations = int(payload.get("iter", PBKDF2_ITERATIONS))
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _encrypt_text(value: str) -> str:
    if not value:
        return ""
    secret = _load_secret()
    nonce = secrets.token_bytes(16)
    plaintext = value.encode("utf-8")
    stream = b""
    counter = 0
    while len(stream) < len(plaintext):
        counter += 1
        stream += hmac.new(secret, nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest()
    ciphertext = bytes(a ^ b for a, b in zip(plaintext, stream))
    tag = hmac.new(secret, nonce + ciphertext, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(nonce + tag + ciphertext).decode("ascii")


def _decrypt_text(value: str) -> str:
    if not value:
        return ""
    try:
        raw = base64.urlsafe_b64decode(value.encode("ascii"))
        nonce, tag, ciphertext = raw[:16], raw[16:48], raw[48:]
        secret = _load_secret()
        expected = hmac.new(secret, nonce + ciphertext, hashlib.sha256).digest()
        if not hmac.compare_digest(tag, expected):
            return ""
        stream = b""
        counter = 0
        while len(stream) < len(ciphertext):
            counter += 1
            stream += hmac.new(secret, nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest()
        plaintext = bytes(a ^ b for a, b in zip(ciphertext, stream))
        return plaintext.decode("utf-8")
    except Exception:
        return ""


def _public_user(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "username": row["username"],
        "role": row["role"],
        "has_api_key": bool(row["api_key_encrypted"]),
        "has_pexels_api_key": bool(row["pexels_api_key_encrypted"]),
    }


def create_user(username: str, password: str) -> dict[str, Any]:
    init_auth_db()
    username = username.strip()
    if not re_valid_username(username):
        raise HTTPException(status_code=400, detail="用户名需为 3-32 位字母、数字、下划线或短横线")
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="密码至少 8 位")

    with _connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        role = "admin" if count == 0 else "user"
        try:
            cur = conn.execute(
                "INSERT INTO users (username, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
                (username, _hash_password(password), role, _iso(_utcnow())),
            )
        except sqlite3.IntegrityError:
            raise HTTPException(status_code=409, detail="用户名已存在")
        row = conn.execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _public_user(row)


def re_valid_username(username: str) -> bool:
    if not 3 <= len(username) <= 32:
        return False
    return all(ch.isalnum() or ch in {"_", "-"} for ch in username)


def authenticate_user(username: str, password: str) -> dict[str, Any] | None:
    init_auth_db()
    with _connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username.strip(),)).fetchone()
    if not row or not _verify_password(password, row["password_hash"]):
        return None
    return _public_user(row)


def create_session(response: Response, user_id: int) -> None:
    init_auth_db()
    token = secrets.token_urlsafe(32)
    now = _utcnow()
    expires = now + timedelta(days=SESSION_DAYS)
    with _connect() as conn:
        conn.execute(
            "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (_token_hash(token), user_id, _iso(now), _iso(expires)),
        )
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_DAYS * 24 * 60 * 60,
        httponly=True,
        samesite="lax",
        secure=os.getenv("WX_COOKIE_SECURE", "").lower() in {"1", "true", "yes"},
    )


def clear_session(response: Response, token: str = "") -> None:
    init_auth_db()
    if token:
        with _connect() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))
    response.delete_cookie(SESSION_COOKIE)


def get_current_user(wx_session: str = Cookie(default="")) -> dict[str, Any]:
    init_auth_db()
    if not wx_session:
        raise HTTPException(status_code=401, detail="请先登录")
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT users.* FROM sessions
            JOIN users ON users.id = sessions.user_id
            WHERE sessions.token_hash = ? AND sessions.expires_at > ?
            """,
            (_token_hash(wx_session), _iso(_utcnow())),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="登录已过期")
    return _public_user(row)


def require_admin_user(user: dict[str, Any]) -> dict[str, Any]:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


def save_user_api_key(user_id: int, api_key: str) -> None:
    init_auth_db()
    api_key = api_key.strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="请填写硅基流动 API Key")
    if len(api_key) < 20 or not re_valid_api_key(api_key):
        raise HTTPException(status_code=400, detail="硅基流动 API Key 格式不正确")
    with _connect() as conn:
        conn.execute(
            "UPDATE users SET api_key_encrypted = ? WHERE id = ?",
            (_encrypt_text(api_key), user_id),
        )


def get_user_api_key(user_id: int) -> str:
    init_auth_db()
    with _connect() as conn:
        row = conn.execute("SELECT api_key_encrypted FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row:
        return ""
    return _decrypt_text(row["api_key_encrypted"])


def re_valid_api_key(api_key: str) -> bool:
    allowed = {"-", "_", "."}
    return all(ch.isalnum() or ch in allowed for ch in api_key)


def save_user_pexels_api_key(user_id: int, api_key: str) -> None:
    init_auth_db()
    api_key = api_key.strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="请填写 Pexels API Key")
    if len(api_key) < 20 or not re_valid_api_key(api_key):
        raise HTTPException(status_code=400, detail="Pexels API Key 格式不正确")
    with _connect() as conn:
        conn.execute(
            "UPDATE users SET pexels_api_key_encrypted = ? WHERE id = ?",
            (_encrypt_text(api_key), user_id),
        )


def get_user_pexels_api_key(user_id: int) -> str:
    init_auth_db()
    with _connect() as conn:
        row = conn.execute(
            "SELECT pexels_api_key_encrypted FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    if not row:
        return ""
    return _decrypt_text(row["pexels_api_key_encrypted"])
