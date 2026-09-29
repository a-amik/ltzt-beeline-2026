"""Поиск с запасом: доводка большим соседством и второй решатель PyVRP."""

import pytest

from bee_routing import settings
from bee_routing.checks import to_min
from bee_routing.lns import refine
from bee_routing.portfolio import STRATEGIES, rank
from bee_routing.solver import solve

from .conftest import needs_data

FAST = {"time_limit_s": 2, "portfolio": False}


def _sound(plan, data):
    """Каждый визит — один раз, в своём окне, у бригады с навыком; опозданий нет."""
    by_id = {r.id: r for r in data.requests}
    skills = {e.id: set(e.skills) for e in data.engineers}
    seen = set()
    for route in plan.routes:
        clock = 0
        for stop in route.stops:
            req = by_id[stop.request_id]
            assert stop.request_id not in seen
            seen.add(stop.request_id)
            assert req.skill in skills[route.engineer_id]
            assert to_min(req.window_start) <= to_min(stop.start) <= to_min(req.window_end)
            assert to_min(stop.arrive) >= clock and stop.late_min == 0
            clock = to_min(stop.end)
    assert seen.isdisjoint({u.request_id for u in plan.unassigned})
    assert len(seen) + len(plan.unassigned) == len(data.requests)


@needs_data
def test_lns_never_worse_and_sound(region):
    """Доводка не портит план: ранг не хуже, визиты в окнах, заявки не теряются."""
    data, matrices = region
    with settings.use({"options": FAST}):
        plan, _ = solve(data, matrices, plan_id="a", start="home")
        better = refine(plan, data, matrices, budget_s=30, max_steps=60, plan_id="b")
    assert rank(better) <= rank(plan)
    assert better.timing["lns_steps"] > 0
    _sound(better, data)


@needs_data
def test_lns_is_seeded(region):
    """Одно зерно и одно число шагов — один ответ."""
    data, matrices = region
    with settings.use({"options": FAST}):
        plan, _ = solve(data, matrices, plan_id="a", start="home")
        one = refine(plan.model_copy(deep=True), data, matrices, budget_s=60, max_steps=25, seed=7)
        two = refine(plan.model_copy(deep=True), data, matrices, budget_s=60, max_steps=25, seed=7)
    assert rank(one) == rank(two)
    assert [[s.request_id for s in r.stops] for r in one.routes] == [[s.request_id for s in r.stops] for r in two.routes]


@needs_data
def test_pyvrp_plan_is_sound(region):
    """Второй решатель отдаёт план по тем же правилам: окна, навыки, обед внутри своего окна."""
    pytest.importorskip("pyvrp")
    assert "PYVRP" not in STRATEGIES  # в портфель не входит: замер не в его пользу
    data, matrices = region
    with settings.use({"options": {"time_limit_s": 3, "portfolio": False}}):
        plan, _ = solve(data, matrices, plan_id="p", start="home", strategy="PYVRP")
    assert plan.timing.get("pyvrp") == 1
    assert len(plan.unassigned) <= max(3, len(data.requests) // 10)
    _sound(plan, data)
    for route in plan.routes:
        if route.break_start and route.stops:
            b0, b1 = to_min(route.break_start), to_min(route.break_end)
            assert all(to_min(s.end) <= b0 or to_min(s.start) >= b1 for s in route.stops), route.engineer_id


@needs_data
def test_lns_keeps_priority_order_under_scarcity():
    """Надбавка приоритета включена настройкой, бригад не хватает: доводка не меняет аварию на ремонт."""
    from bee_routing.economy import priority_tier
    from bee_routing.loader import load_dataset, load_matrices

    data = load_dataset("yugo-vostok")
    matrices = load_matrices("yugo-vostok")
    full = [e for e in data.engineers if {s.value for s in e.skills} >= {"local", "connect", "emergency"}]
    few = data.model_copy(update={"engineers": full[:3]})
    tier = {r.id: priority_tier(r) for r in data.requests}

    def taken(plan):
        served = {s.request_id for r in plan.routes for s in r.stops}
        return {name: sum(1 for rid in served if tier[rid] == name) for name in ("emergency", "connect", "rest")}

    strict = {"economy": {"priority_bonus_rub": {"emergency": 200000, "connect": 20000}}}
    with settings.use({**strict, "options": {"time_limit_s": 3, "portfolio": False, "start": "home"}}):
        plan, _ = solve(few, matrices, plan_id="s")
        better = refine(plan, few, matrices, budget_s=30, max_steps=80, plan_id="l")
    before, after = taken(plan), taken(better)
    assert plan.unassigned, "бригад должно не хватать, иначе проверять нечего"
    assert rank(better) <= rank(plan)
    assert after["emergency"] >= before["emergency"]
    assert (after["emergency"], after["connect"]) >= (before["emergency"], before["connect"])


def test_buffer_victim_is_least_important_in_chain():
    """Ради запаса из цепочки уходит ремонт, а не подключение, у которого приезд вышел за окно."""
    from types import SimpleNamespace as NS

    from bee_routing.economy import tariffs
    from bee_routing.models import Request
    from bee_routing.risk import Buffer
    from bee_routing.solver import _buffer_victim

    def req(rid, skill, type_bk, we):
        return Request(id=rid, type_bk=type_bk, type_hd="", address="", district="", lat=55.6, lon=37.7,
                       geo_quality="house", duration_min=60, window_start="10:00", window_end=we,
                       priority="normal", skill=skill, transport=None)

    repair, connect = req("a", "local", "Локальная заявка", "12:00"), req("b", "connect", "Подключение", "12:00")
    road = NS(minutes=20)
    visits = [
        (repair, {"arrive": 620, "start": 620, "end": 680, "wait": 0, "late": 0}, road),
        (connect, {"arrive": 700, "start": 700, "end": 760, "wait": 0, "late": 0}, road),
    ]
    buf = Buffer(travel=0.5, work=0.5)  # приезд с запасом: 700 + 10 + 30 + 10 > 720
    assert _buffer_victim(visits, buf, tariffs()) == "a"
    assert _buffer_victim(visits, Buffer(0.0, 0.0), tariffs()) is None
