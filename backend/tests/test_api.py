"""API по контракту: список регионов, план, перепланирование."""

from fastapi.testclient import TestClient

from bee_routing.api import app

from .conftest import REGIONS, needs_data

client = TestClient(app)


@needs_data
def test_datasets_list():
    """GET /datasets отдаёт три участка заказчика и «Вся Москва» — набор из них, со счётчиками."""
    body = client.get("/datasets").json()
    assert {item["id"] for item in body if item["source"] == "customer"} == set(REGIONS) | {"moskva"}
    assert all(item["requests_count"] and item["engineers_count"] for item in body)


@needs_data
def test_dataset_and_plan():
    """GET /datasets/{id} и POST /plan отвечают по контракту."""
    dataset_id = REGIONS[0]
    data = client.get(f"/datasets/{dataset_id}").json()
    assert data["office"]["lat"] and data["requests"] and data["engineers"]

    plan = client.post("/plan", json={"dataset_id": dataset_id, "algorithm": "baseline"}).json()
    assert plan["algorithm"] == "baseline"
    assert set(plan["metrics"]) == {
        "engineers_used", "distance_km", "travel_min", "unassigned", "late", "changed_requests",
        "risk_late", "risky_stops",
    }
    assert plan["diff"] is None

    solver = client.post("/plan", json={"dataset_id": dataset_id, "algorithm": "solver"}).json()
    assert solver["algorithm"] == "solver"
    assert solver["metrics"]["unassigned"] <= plan["metrics"]["unassigned"]

    event = data["events"][0]
    replanned = client.post("/replan", json={"plan_id": plan["id"], "event": event}).json()
    assert replanned["diff"]["event"]["id"] == event["id"]
    assert replanned["diff"]["frozen_requests"]


def test_unknown_dataset():
    """Неизвестный регион — 404, а не пятисотая."""
    assert client.get("/datasets/net-takogo").status_code == 404
    assert client.post("/replan", json={"plan_id": "p999", "event": {"id": "x", "type": "cancel", "time": "13:00"}}).status_code == 404


def test_settings_schema_and_compare(client_or_skip=None):
    """Форма настроек отдаётся, сравнение считает три плана с настройками из запроса."""
    from fastapi.testclient import TestClient

    from bee_routing.api import app
    from bee_routing.loader import dataset_ids

    if not dataset_ids():
        return
    client = TestClient(app)
    form = client.get("/settings").json()
    paths = {f["path"] for group in form["schema"] for f in group["fields"]}
    assert "economy.bonus_multiplier" in paths and "options.modes" in paths
    assert form["defaults"]["economy"]["norm_day_min"] > 0
    body = {"dataset_id": "yugocentr", "settings": {"options": {"time_limit_s": 2, "breaks": False},
                                                     "economy": {"bonus_multiplier": 99}}}
    result = client.post("/compare", json=body).json()
    assert [row["key"] for row in result["rows"]] == ["control", "baseline", "solver", "solver_robust"]
    assert result["kpis"][0]["label"]
    plan = client.post("/plan", json={"dataset_id": "yugocentr", "algorithm": "solver", "settings": body["settings"]}).json()
    assert plan["settings"]["economy"]["bonus_multiplier"] == 5  # обрезано диапазоном схемы
    assert all(route["break_start"] is None for route in plan["routes"])
