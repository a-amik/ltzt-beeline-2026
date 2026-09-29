"""Базовый вариант: каждое назначение обязано проходить те же проверки."""

from bee_routing import settings
from bee_routing.baseline import build_baseline
from bee_routing.checks import check_visit, feasible, to_min
from bee_routing.models import Plan

from .conftest import needs_data


@needs_data
def test_every_assignment_is_feasible(region):
    """Прогоняем готовый план через check_visit: ни одного нарушения."""
    data, matrices = region
    plan, _ = build_baseline(data, matrices)
    by_id = {req.id: req for req in data.requests}
    engineers = {eng.id: eng for eng in data.engineers}
    for route in plan.routes:
        engineer = engineers[route.engineer_id]
        previous = "office"
        for seq, stop in enumerate(route.stops, start=1):
            assert stop.seq == seq, "порядок визитов — порядок назначения"
            checks = check_visit(
                engineer, by_id[stop.request_id], to_min(stop.arrive), matrices, prev_id=previous
            )
            assert feasible(checks), f"{route.engineer_id} / {stop.request_id}: {checks}"
            assert stop.late_min == 0
            previous = stop.request_id


@needs_data
def test_route_arithmetic(region):
    """Времена в маршруте складываются: отъезд + дорога = приезд, ожидание сходится."""
    data, matrices = region
    plan, _ = build_baseline(data, matrices)
    for route in plan.routes:
        clock = to_min(data.engineers[0].shift_start)
        for stop in route.stops:
            assert to_min(stop.depart_prev) == clock
            assert to_min(stop.arrive) == clock + stop.travel_min
            assert to_min(stop.start) == to_min(stop.arrive) + stop.wait_min
            clock = to_min(stop.end)
        assert route.travel_min == sum(stop.travel_min for stop in route.stops)
        assert round(route.distance_km, 1) == round(
            sum(stop.travel_km for stop in route.stops), 1
        )


@needs_data
def test_plan_covers_every_request(region):
    """Каждая заявка либо в маршруте, либо в отказах с кодом причины."""
    data, matrices = region
    plan, _ = build_baseline(data, matrices)
    placed = {stop.request_id for route in plan.routes for stop in route.stops}
    refused = {item.request_id for item in plan.unassigned}
    assert placed | refused == {req.id for req in data.requests}
    assert not placed & refused
    assert all(item.reason and item.reason_code for item in plan.unassigned)
    assert plan.metrics.engineers_used == sum(1 for r in plan.routes if r.stops)
    assert plan.metrics.unassigned == len(plan.unassigned)
    assert isinstance(plan, Plan)


@needs_data
def test_explanations(region):
    """У назначенной заявки есть проверки и альтернативы по прочим бригадам — ближайшим, числом `scan_limit`."""
    data, matrices = region
    plan, _ = build_baseline(data, matrices)
    placed = [stop.request_id for route in plan.routes for stop in route.stops]
    assert set(plan.explanations) == set(placed)
    sample = plan.explanations[placed[0]]
    limit = int(settings.option("scan_limit") or 0) or len(data.engineers)
    assert len(sample.alternatives) == min(len(data.engineers), limit) - 1
    assert all(check.text for check in sample.checks)
    for alt in sample.alternatives:
        assert alt.text
        assert (alt.delta_km is not None) == alt.feasible
        assert (alt.reason_code is not None) != alt.feasible
