"""Сборщик 2ГИС: план заданий и сводка без сырых времён."""

from bee_routing import dgis_collect as dc


def test_sweep_plan_fits_demo_budget():
    tasks = dc.sweep_tasks()
    ids = [t.id for t in tasks]
    assert len(ids) == len(set(ids))
    pairs = 12
    # Полная сетка укладывается в один демо-ключ; живой ряд и показ берут
    # со следующих ключей (решение команды 19.09.2026). Запас пятницы —
    # ровно одна её пересъёмка.
    # Каждый вид дня — не больше одного ключа.
    assert len([t for t in tasks if t.profile == "car"]) * pairs <= 1000
    fridays = [t for t in tasks if t.day_type == "friday"]
    assert dc.FRIDAY_RESERVE == len(fridays) * pairs


def osrm_table():
    ids = ["office", "a", "b"]
    return {
        "ids": ids,
        "index": {n: i for i, n in enumerate(ids)},
        "duration_min": [[0, 10, 20], [10, 0, 5], [20, 5, 0]],
    }


def row(kind, profile, hour, source, target, minutes, status="OK", day_type="workday"):
    return {"kind": kind, "profile": profile, "day_type": day_type, "hour_msk": hour,
            "source": source, "target": target, "status": status,
            "duration_s": minutes * 60, "distance_m": 1000}


def test_summary_is_ratio_of_sums_and_skips_failures():
    osrm = {"car": osrm_table(), "bike": osrm_table()}
    raw = [
        row("stats", "car", 19, "office", "a", 15),
        row("stats", "car", 19, "office", "b", 30),
        row("stats", "car", 19, "a", "b", 99, status="ROUTE_NOT_FOUND"),
        row("stats", "car", 13, "office", "a", 11),
        row("modes", "scooter", 13, "office", "b", 40),
        row("live", "car", 19, "office", "a", 18),
    ]
    out = dc.summarize(raw, osrm)
    assert out["stats"]["workday"]["19"] == {"k": 1.5, "pairs": 2}
    assert out["stats"]["workday"]["13"]["k"] == 1.1
    assert out["modes"]["scooter"]["13"]["k"] == 2.0  # самокат сравнивается с велосипедом OSRM
    assert out["live_vs_stats"] == [
        {"day_type": "workday", "hour": 19, "live_k": 1.8, "stats_k": 1.5}
    ]
    text = str(out)
    assert "duration_s" not in text and "distance_m" not in text
