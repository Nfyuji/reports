# -*- coding: utf-8 -*-
"""إدارة المستخدمين والاشتراكات ومساحات العمل المنفصلة."""

from __future__ import annotations

import secrets
import sqlite3
import string
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator

import os
import secrets
import sqlite3
import string
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator

# على Render ضع Persistent Disk على /var/data وEnvironment: DATA_DIR=/var/data
BASE = Path(__file__).resolve().parent
DATA_ROOT = Path(os.environ.get("DATA_DIR", str(BASE)))
DATA_DIR = DATA_ROOT / "data"
USERS_DIR = DATA_ROOT / "users"
MASTER_DIR = DATA_ROOT / "master_templates"
DB_PATH = DATA_DIR / "app.db"

# كلمة مرور لوحة الإدارة (يمكن تغييرها من الواجهة لاحقاً عبر الإعدادات)
DEFAULT_ADMIN_PASSWORD = "admin2026"


@dataclass
class User:
    id: int
    access_code: str
    display_name: str
    expires_at: str  # ISO date YYYY-MM-DD
    active: int
    created_at: str
    last_login_at: str | None

    @property
    def expired(self) -> bool:
        try:
            return datetime.strptime(self.expires_at, "%Y-%m-%d").date() < datetime.now().date()
        except ValueError:
            return True

    @property
    def days_left(self) -> int:
        try:
            exp = datetime.strptime(self.expires_at, "%Y-%m-%d").date()
            return (exp - datetime.now().date()).days
        except ValueError:
            return 0

    @property
    def workspace(self) -> Path:
        return USERS_DIR / str(self.id)


def ensure_dirs() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    USERS_DIR.mkdir(exist_ok=True)
    MASTER_DIR.mkdir(exist_ok=True)


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    ensure_dirs()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    ensure_dirs()
    with db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                access_code TEXT NOT NULL UNIQUE,
                display_name TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                last_login_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        row = conn.execute("SELECT value FROM settings WHERE key='admin_password'").fetchone()
        if not row:
            conn.execute(
                "INSERT INTO settings(key, value) VALUES('admin_password', ?)",
                (DEFAULT_ADMIN_PASSWORD,),
            )


def get_admin_password() -> str:
    init_db()
    with db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key='admin_password'").fetchone()
        return row["value"] if row else DEFAULT_ADMIN_PASSWORD


def is_default_admin_password() -> bool:
    return get_admin_password() == DEFAULT_ADMIN_PASSWORD


def set_admin_password(password: str) -> None:
    password = (password or "").strip()
    if len(password) < 6:
        raise ValueError("كلمة المرور يجب أن تكون 6 أحرف على الأقل")
    with db() as conn:
        conn.execute(
            "INSERT INTO settings(key, value) VALUES('admin_password', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (password,),
        )
        conn.execute(
            "INSERT INTO settings(key, value) VALUES('admin_password_changed', '1') "
            "ON CONFLICT(key) DO UPDATE SET value='1'"
        )


def change_admin_password(current: str, new_password: str) -> None:
    if current != get_admin_password():
        raise ValueError("كلمة المرور الحالية غير صحيحة")
    set_admin_password(new_password)


def set_gemini_api_key(key: str) -> None:
    init_db()
    with db() as conn:
        conn.execute(
            "INSERT INTO settings(key, value) VALUES('gemini_api_key', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ((key or "").strip(),),
        )


def get_setting(key: str, default: str = "") -> str:
    init_db()
    with db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default


def generate_access_code() -> str:
    """رقم اشتراك مثل: 48291763"""
    alphabet = string.digits
    while True:
        code = "".join(secrets.choice(alphabet) for _ in range(8))
        if not code.startswith("0"):
            with db() as conn:
                exists = conn.execute(
                    "SELECT 1 FROM users WHERE access_code=?", (code,)
                ).fetchone()
            if not exists:
                return code


def _row_to_user(row: sqlite3.Row) -> User:
    return User(
        id=row["id"],
        access_code=row["access_code"],
        display_name=row["display_name"],
        expires_at=row["expires_at"],
        active=row["active"],
        created_at=row["created_at"],
        last_login_at=row["last_login_at"],
    )


