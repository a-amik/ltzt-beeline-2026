"""Замер поиска с запасом: три региона, три бюджета, три способа искать.

Способы:
- `ortools` — портфель четырёх стратегий OR-Tools, весь бюджет решателю;
- `pyvrp` — PyVRP один, весь бюджет ему;
- `lns` — портфель OR-Tools на 4 секунды, остальное — доводка
  большим соседством (`lns.py`). При бюджете в 4 секунды это просто портфель.

Решателям больше минуты не даётся (потолок настройки «Время поиска»): первый
замер 19.09.2026 показал, что OR-Tools упирается в потолок качества за первые
секунды, а PyVRP лишнее время по нашей мерке не помогает;
на бюджетах дольше минуты идёт только `lns`.

Мерка одна: показатели `benchmark.kpis` и риск окон; контроль заказчика —
первой строкой региона. Запуск: `uv run python -m bee_routing.search_bench [бюджеты через запятую]`,
итог — `data/search/report.json` и `report.md`.
"""

from __future__ import annotations

import json
import sys
import time

from . import settings
from .benchmark import kpis
from .control import control_plan
from .economy import summarize
from .geocode import DATA_DIR
from .loader import dataset_ids, load_dataset, load_matrices
from .lns import refine
from .risk import annotate
from .solver import solve

OUT = DATA_DIR / "search"
KEYS = ("on_time", "unassigned", "engineers_used", "distance_km", "travel_per_visit_min", "wait_min",
        "utilization_pct", "net_rub")
QUICK_S = 4
SOLVER_MAX_S = 60  # потолок «Времени поиска» в схеме настроек: дольше решатели не считают, дольше идёт только LNS


def _row(plan, data, by_id, seconds: float) -> dict:
    plan.economy = summarize(plan, data)
    plan = annotate(plan, by_id)
    row = {k: kpis(plan, data)[k] for k in KEYS}
    row.update(risk_late=plan.metrics.risk_late, late=plan.metrics.late, seconds=round(seconds, 1),
               lns_steps=plan.timing.get("lns_steps"), winner_pyvrp=bool(plan.timing.get("pyvrp")))
    return row


def run(budgets: list[int]) -> dict:
    report: dict = {"budgets": budgets, "regions": {}}
    for ds in dataset_ids():
        data, matrices = load_dataset(ds), load_matrices(ds)
        by_id = {r.id: r for r in data.requests}
        with settings.use({}):
            control = control_plan(data, matrices)
            rows = {"control": _row(control, data, by_id, 0)}
        for budget in budgets:
            base = {"time_limit_s": budget, "stall_s": 0, "lns_s": 0}
            if budget <= SOLVER_MAX_S:
                t = time.perf_counter()
                with settings.use({"options": base}):
                    plan, _ = solve(data, matrices, plan_id=f"o{budget}", start="home")
                rows[f"ortools@{budget}"] = _row(plan, data, by_id, time.perf_counter() - t)

                t = time.perf_counter()
                with settings.use({"options": {**base, "portfolio": False}}):
                    plan, _ = solve(data, matrices, plan_id=f"p{budget}", start="home", strategy="PYVRP")
                rows[f"pyvrp@{budget}"] = _row(plan, data, by_id, time.perf_counter() - t)

            t = time.perf_counter()
            with settings.use({"options": {**base, "time_limit_s": QUICK_S}}):
                plan, _ = solve(data, matrices, plan_id=f"l{budget}", start="home")
                if budget > QUICK_S:
                    plan = refine(plan, data, matrices, budget_s=budget - QUICK_S)
            rows[f"lns@{budget}"] = _row(plan, data, by_id, time.perf_counter() - t)
            print(ds, budget, {k: v["net_rub"] for k, v in rows.items()}, flush=True)
        report["regions"][ds] = rows
    return report


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    budgets = [int(x) for x in args[0].split(",")] if args else [4, 60, 300]
    report = run(budgets)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = ["# Поиск с запасом: замер", ""]
    for ds, rows in report["regions"].items():
        lines += [f"## {ds}", "", "| план | " + " | ".join(KEYS) + " | risk_late | сек |", "|---|" + "---|" * (len(KEYS) + 2)]
        for name, row in rows.items():
            lines.append(f"| {name} | " + " | ".join(str(row[k]) for k in KEYS) + f" | {row['risk_late']} | {row['seconds']} |")
        lines.append("")
    (OUT / "report.md").write_text("\n".join(lines), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
