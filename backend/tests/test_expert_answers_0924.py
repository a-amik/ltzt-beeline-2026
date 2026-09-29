"""Ответы экспертов Билайна 22 и 24.09.2026: окно «весь день», бригада с выходного, выехавшая бригада.

Правило проекта: поведение меняет настройка или допущение, и тест крутит именно их.
"""

import pytest

from bee_routing import settings
from bee_routing.checks import to_min
from bee_routing.geocode import load_assumptions
from bee_routing.loader import load_dataset, load_matrices
from bee_routing.models import Event
from bee_routing.prepare import window_for
from bee_routing.replan import replan
from bee_routing.solver import solve

from .conftest import REGIONS

pytestmark = pytest.mark.skipif("vostok" not in REGIONS, reason="нужен Восток")


@pytest.fixture(scope="module")
def vostok():
    """План Востока решателем: утром работают не все бригады."""
    data, matrices = load_dataset("vostok"), load_matrices("vostok")
    plan, _ = solve(data, matrices, plan_id="x0")
    on_duty = {r.engineer_id for r in plan.routes if r.stops}
    if len(on_duty) == len(data.engineers):
        pytest.skip("решатель занял всех бригад — проверять нечего")
    return data, matrices, plan, on_duty


def _working(plan):
    return {r.engineer_id for r in plan.routes if r.stops}


def test_all_day_window_stays_as_in_file():
    conf = load_assumptions()
    row = {"Начало": "17.08.2026 0:01", "Окончание": "17.08.2026 23:59"}
    assert window_for(row, conf) == ("00:01", "23:59"), "окно заказчика не подменяется"
    workday = conf["workday"]
    conf["all_day_window"]["to_workday"] = True
    assert window_for(row, conf) == (workday["start"], workday["end"]), "старое поведение — ключом допущений"


@pytest.mark.parametrize("mode", ["local", "full"])
def test_replan_does_not_wake_idle_crews(vostok, mode):
    data, matrices, plan, on_duty = vostok
    accident = next(r for r in load_dataset("yugo-vostok").requests if r.skill.value == "emergency")
    src = data.requests[0]
    req = src.model_copy(update={"id": "x-acc", "skill": accident.skill, "window_start": "13:00", "window_end": "23:59"})
    event = Event(id="e-acc", type="urgent", time="13:00", request=req)
    with settings.use({"options": {"replan_mode": mode, "idle_call": "never"}}):
        after = replan(plan, data, matrices, event, plan_id="x1")
    assert _working(after) <= on_duty, "штатный пересчёт не поднимает бригаду с выходного"
    assert {r.engineer_id for r in after.routes} >= {r.engineer_id for r in plan.routes}, "свободные бригады остаются в плане"


def test_idle_crew_is_called_only_as_escalation(vostok):
    data, matrices, plan, on_duty = vostok
    src = data.requests[0]
    req = src.model_copy(update={
        "id": "x-hot", "lat": data.office.lat, "lon": data.office.lon,
        "priority": src.priority.__class__("urgent"), "window_start": "20:00", "window_end": "20:05",
    })
    event = Event(id="e-hot", type="urgent", time="20:00", request=req)
    base = {"emergency_reaction_min": 0}

    def who(call):
        with settings.use({"options": {**base, "idle_call": call}}):
            after = replan(plan, data, matrices, event, plan_id="x2")
        crew = next((r.engineer_id for r in after.routes for s in r.stops if s.request_id == req.id), None)
        return crew, after.history[-1].note

    crew, _ = who("never")
    if crew is not None:
        pytest.skip("срочную у офиса взяла работающая бригада — эскалация не нужна")
    crew, note = who("accident")
    assert crew is not None and crew not in on_duty, "под срочную зовут бригаду с выходного"
    assert note == "idle_called", "вызов с выходного помечен в событии"


def test_crew_on_the_way_is_not_turned_back(vostok):
    data, matrices, plan, _ = vostok
    route, stop = next(
        (r, s) for r in plan.routes for s in r.stops
        if s.travel_min >= 10 and to_min(s.arrive) - s.travel_min + 5 < to_min(s.start) - 60
    )
    moment = to_min(stop.arrive) - stop.travel_min + 5
    time = f"{moment // 60:02d}:{moment % 60:02d}"
    src = data.requests[0]
    req = src.model_copy(update={"id": "x-way", "priority": src.priority.__class__("urgent"),
                                 "window_start": time, "window_end": "21:00"})
    event = Event(id="e-way", type="urgent", time=time, request=req)
    with settings.use({"options": {"accident_lock_horizon_min": 0, "lock_horizon_min": 0}}):
        after = replan(plan, data, matrices, event, plan_id="x3")
    assert stop.request_id in after.diff.frozen_requests, "визит, к которому бригада уже едет, заморожен"
    kept = next(s for r in after.routes if r.engineer_id == route.engineer_id for s in r.stops
                if s.request_id == stop.request_id)
    assert kept.start == stop.start
