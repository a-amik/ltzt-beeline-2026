"""Проверки каркаса: расстояние по прямой и живость сервиса."""

from fastapi.testclient import TestClient

from bee_routing.api import app
from bee_routing.distance import haversine_km


def test_haversine_moscow_spb():
    """Расстояние Москва — Санкт-Петербург по прямой — около 635 км."""
    km = haversine_km(55.7558, 37.6173, 59.9311, 30.3609)
    assert 600 < km < 700


def test_health():
    """GET /health отвечает, что сервис жив."""
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
