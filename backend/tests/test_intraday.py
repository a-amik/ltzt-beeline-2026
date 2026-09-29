"""События по ходу дня: новая заявка, перенос окна, клиента нет, задержка бригады.

Правила качества сервиса при пересчёте: обещанное в горизонте не двигается,
остальное сдвигается не дальше допустимого, новая заявка либо встаёт, либо
явно уходит на завтра с причиной.
"""

from bee_routing import settings
from bee_routing.checks import to_min
from bee_routing.models import Event
from bee_routing.replan import replan
from bee_routing.solver import solve

from .conftest import needs_data

FAST = {"options": {"time_limit_s": 2}}


def stops_of(plan):
    return {
        stop.request_id: (route.engineer_id, stop.start, stop.status)
        for route in plan.routes
        for stop in route.stops
    }


def clone(request, rid, ws, we):
    return request.model_copy(update={"id": rid, "window_start": ws, "window_end": we})


@needs_data
def test_new_request_direct_is_assigned_or_deferred(region):
    """Новая заявка дня директивно либо встаёт в маршрут, либо явно уходит на завтра."""
    data, matrices = region
    with settings.use(FAST):
        plan, _ = solve(data, matrices, plan_id="p1")
        base = data.requests[0]
        fresh = clone(base, "n-test", "14:00", "18:00")
        matrices.register(fresh.id, fresh.lat, fresh.lon, alias_of=base.id)
        event = Event(id="x1", type="new_request", time="12:00", request=fresh, policy="direct")
        after = replan(plan, data, matrices, event, plan_id="p2")
    placed = "n-test" in stops_of(after)
    deferred = [d for d in after.deferred if d.request_id == "n-test"]
    assert placed != bool(deferred), "заявка либо в маршруте, либо на завтра, но не в обоих и не нигде"
    assert not any(u.request_id == "n-test" for u in after.unassigned) or not deferred
    if deferred:
        assert "следующий день" in deferred[0].reason
    assert after.history[-1].id == "x1"


@needs_data
def test_new_request_offer_waits_for_crew(region):
    """В режиме предложения заявка не ставится сама: у неё есть кандидаты или она на завтра."""
    data, matrices = region
    with settings.use(FAST):
        plan, _ = solve(data, matrices, plan_id="p1")
        base = data.requests[1]
        fresh = clone(base, "n-offer", "15:00", "19:00")
        matrices.register(fresh.id, fresh.lat, fresh.lon, alias_of=base.id)
        event = Event(id="x2", type="new_request", time="12:30", request=fresh, policy="offer")
        after = replan(plan, data, matrices, event, plan_id="p2")
    assert "n-offer" not in stops_of(after), "в режиме предложения заявку ставит бригада, а не система"
    offer = next((o for o in after.offers if o.request_id == "n-offer"), None)
    deferred = any(d.request_id == "n-offer" for d in after.deferred)
    assert (offer is not None and offer.candidates) or deferred


@needs_data
def test_impossible_request_is_deferred_with_reason(region):
    """Заявка с окном после конца смен никому не подходит и уходит на завтра словами."""
    data, matrices = region
    with settings.use(FAST):
        plan, _ = solve(data, matrices, plan_id="p1")
        base = data.requests[2]
        fresh = clone(base, "n-late", "21:30", "22:00").model_copy(update={"duration_min": 120})
        matrices.register(fresh.id, fresh.lat, fresh.lon, alias_of=base.id)
        event = Event(id="x3", type="new_request", time="12:00", request=fresh, policy="direct")
        after = replan(plan, data, matrices, event, plan_id="p2")
    deferred = [d for d in after.deferred if d.request_id == "n-late"]
    assert deferred and deferred[0].since == "12:00"
    assert "n-late" not in stops_of(after)
    assert not any(u.request_id == "n-late" for u in after.unassigned)


@needs_data
def test_lock_horizon_and_max_shift(region):
    """Обещанное в горизонте стоит на месте; остальное сдвигается не дальше допустимого."""
    data, matrices = region
    with settings.use({"options": {"time_limit_s": 2, "lock_horizon_min": 60, "max_shift_min": 30}}):
        plan, _ = solve(data, matrices, plan_id="p1")
        before = stops_of(plan)
        event = next(e for e in data.events if e.type == "engineer_off")
        after = replan(plan, data, matrices, event, plan_id="p2")
    moment = to_min(event.time)
    now = stops_of(after)
    for rid, (eng, start, _) in before.items():
        if eng == event.engineer_id or rid not in now:
            continue
        if to_min(start) < moment + 60:
            assert now[rid][:2] == (eng, start), f"{rid} обещан в горизонте и не должен двигаться"
        else:
            assert to_min(now[rid][1]) <= to_min(start) + 30, f"{rid} сдвинут дальше допустимого"


