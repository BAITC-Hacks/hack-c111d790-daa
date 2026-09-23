"""Local password accounts and revocable, opaque cookie sessions for the shared workspace."""

import hashlib
import hmac
import re
import secrets
import sqlite3
import time
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import Field, field_validator, model_validator

from . import storage
from .schemas import StrictModel

router = APIRouter(prefix="/api/auth", tags=["Accounts"])
COOKIE = "waresync_session"
SESSION_SECONDS = 7 * 24 * 60 * 60


class Credentials(StrictModel):
    email: str = Field(max_length=254)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        value = value.strip().lower()
        if not re.fullmatch(r"[^\s@]+@[^\s@.]+(?:\.[^\s@.]+)+", value):
            raise ValueError("Введите корректный email")
        return value


class Profile(StrictModel):
    name: str = Field(min_length=2, max_length=80)
    job_title: str = Field(default="Менеджер закупок", max_length=80)

    @field_validator("name", "job_title", mode="before")
    @classmethod
    def strip_text(cls, value):
        return value.strip() if isinstance(value, str) else value


class Registration(Credentials, Profile):
    password_confirmation: str = Field(max_length=128)

    @model_validator(mode="after")
    def check_password(self):
        if (
            len(self.password) < 8
            or not any(c.isalpha() for c in self.password)
            or not any(c.isdigit() for c in self.password)
        ):
            raise ValueError("Пароль: минимум 8 символов, хотя бы одна буква и одна цифра")
        if self.password != self.password_confirmation:
            raise ValueError("Пароли не совпадают")
        return self


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(
        password.encode(), salt=bytes.fromhex(salt), n=2**17, r=8, p=1, maxmem=256 * 1024 * 1024
    ).hex()
    return f"scrypt${salt}${digest}"


def password_matches(password: str, encoded: str) -> bool:
    return hmac.compare_digest(hash_password(password, encoded.split("$")[1]), encoded)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def public_user(row) -> dict:
    return {key: row[key] for key in ("id", "email", "name", "job_title", "created_at")}


def session_user(request: Request) -> dict | None:
    token = request.cookies.get(COOKIE)
    if not token or len(token) > 128:
        return None
    with storage.db() as db:
        row = db.execute(
            "SELECT users.* FROM sessions JOIN users ON users.id = sessions.user_id "
            "WHERE token_hash = ? AND expires_at > ?",
            (token_hash(token), time.time()),
        ).fetchone()
    return public_user(row) if row else None


def start_session(request: Request, response: Response, user_id: str):
    token = secrets.token_urlsafe(32)
    with storage.db() as db:
        db.execute("DELETE FROM sessions WHERE expires_at <= ?", (time.time(),))
        old = request.cookies.get(COOKIE)
        if old:
            db.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash(old),))
        db.execute(
            "INSERT INTO sessions VALUES (?, ?, ?)",
            (token_hash(token), user_id, time.time() + SESSION_SECONDS),
        )
    response.set_cookie(
        COOKIE,
        token,
        max_age=SESSION_SECONDS,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="strict",
        path="/",
    )


def check_rate_limit(request: Request):
    address = request.client.host if request.client else "local"
    with storage.db() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("DELETE FROM auth_attempts WHERE attempted_at < ?", (time.time() - 600,))
        count = db.execute("SELECT COUNT(*) FROM auth_attempts WHERE address = ?", (address,)).fetchone()[0]
        if count >= 10:
            raise HTTPException(429, "Слишком много попыток. Попробуйте через 10 минут.")
        db.execute("INSERT INTO auth_attempts VALUES (?, ?)", (address, time.time()))


@router.post("/register", status_code=201)
def register(data: Registration, request: Request, response: Response):
    check_rate_limit(request)
    user = dict(
        id=uuid4().hex, email=data.email, name=data.name, job_title=data.job_title, created_at=storage.now()
    )
    encoded = hash_password(data.password)
    try:
        with storage.db() as db:
            db.execute(
                "INSERT INTO users VALUES (?, ?, ?, ?, ?, ?)",
                (user["id"], data.email, data.name, data.job_title, encoded, user["created_at"]),
            )
    except sqlite3.IntegrityError:
        raise HTTPException(409, "Этот email уже зарегистрирован. Войдите в аккаунт.") from None
    start_session(request, response, user["id"])
    return user


@router.post("/login")
def login(data: Credentials, request: Request, response: Response):
    check_rate_limit(request)
    with storage.db() as db:
        user = db.execute("SELECT * FROM users WHERE email = ?", (data.email,)).fetchone()
    # Perform the same expensive operation for unknown emails, too.
    encoded = user["password_hash"] if user else f"scrypt${'0' * 32}${'0' * 128}"
    if not password_matches(data.password, encoded) or not user:
        raise HTTPException(401, "Неверный email или пароль")
    with storage.db() as db:
        db.execute(
            "DELETE FROM auth_attempts WHERE address = ?",
            (request.client.host if request.client else "local",),
        )
    start_session(request, response, user["id"])
    return public_user(user)


@router.get("/me")
def me(request: Request):
    return request.state.user


@router.post("/profile")
def update_profile(data: Profile, request: Request):
    user = request.state.user
    with storage.db() as db:
        db.execute(
            "UPDATE users SET name = ?, job_title = ? WHERE id = ?", (data.name, data.job_title, user["id"])
        )
    return {**user, **data.model_dump()}


@router.post("/logout")
def logout(request: Request, response: Response):
    with storage.db() as db:
        db.execute(
            "DELETE FROM sessions WHERE token_hash = ?", (token_hash(request.cookies.get(COOKIE, "")),)
        )
    response.delete_cookie(COOKIE, path="/", httponly=True, samesite="strict")
    return {"ok": True}
