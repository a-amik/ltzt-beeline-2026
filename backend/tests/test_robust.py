"""Робастный план: поджатие маршрута, запас надёжности, обед в оценке риска."""

from bee_routing import settings
from bee_routing.checks import to_min
from bee_routing.risk import RELIABILITY, annotate, buffer
from bee_routing.solver import solve

from .conftest import needs_data

FAST = {"time_limit_s": 3, "portfolio": False}


def _plan(region, level):
    data, matrices = region
    by_id = {r.id: r for r in data.requests}
    with settings.use({"options": {**FAST, "reliability": level}}):
        plan, _ = solve(data, matrices, plan_id=f"r-{level}", start="home")
        plan = annotate(plan, by_id)
    return data, by_id, plan


def test_buffer_levels():
    """Выключенная надёжность — нулевой запас; уровни растут."""
    assert RELIABILITY["off"] == 0 < RELIABILITY["medium"] < RELIABILITY["high"]
    with settings.use({"options": {"reliability": "off"}}):
        assert not buffer().on
    with settings.use({"options": {"reliability": "high"}}):
        buf = buffer()
        assert buf.on and buf.road(100) > 0 and buf.job(100) > 0
        assert buf.after_start(30.0, arrive=600, begin=700) == 0, "ожидание окна съедает запас"
        assert buf.after_start(30.0, arrive=700, begin=700) == 30.0


@needs_data
def test_routes_are_compacted(region):
    """Визит начинается, как только бригада приехала и окно открыто, а не в произвольную минуту окна."""
    _, by_id, plan = _plan(region, "off")
    for route in plan.routes:
        for stop in route.stops:
            earliest = max(to_min(stop.arrive), to_min(by_id[stop.request_id].window_start))
            after_lunch = to_min(route.break_end) if route.break_end else -1
            assert to_min(stop.start) in (earliest, max(earliest, after_lunch)), (
                route.engineer_id, stop.request_id, stop.arrive, stop.start, route.break_start)


@needs_data
def test_reliability_lowers_risk(region):
    """С запасом ожидаемое число сорванных окон меньше, и визитов под риском не больше.

    Ноля визитов под риском запас не обещает: с 22.09.2026 надбавка ступени включена
    по умолчанию, и план берёт заявку старшей ступени даже в тесное окно, вместо того
    чтобы её отбросить. На Юго-востоке это 78 визитов против 77 и один визит с риском
    0,64 — ступень дороже надёжности окна, так решено.
    """
    _, _, tight = _plan(region, "off")
    _, by_id, safe = _plan(region, "high")
    assert safe.metrics.risk_late < max(tight.metrics.risk_late, 0.5)
    assert safe.metrics.risky_stops <= tight.metrics.risky_stops
    assert safe.metrics.late == 0
    for item in safe.unassigned:
        assert item.reason, "отказ из-за запаса назван словами"


@needs_data
def test_break_is_simulated_in_place(region):
    """Без шума прогон повторяет план: обед стоит там же, и ни один визит не срывается."""
    data, matrices = region
    by_id = {r.id: r for r in data.requests}
    with settings.use({"options": FAST, "risk": {"spread_travel": 0, "spread_work": 0, "runs": 20}}):
        plan, _ = solve(data, matrices, plan_id="quiet", start="home")
        plan = annotate(plan, by_id)
    assert plan.metrics.late == 0
    assert plan.metrics.risk_late == 0, [
        (r.engineer_id, s.request_id, s.start, s.arrive_p90) for r in plan.routes for s in r.stops if s.late_risk
    ]