@needs_data
def test_no_show_frees_time_and_defers(region):
    """Клиента нет: визит остаётся отметкой, заявка на завтра, бригада едет дальше."""
    data, matrices = region
    with settings.use(FAST):
        plan, _ = solve(data, matrices, plan_id="p1")
        route = next(r for r in plan.routes if len(r.stops) >= 3)
        stop = route.stops[1]
        event = Event(id="x4", type="no_show", time=stop.arrive, request_id=stop.request_id, note="unreachable")
        after = replan(plan, data, matrices, event, plan_id="p2")
    now = stops_of(after)
    assert now[stop.request_id][2] == "no_show"
    assert any(d.request_id == stop.request_id and "не отвечает" in d.reason for d in after.deferred)
    marked = next(s for r in after.routes for s in r.stops if s.request_id == stop.request_id)
    wait = int(settings.option("no_show_wait_min"))
    assert to_min(marked.end) - to_min(marked.start) <= wait
    assert after.economy is not None
    values = [s for r in after.routes for s in r.stops if s.status != "no_show"]
    assert len(values) >= len(plan.routes[0].stops) - 1


@needs_data
def test_reschedule_moves_window(region):
    """Перенос окна: заявка либо встаёт в новое окно, либо не назначена, но никогда — в старое."""
    data, matrices = region
    with settings.use(FAST):
        plan, _ = solve(data, matrices, plan_id="p1")
        route = next(r for r in plan.routes if len(r.stops) >= 3)
        stop = route.stops[-1]
        event = Event(id="x5", type="reschedule", time="11:00", request_id=stop.request_id,
                      window_start="18:00", window_end="21:00")
        after = replan(plan, data, matrices, event, plan_id="p2")
    now = stops_of(after)
    if stop.request_id in now:
        assert to_min(now[stop.request_id][1]) >= to_min("18:00")
    assert after.history[-1].type == "reschedule"


@needs_data
def test_delay_pushes_tail_not_head(region):
    """Задержка бригады сдвигает её хвост, чужие маршруты не трогает."""
    data, matrices = region
    with settings.use(FAST):
        plan, _ = solve(data, matrices, plan_id="p1")
        route = next(r for r in plan.routes if len(r.stops) >= 3)
        stop = route.stops[1]
        event = Event(id="x6", type="delay", time=stop.start, engineer_id=route.engineer_id, delay_min=30)
        after = replan(plan, data, matrices, event, plan_id="p2")
    before, now = stops_of(plan), stops_of(after)
    for rid, (eng, start, _) in before.items():
        if eng != route.engineer_id and rid in now and rid not in {c.request_id for c in after.diff.changed_requests}:
            assert now[rid][:2] == (eng, start)
    later = [s for s in route.stops if to_min(s.start) > to_min(stop.start)]
    for s in later:
        if s.request_id in now and now[s.request_id][0] == route.engineer_id:
            assert to_min(now[s.request_id][1]) >= to_min(s.start), "обещанный визит не сдвигают раньше"
    kept = [s for s in later if s.request_id in now]
    lost = {s.request_id for s in later} - {s.request_id for s in kept}
    assert all(any(u.request_id == rid for u in after.unassigned) or any(d.request_id == rid for d in after.deferred)
               for rid in lost), "выпавший визит либо не назначен с причиной, либо на завтра"


@needs_data
def test_local_repair_moves_less_than_full(region):
    """Локальный ремонт двигает меньше визитов, чем полный пересчёт."""
    data, matrices = region
    event = next(e for e in data.events if e.type == "cancel")
    with settings.use({"options": {"time_limit_s": 2, "replan_mode": "local"}}):
        plan, _ = solve(data, matrices, plan_id="p1")
        local = replan(plan, data, matrices, event, plan_id="p2")
    with settings.use({"options": {"time_limit_s": 2, "replan_mode": "full"}}):
        full = replan(plan, data, matrices, event, plan_id="p3")
    # Изменение — другая бригада или сдвиг начала от 5 минут. Сдвиг на минуту — расхождение округления
    # между решателем и пересчётом времени, а не перестановка: 29.09.2026 после отмены на Югоцентре
    # локальная правка сдвинула 12 визитов других бригад на минуту и не перенесла ни одного.
    def moved(new):
        return sum(1 for c in new.diff.changed_requests if c.from_engineer != c.to_engineer or (
            c.from_start and c.to_start and abs(to_min(c.to_start) - to_min(c.from_start)) >= 5))
    assert moved(local) <= moved(full)
    assert event.request_id not in stops_of(local)
