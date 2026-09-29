"""Имитация дня: воспроизводима по зерну, динамика берёт заявок дня не меньше статики."""

from fastapi.testclient import TestClient

from bee_routing.api import app
from bee_routing.models import ScenarioSpec
from bee_routing.simulate import make_events, simulate
from bee_routing.solver import solve

from .conftest import REGIONS, needs_data


@needs_data
def test_events_are_reproducible(region):
    """Одно зерно — одни события; другое — другие."""
    data, matrices = region
    spec = ScenarioSpec(dataset_id=data.id, seed=3, new_requests=3, cancels=1, no_shows=1, time_limit_s=1)
    plan, _ = solve(data, matrices, plan_id="p1", time_limit_s=1)
    first = make_events(data, plan, spec, matrices)
    second = make_events(data, plan, spec, matrices)
    assert [e.model_dump() for e in first] == [e.model_dump() for e in second]
    assert [e.time for e in first] == sorted(e.time for e in first)
    other = make_events(data, plan, spec.model_copy(update={"seed": 4}), matrices)
    assert [e.model_dump() for e in other] != [e.model_dump() for e in first]
    assert sum(1 for e in first if e.type == "new_request") == 3


@needs_data
def test_dynamic_serves_more_intraday_than_static(region):
    """Правило «предложить» берёт сегодня не меньше заявок дня, чем «всё на завтра»."""
    data, matrices = region
    spec = ScenarioSpec(dataset_id=data.id, seed=1, new_requests=4, cancels=1, no_shows=1,
                        reschedules=0, delays=1, policy="direct", time_limit_s=1)
    result = simulate(data, matrices, spec)
    runs = {run.policy: run for run in result.runs}
    assert set(runs) == {"static", "direct"}
    assert runs["static"].kpis["intraday_served"] == 0
    assert runs["static"].kpis["deferred"] >= 4
    assert runs["direct"].kpis["intraday_served"] >= runs["static"].kpis["intraday_served"]
    served = runs["direct"].kpis["intraday_served"]
    deferred_new = sum(1 for d in runs["direct"].plan.deferred if d.request_id.startswith("n"))
    assert served + deferred_new == 4, "каждая заявка дня либо взята, либо явно на завтра"
    assert all(e.outcome for e in runs["direct"].timeline)


def test_simulate_endpoint():
    """POST /simulate отдаёт события, прогоны и подписи показателей."""
    if not REGIONS:
        return
    client = TestClient(app)
    body = {"dataset_id": REGIONS[0], "seed": 2, "new_requests": 2, "cancels": 1, "no_shows": 0,
            "reschedules": 0, "delays": 0, "policy": "offer", "time_limit_s": 1}
    response = client.post("/simulate", json=body)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert {run["policy"] for run in payload["runs"]} == {"static", "offer"}
    assert payload["kpi_labels"] and payload["events"]
    plan_id = payload["runs"][-1]["plan"]["id"]
    engineer_id = payload["runs"][-1]["plan"]["routes"][0]["engineer_id"]
    crew = client.get(f"/plan/{plan_id}/crew/{engineer_id}")
    assert crew.status_code == 200, crew.text
    assert crew.json()["earnings"]["norm_day_min"] > 0
    request_id = payload["runs"][-1]["plan"]["routes"][0]["stops"][0]["request_id"]
    bad = {"mark": {"engineer_id": engineer_id, "request_id": "nope", "kind": "depart", "time": "10:00"}}
    assert client.post(f"/plan/{plan_id}/marks", json=bad).status_code == 409, "чужая заявка не принимается"
    mark = {"mark": {"engineer_id": engineer_id, "request_id": request_id, "kind": "depart", "time": "10:00"}}
    marked = client.post(f"/plan/{plan_id}/marks", json=mark)
    assert marked.status_code == 200 and len(marked.json()["marks"]) == 1
    assert client.post(f"/plan/{plan_id}/marks", json=mark).status_code == 409, "повтор отметки не принимается"
    # Планы имитации в «последний» не попадают: он появляется только с планом основной ветки.
    from bee_routing import api as api_module

    api_module.LATEST.clear()
    assert client.get("/plan/latest").status_code == 404
    built = client.post("/plan", json={"dataset_id": REGIONS[0], "algorithm": "baseline"})
    assert built.status_code == 200
    assert client.get("/plan/latest").json()["id"] == built.json()["id"]
