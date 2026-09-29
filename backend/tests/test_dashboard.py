"""Сводка руководителя: один план города, участки — его разбивка, суммы сходятся."""

from bee_routing.baseline import build_baseline
from bee_routing.dashboard import dashboard
from bee_routing.economy import summarize
from bee_routing.loader import load_dataset, load_matrices
from bee_routing.moscow import MOSCOW_ID


def test_sectors_add_up_to_city():
    """Итоги участков складываются в итог города, экономика участков — в итог плана."""
    data = load_dataset(MOSCOW_ID)
    plan, _ = build_baseline(data, load_matrices(MOSCOW_ID))
    plan.economy = summarize(plan, data)
    out = dashboard(plan, data, [], [], {"on_time_pct": 95, "utilization_pct": 65}, "office")
    totals, sectors = out["totals"], out["sectors"]
    assert [s["id"] for s in sectors] == [s.id for s in data.sectors]
    for key in ("requests", "on_time", "unassigned", "crews_total"):
        assert sum(s[key] for s in sectors) == totals[key], key
    assert totals["requests"] == len(data.requests)
    assert sum(s["net_rub"] for s in out["economy"]["sectors"]) == plan.economy.net_rub
    assert out["hours"]["planned"][-1] == sum(1 for r in plan.routes for s in r.stops if s.status != "no_show")
    assert len(out["load"]["rows"]) == len(data.sectors)
    assert all(c["norm_day"] > 0 for c in out["crews"])
    # Без плана города в прогоне сравнения сумма участков не удваивается.
    bench = out["versus"].get("benchmark")
    if bench:
        assert bench["control"]["requests_total"] == len(data.requests)
