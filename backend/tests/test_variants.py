"""Варианты ответа на пачку событий и вброс заявки в имитацию."""

from itertools import count

from bee_routing import settings
from bee_routing.models import Event, InjectedRequest, ScenarioSpec
from bee_routing.simulate import make_events
from bee_routing.solver import solve
from bee_routing.variants import variants

from .conftest import needs_data

FAST = {"options": {"time_limit_s": 1}}


@needs_data
def test_batch_gives_three_variants(region):
    """Две новые заявки пачкой: три варианта, на завтра — обе в очереди, разница от плана до пачки."""
    data, matrices = region
    with settings.use(FAST):
        plan, _ = solve(data, matrices, plan_id="p1")
    plan.settings = FAST
    events = []
    for i, base in enumerate(data.requests[:2]):
        fresh = base.model_copy(update={"id": f"nb{i}", "window_start": "15:00", "window_end": "19:00"})
        events.append(Event(id=f"b{i}", type="new_request", time=f"12:{i}0", request=fresh, policy="direct"))
    ids = count(100)
    found = variants(plan, data, matrices, events, lambda: f"v{next(ids)}")
    assert [v.key for v in found] == ["keep", "full", "tomorrow"]
    for v in found:
        assert len(v.requests) == 2
        assert v.placed + v.offered + v.deferred == 2
        assert [e.id for e in v.plan.history[-2:]] == ["b0", "b1"]
    later = found[2]
    assert later.deferred == 2 and later.changed == 0
    assert {d.request_id for d in later.plan.deferred} >= {"nb0", "nb1"}


@needs_data
def test_injected_request_lands_at_its_minute(region):
    """Вброшенная заявка встаёт событием в названную минуту и по названной точке."""
    data, matrices = region
    with settings.use(FAST):
        plan, _ = solve(data, matrices, plan_id="p1")
    base = data.requests[3]
    spec = ScenarioSpec(dataset_id=data.id, new_requests=0, cancels=0, no_shows=0, reschedules=0, delays=0,
                        injected=[InjectedRequest(time="13:10", lat=base.lat, lon=base.lon,
                                                  window_start="15:00", window_end="18:00")])
    events = make_events(data, plan, spec, matrices)
    assert len(events) == 1
    event = events[0]
    assert event.type == "new_request" and event.time == "13:10" and event.request.id == "v1"
    assert (event.request.lat, event.request.window_end) == (base.lat, "18:00")


@needs_data
def test_variants_endpoint_and_adopt():
    """Варианты не подменяют план дня; принятый — подменяет."""
    from fastapi.testclient import TestClient

    from bee_routing.api import app

    from .conftest import REGIONS

    client = TestClient(app)
    dataset_id = REGIONS[0]
    data = client.get(f"/datasets/{dataset_id}").json()
    plan = client.post("/plan", json={"dataset_id": dataset_id, "algorithm": "baseline"}).json()
    fresh = {**data["requests"][0], "id": "n-api", "window_start": "15:00", "window_end": "19:00"}
    events = [{"id": "e1", "type": "new_request", "time": "12:00", "request": fresh, "policy": "direct"}]
    body = client.post("/replan/variants", json={"plan_id": plan["id"], "events": events}).json()
    keys = [v["key"] for v in body["variants"]]
    assert keys == ["keep", "full", "tomorrow"]
    latest = client.get(f"/plan/latest?dataset_id={dataset_id}").json()
    assert latest["id"] == plan["id"], "вариант не становится планом дня, пока его не приняли"
    chosen = body["variants"][2]["plan"]["id"]
    adopted = client.post(f"/plan/{chosen}/adopt").json()
    assert adopted["id"] == chosen
    assert client.get(f"/plan/latest?dataset_id={dataset_id}").json()["id"] == chosen
