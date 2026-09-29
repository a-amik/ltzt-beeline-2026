"""Сравнение с исходными данными заказчика: наш план против контрольного распределения.

Те же утверждения стоят в отчёте `data/benchmark/report.md`
(`python -m bee_routing.benchmark`). Опоздание — начало работы позже
конца окна; дорога у всех планов считается одной моделью.
"""

import pytest

from bee_routing.benchmark import REPORT_SETTINGS, compare, kpis, verdicts
from bee_routing.control import control_plan

from .conftest import needs_data

_CACHE: dict = {}


def _comparison(region):
    data, matrices = region
    if data.id not in _CACHE:
        _CACHE[data.id] = compare(data, matrices, REPORT_SETTINGS, time_limit_s=5)
    return _CACHE[data.id]


def _rows(region):
    return {row.key: row.kpis for row in _comparison(region).rows}


@needs_data
def test_three_plans_are_compared(region):
    assert set(_rows(region)) == {"control", "baseline", "solver", "solver_robust"}


@needs_data
def test_on_time_not_less_than_control(region):
    rows = _rows(region)
    assert rows["solver"]["on_time"] >= rows["control"]["on_time"]


@needs_data
def test_no_late_visits(region):
    assert _rows(region)["solver"]["late"] == 0


@needs_data
def test_engineers_not_more_than_control(region):
    rows = _rows(region)
    assert rows["solver"]["engineers_used"] <= rows["control"]["engineers_used"]


@needs_data
def test_travel_per_visit_not_worse(region):
    rows = _rows(region)
    assert rows["solver"]["travel_per_visit_min"] <= rows["control"]["travel_per_visit_min"]


@needs_data
def test_value_on_time_not_less(region):
    rows = _rows(region)
    assert rows["solver"]["value_on_time_rub"] >= rows["control"]["value_on_time_rub"]


@needs_data
def test_net_not_worse_than_control(region):
    rows = _rows(region)
    assert rows["solver"]["net_rub"] >= rows["control"]["net_rub"]


@needs_data
def test_better_than_baseline(region):
    rows = _rows(region)
    assert rows["solver"]["on_time"] >= rows["baseline"]["on_time"]
    assert rows["solver"]["unassigned"] <= rows["baseline"]["unassigned"]


@needs_data
def test_verdicts_all_pass(region):
    failed = [(text, detail) for text, ok, detail in verdicts(_comparison(region)) if not ok]
    assert not failed, failed


@needs_data
def test_control_kpis_count_every_request(region):
    data, matrices = region
    k = kpis(control_plan(data, matrices), data)
    assert k["on_time"] + k["late"] + k["unassigned"] == k["requests_total"]


@needs_data
@pytest.mark.parametrize(
    "override, check",
    [
        ({"options": {"breaks": False}}, lambda k: k["breaks"] == 0),
        ({"options": {"extra_load": False}}, lambda k: k["over_norm_engineers"] == 0 and k["bonus_rub"] == 0),
    ],
    ids=["без обеда", "без работы сверх нормы"],
)
def test_settings_change_plan(region, override, check):
    data, matrices = region
    result = compare(data, matrices, override, time_limit_s=2, lns_s=0)
    ours = next(row.kpis for row in result.rows if row.key == "solver")
    assert check(ours)


@needs_data
def test_car_only_uses_car(region):
    from bee_routing import settings
    from bee_routing.solver import solve

    data, matrices = region
    with settings.use({"options": {"modes": ["car"]}}):
        plan, _ = solve(data, matrices, time_limit_s=2)
    modes = {s.mode.value for r in plan.routes for s in r.stops}
    assert modes <= {"car", "foot"}  # бригады без машины остаются пешком
    assert plan.settings["options"]["modes"] == ["car"]
