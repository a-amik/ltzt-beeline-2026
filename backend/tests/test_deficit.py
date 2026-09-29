"""Карта дефицита: районы × окна, давление, подсказки; цена заявки в остановке."""

from fastapi.testclient import TestClient

from bee_routing import settings
from bee_routing.api import app
from bee_routing.deficit import deficit_map, plural
from bee_routing.solver import solve

from .conftest import REGIONS, needs_data

FAST = {"options": {"time_limit_s": 1, "portfolio": False}}


def test_plural():
    assert [plural(n, "заявка", "заявки", "заявок") for n in (1, 2, 5, 11, 21, 104)] == [
        "заявка", "заявки", "заявок", "заявок", "заявка", "заявки"]


@needs_data
def test_deficit_shape_and_consistency(region):
    """Каждая заявка плана в своём районе; спрос района сходится с нормо-минутами; уровни по давлению."""
    data, matrices = region
    with settings.use(FAST):
        plan, _ = solve(data, matrices, plan_id="p")
        result = deficit_map(plan, data)
    assert result.windows and all(len(a.slots) == len(result.windows) for a in result.areas)
    requests = {s.request_id for r in plan.routes for s in r.stops} | {u.request_id for u in plan.unassigned}
    assert sum(a.requests for a in result.areas) == len(requests)
    for area in result.areas:
        for cell in area.slots:
            if cell.unassigned:
                assert cell.level == "deficit"
            if cell.level == "free":
                assert cell.pressure < 0.5 and cell.free_min >= 60
    unassigned_cells = sum(c.unassigned for a in result.areas for c in a.slots)
    assert unassigned_cells >= len(plan.unassigned)
    for item in result.advice:
        assert item.text.startswith(("Не обещать", "Продавать", "По региону"))


@needs_data
def test_stop_values_are_priced(region):
    """У остановок плана проставлена ценность заявки — показ считает деньги по ней."""
    data, matrices = region
    with settings.use(FAST):
        plan, _ = solve(data, matrices, plan_id="p")
    values = [s.value_rub for r in plan.routes for s in r.stops]
    assert values and all(v > 0 for v in values)


def test_deficit_endpoint_by_body():
    """POST /deficit считает по присланному плану: сервер может его и не помнить."""
    if not REGIONS:
        return
    client = TestClient(app)
    plan = client.post("/plan", json={"dataset_id": REGIONS[0], "algorithm": "baseline"}).json()
    from bee_routing import api as api_module

    api_module.PLANS.clear()
    response = client.post("/deficit", json={"plan": plan})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["plan_id"] == plan["id"] and body["areas"] and body["totals"]
