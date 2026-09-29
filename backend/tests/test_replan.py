"""Перепланирование: начатое до события не трогается, остальное считается заново."""

from bee_routing import settings
from bee_routing.baseline import build_baseline
from bee_routing.checks import to_min
from bee_routing.replan import replan

from .conftest import needs_data


def stops_of(plan):
    """Карта «заявка → (бригада, начало)» по плану."""
    return {
        stop.request_id: (route.engineer_id, stop.start)
        for route in plan.routes
        for stop in route.stops
    }


@needs_data
def test_frozen_visits_do_not_move(region):
    """Визит, начатый до времени события, остаётся у той же бригады в то же время."""
    data, matrices = region
    plan, _ = build_baseline(data, matrices, plan_id="p1")
    before = stops_of(plan)
    for event in data.events:
        after_plan = replan(plan, data, matrices, event, plan_id="p2")
        after = stops_of(after_plan)
        frozen = after_plan.diff.frozen_requests
        assert frozen, f"{event.type}: до {event.time} бригады успевают начать работу"
        accident = event.type == "urgent"
        horizon = int(settings.option("accident_lock_horizon_min" if accident else "lock_horizon_min") or 0)
        left = {s.request_id: to_min(s.arrive) - s.travel_min for r in plan.routes for s in r.stops}
        for request_id in frozen:
            assert before[request_id] == after[request_id]
            # Начнётся в горизонте — или бригада к нему уже выехала (эксперты 24.09.2026).
            assert (to_min(before[request_id][1]) < to_min(event.time) + horizon
                    or left[request_id] < to_min(event.time))
        assert after_plan.diff.event.id == event.id
        assert after_plan.metrics.changed_requests == len(after_plan.diff.changed_requests)


@needs_data
def test_urgent_goes_first(region):
    """Срочная заявка попадает в план и встаёт впереди прочих в своей бригаде."""
    data, matrices = region
    plan, _ = build_baseline(data, matrices, plan_id="p1")
    event = next(e for e in data.events if e.type == "urgent")
    after = replan(plan, data, matrices, event, plan_id="p2")
    placed = stops_of(after)
    assert event.request.id in placed, "аварию обязаны взять"
    engineer_id, _ = placed[event.request.id]
    route = next(r for r in after.routes if r.engineer_id == engineer_id)
    seq = next(s.seq for s in route.stops if s.request_id == event.request.id)
    later = [s for s in route.stops if s.seq > seq and s.request_id not in after.diff.frozen_requests]
    assert all(to_min(s.start) >= to_min(event.request.window_start) for s in later)


@needs_data
def test_cancel_removes_request(region):
    """Отменённая заявка уходит из плана целиком."""
    data, matrices = region
    plan, _ = build_baseline(data, matrices, plan_id="p1")
    event = next(e for e in data.events if e.type == "cancel")
    after = replan(plan, data, matrices, event, plan_id="p2")
    assert event.request_id not in stops_of(after)
    assert event.request_id not in {item.request_id for item in after.unassigned}


@needs_data
def test_engineer_off_closes_shift(region):
    """Выбывшая бригада не берёт ничего нового: у неё остаётся только начатое.

    Начатый до события визит бригада доводит до конца — он может кончиться
    и после времени события, это не новое назначение, а уже идущая работа.
    """
    data, matrices = region
    plan, _ = build_baseline(data, matrices, plan_id="p1")
    event = next(e for e in data.events if e.type == "engineer_off")
    after = replan(plan, data, matrices, event, plan_id="p2")
    route = next(r for r in after.routes if r.engineer_id == event.engineer_id)
    frozen = set(after.diff.frozen_requests)
    for stop in route.stops:
        if stop.request_id in frozen:
            assert to_min(stop.start) < to_min(event.time), "замороженное уже шло"
        else:
            assert to_min(stop.end) <= to_min(event.time), "новое влезает до ухода бригады"
