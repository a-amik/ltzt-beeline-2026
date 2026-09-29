"""Вход на стенд: пара логин/пароль выдаёт cookie с секретом, неверная — 401."""

from fastapi.testclient import TestClient

from bee_routing import access
from bee_routing.api import app


def _env(monkeypatch, mode="guest"):
    monkeypatch.setenv("BEE_MODE", mode)
    monkeypatch.setenv("BEE_AUTH_LOGIN", "team")
    monkeypatch.setenv("BEE_AUTH_HASH", access.make_hash("s3cret", iterations=1000))
    monkeypatch.setenv("BEE_AUTH_TOKEN", "tok-123")
    monkeypatch.setattr(access.time, "sleep", lambda _s: None)


def test_mode_defaults_to_local(monkeypatch):
    monkeypatch.delenv("BEE_MODE", raising=False)
    assert TestClient(app).get("/auth/me").json() == {"mode": "local", "login": False}


def test_login_sets_secret_cookie(monkeypatch):
    _env(monkeypatch)
    client = TestClient(app)
    assert client.get("/auth/me").json()["mode"] == "guest"
    resp = client.post("/auth/login", json={"login": "team", "password": "s3cret"})
    assert resp.status_code == 200
    cookie = resp.headers["set-cookie"]
    assert "bee_auth=tok-123" in cookie and "HttpOnly" in cookie and "Secure" in cookie


def test_wrong_password_or_login_is_refused(monkeypatch):
    _env(monkeypatch)
    client = TestClient(app)
    for login, password in (("team", "nope"), ("other", "s3cret"), ("", "")):
        resp = client.post("/auth/login", json={"login": login, "password": password})
        assert resp.status_code == 401
        assert "set-cookie" not in resp.headers


def test_no_configuration_means_no_login(monkeypatch):
    for name in ("BEE_AUTH_LOGIN", "BEE_AUTH_HASH", "BEE_AUTH_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(access.time, "sleep", lambda _s: None)
    assert TestClient(app).post("/auth/login", json={"login": "", "password": ""}).status_code == 401


def test_logout_clears_cookie(monkeypatch):
    _env(monkeypatch)
    resp = TestClient(app).post("/auth/logout")
    assert 'bee_auth=""' in resp.headers["set-cookie"] or "Max-Age=0" in resp.headers["set-cookie"]