def create_user(display_name: str, months: int = 1) -> User:
    init_db()
    months = max(1, int(months))
    code = generate_access_code()
    now = datetime.now()
    expires = (now + timedelta(days=30 * months)).strftime("%Y-%m-%d")
    with db() as conn:
        cur = conn.execute(
            """
            INSERT INTO users(access_code, display_name, expires_at, active, created_at)
            VALUES (?, ?, ?, 1, ?)
            """,
            (code, display_name.strip() or "مستخدم", expires, now.strftime("%Y-%m-%d %H:%M")),
        )
        user_id = cur.lastrowid
    user = get_user_by_id(user_id)
    assert user is not None
    provision_workspace(user)
    return user


def renew_user(user_id: int, months: int = 1) -> User | None:
    months = max(1, int(months))
    user = get_user_by_id(user_id)
    if not user:
        return None
    base = datetime.now().date()
    try:
        current_exp = datetime.strptime(user.expires_at, "%Y-%m-%d").date()
        if current_exp > base:
            base = current_exp
    except ValueError:
        pass
    new_exp = (base + timedelta(days=30 * months)).strftime("%Y-%m-%d")
    with db() as conn:
        conn.execute(
            "UPDATE users SET expires_at=?, active=1 WHERE id=?",
            (new_exp, user_id),
        )
    return get_user_by_id(user_id)


def set_user_active(user_id: int, active: bool) -> None:
    with db() as conn:
        conn.execute("UPDATE users SET active=? WHERE id=?", (1 if active else 0, user_id))


def list_users() -> list[User]:
    init_db()
    with db() as conn:
        rows = conn.execute("SELECT * FROM users ORDER BY id DESC").fetchall()
    return [_row_to_user(r) for r in rows]


def get_user_by_id(user_id: int) -> User | None:
    with db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    return _row_to_user(row) if row else None


def get_user_by_code(access_code: str) -> User | None:
    code = (access_code or "").strip()
    with db() as conn:
        row = conn.execute("SELECT * FROM users WHERE access_code=?", (code,)).fetchone()
    return _row_to_user(row) if row else None


def touch_login(user_id: int) -> None:
    with db() as conn:
        conn.execute(
            "UPDATE users SET last_login_at=? WHERE id=?",
            (datetime.now().strftime("%Y-%m-%d %H:%M"), user_id),
        )


def authenticate(access_code: str) -> tuple[User | None, str | None]:
    """يرجع (user, error_message)."""
    init_db()
    user = get_user_by_code(access_code)
    if not user:
        return None, "رقم الاشتراك غير صحيح"
    if not user.active:
        return None, "هذا الحساب موقوف. تواصل مع الإدارة."
    if user.expired:
        return None, "انتهى الاشتراك. جدّد الاشتراك الشهري للمتابعة."
    touch_login(user.id)
    provision_workspace(user)
    return user, None


def master_template_path() -> Path | None:
    ensure_dirs()
    files = sorted(
        [p for p in MASTER_DIR.glob("*.pptx") if not p.name.startswith("~$")],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if files:
        return files[0]
    # احتياطي: من جذر المشروع
    root_files = sorted(
        [
            p
            for p in BASE.glob("*.pptx")
            if not p.name.startswith("~$")
            and not p.name.startswith("_")
            and "تقرير" in p.name
        ],
        key=lambda p: p.stat().st_size,
        reverse=True,
    )
    if root_files:
        # انسخه كقالب رئيسي مرة واحدة
        dest = MASTER_DIR / "قالب_التقرير_الفني.pptx"
        if not dest.exists():
            import shutil

            shutil.copy2(root_files[0], dest)
        return dest
    return None


def provision_workspace(user: User) -> Path:
    """ينشئ مجلد المستخدم وينسخ القالب إذا كانت أول مرة."""
    import shutil

    ws = user.workspace
    ws.mkdir(parents=True, exist_ok=True)
    report = ws / "report.pptx"
    if not report.exists():
        master = master_template_path()
        if not master or not master.exists():
            raise FileNotFoundError("لا يوجد قالب رئيسي لنسخه للمستخدم.")
        shutil.copy2(master, report)
    return report


def user_report_path(user: User) -> Path:
    path = provision_workspace(user)
    return path
