"""Вход на стенд: гостевой режим на обезличенном наборе и данные задания за паролем.

Стенд держит два экземпляра API. Гостевой читает обезличенный набор, боевой —
данные задания (своя папка `BEE_DATA_DIR`). Какой из них ответит, решает
nginx по cookie `bee_auth`: её значение — секрет `BEE_AUTH_TOKEN`, и выдаёт
его только вход с верной парой логин/пароль. Без cookie боевой экземпляр
недостижим, поэтому данные задания не уходят гостю ни одним запросом.

GET  /auth/me     — режим этого экземпляра: guest, real или local (разработка)
POST /auth/login  — {login, password} → cookie на 30 дней
POST /auth/logout — стереть cookie

Переменные окружения: `BEE_MODE` (guest | real; нет — local, вход не нужен),
`BEE_AUTH_LOGIN`, `BEE_AUTH_HASH` (`pbkdf2_sha256$итерации$соль$хеш`),
`BEE_AUTH_TOKEN`. Хеш пароля: `uv run python -m bee_routing.access` и пароль
в stdin.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sys
import time

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

COOKIE = "bee_auth"
MAX_AGE = 30 * 24 * 3600
ITERATIONS = 200_000

router = APIRouter()


class Credentials(BaseModel):
    login: str
    password: str


def mode() -> str:
    """guest — гостевой экземпляр стенда, real — за входом, local — разработка."""
    value = os.environ.get("BEE_MODE", "").strip().lower()
    return value if value in ("guest", "real") else "local"


def make_hash(password: str, salt: str | None = None, iterations: int = ITERATIONS) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), iterations).hex()
    return f"pbkdf2_sha256${iterations}${salt}${digest}"


def check(login: str, password: str) -> bool:
    """Пара совпала с заданной в окружении; нет настройки — входа нет вовсе."""
    want_login = os.environ.get("BEE_AUTH_LOGIN", "")
    stored = os.environ.get("BEE_AUTH_HASH", "")
    try:
        _, iterations, salt, _digest = stored.split("$")
    except ValueError:
        return False
    same_login = hmac.compare_digest(login.strip().encode(), want_login.encode())
    same_pass = hmac.compare_digest(make_hash(password, salt, int(iterations)).encode(), stored.encode())
    return bool(want_login) and same_login and same_pass


@router.get("/auth/me")
def me() -> dict:
    return {"mode": mode(), "login": mode() in ("guest", "real")}


@router.post("/auth/login")
def login(body: Credentials, response: Response) -> dict:
    token = os.environ.get("BEE_AUTH_TOKEN", "")
    if not token or not check(body.login, body.password):
        time.sleep(1.0)  # перебор пароля — не быстрее раза в секунду на запрос
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")
    response.set_cookie(COOKIE, token, max_age=MAX_AGE, httponly=True, samesite="lax",
                        secure=os.environ.get("BEE_AUTH_INSECURE") != "1", path="/")
    return {"mode": "real"}


@router.post("/auth/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(COOKIE, path="/")
    return {"mode": "guest"}


if __name__ == "__main__":
    print(make_hash(sys.stdin.readline().rstrip("\n")))
