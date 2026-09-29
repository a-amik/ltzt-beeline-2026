"""Решатель: план проходит те же проверки, что базовый, и не хуже его по целям."""

from bee_routing.baseline import build_baseline
from bee_routing.checks import check_visit, feasible, to_min
from bee_routing.models import Event, Skill
from bee_routing.replan import replan
from bee_routing.solver import solve

from .conftest import needs_data


def _plan(region, **kw):
    data, matrices = region
    plan, _ = solve(data, matrices, time_limit_s=3, **kw)
    return data, matrices, plan


@needs_data
def test_every_assignment_is_feasible(region):
    data, matrices, plan = _plan(region)
    by_id = {req.id: req for req in data.requests}
    engineers = {eng.id: eng for eng in data.engineers}
    seen = set()
    for route in plan.routes:
        engineer = engineers[route.engineer_id]
        previous, clock = "office", to_min(engineer.shift_start)
        for seq, stop in enumerate(route.stops, start=1):
            assert stop.seq == seq
            assert stop.request_id not in seen
            seen.add(stop.request_id)
            req = by_id[stop.request_id]
            checks = check_visit(engineer, req, to_min(stop.arrive), matrices, prev_id=previous)
            assert feasible(checks), f"{route.engineer_id} / {stop.request_id}: {checks}"
            assert stop.late_min == 0 and stop.mode in engineer.transports
            assert to_min(stop.depart_prev) == clock
            brk = 30 if route.break_start and clock <= to_min(route.break_start) < clock + stop.travel_min + 30 else 0
            assert to_min(stop.arrive) in (clock + stop.travel_min, clock + stop.travel_min + brk)
            assert to_min(stop.start) >= to_min(req.window_start)
            assert to_min(stop.start) <= to_min(req.window_end)
            clock, previous = to_min(stop.end), stop.request_id
        assert clock <= to_min(engineer.shift_end)
    assert seen | {u.request_id for u in plan.unassigned} == set(by_id)
    assert plan.algorithm == "solver"


@needs_data
def test_not_worse_than_baseline(region):
    """Первая цель — назначенные заявки, вторая — бригады: решатель не проигрывает базовому."""
    data, matrices, plan = _plan(region)
    base, _ = build_baseline(data, matrices)
    assert plan.metrics.unassigned <= base.metrics.unassigned
    if plan.metrics.unassigned == base.metrics.unassigned:
        assert plan.metrics.engineers_used <= base.metrics.engineers_used


@needs_data
def test_emergencies_start_early(region):
    """Авария — как можно раньше: начинается не позже середины смены, если назначена."""
    data, _, plan = _plan(region)
    by_id = {req.id: req for req in data.requests}
    shift_start = data.engineers[0].shift_start
    starts = [
        to_min(stop.start)
        for route in plan.routes for stop in route.stops
        if by_id[stop.request_id].skill == Skill.EMERGENCY
        and by_id[stop.request_id].window_start == shift_start
    ]
    if starts:
        assert min(starts) <= to_min("12:00")


@needs_data
def test_unassigned_have_reasons(region):
    _, _, plan = _plan(region)
    for item in plan.unassigned:
        assert item.reason and item.reason_code


@needs_data
def test_replan_with_solver_keeps_started(region):
    data, matrices, plan = _plan(region)
    busy = max(plan.routes, key=lambda r: len(r.stops))
    if not busy.stops:
        return
    event = Event(id="off", type="engineer_off", time="13:00", engineer_id=busy.engineer_id)
    new_plan = replan(plan, data, matrices, event, plan_id="p2")
    assert new_plan.algorithm == "solver" and new_plan.diff is not None
    started = {s.request_id for s in busy.stops if to_min(s.start) < to_min("13:00")}
    assert started <= set(new_plan.diff.frozen_requests)
    route = next(r for r in new_plan.routes if r.engineer_id == busy.engineer_id)
    assert all(to_min(s.start) < to_min("13:00") for s in route.stops)
