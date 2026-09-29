"""Отчёт по исполнителям: пробег каждой бригады и суммарно — вторая обязательная метрика (п. 2.3).

    uv run python -m bee_routing.mileage

Для каждого набора с контрольным распределением считает три плана теми же
функциями и настройками, что сравнение (`benchmark.compare`): контрольное
распределение заказчика, базовый вариант п. 2.3 и наш план. По каждому
исполнителю — пробег и число визитов, по плану — исполнители, суммарный
пробег, заявки в срок и без исполнителя. Пишет `data/mileage/report.json`
(его читает раздел «О проекте») и `report.md` — тот же отчёт таблицами.

Возвращение в стартовую точку в пробег не входит (п. 2.4 задания). Поиск
нашего плана ограничен временем, поэтому от прогона к прогону пробег может
немного отличаться; исполнителей и заявок в срок это обычно не меняет.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

from . import settings
from .baseline import build_baseline
from .benchmark import LNS_S, REPORT_SETTINGS, kpis
from .control import control_plan
from .geocode import DATA_DIR
from .loader import dataset_infos, load_dataset, load_matrices
from .solver import solve

PLANS = (("control", "Контрольное распределение"), ("baseline", "Базовый вариант, п. 2.3"), ("solver", "Наш план"))
REPORT_DIR = DATA_DIR / "mileage"


def _commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                              cwd=Path(__file__).parent, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def zone(dataset_id: str, name: str) -> dict:
    """Три плана одного набора: исполнители по строкам, планы по столбцам."""
    data = load_dataset(dataset_id)
    matrices = load_matrices(dataset_id)
    user = {**REPORT_SETTINGS, "options": {"lns_s": LNS_S, **(REPORT_SETTINGS.get("options") or {})}}
    with settings.use(user):
        start = settings.option("start") or "office"
        plans = {
            "control": control_plan(data, matrices),
            "baseline": build_baseline(data, matrices, start="office")[0],
            "solver": solve(data, matrices, start=start, time_limit_s=8)[0],
        }
    routes = {key: {r.engineer_id: r for r in plan.routes} for key, plan in plans.items()}
    engineers = []
    for engineer in data.engineers:
        row = {"id": engineer.id, "name": getattr(engineer, "name", None) or engineer.id}
        for key in routes:
            r = routes[key].get(engineer.id)
            stops = len(r.stops) if r else 0
            row[key] = {"km": round(r.distance_km, 1) if stops else 0.0, "stops": stops}
        engineers.append(row)
    totals = {}
    for key, plan in plans.items():
        k = kpis(plan, data)
        totals[key] = {
            "engineers": int(k["engineers_used"]), "km": round(k["distance_km"], 1),
            "on_time": int(k["on_time"]), "unassigned": int(k["unassigned"]), "requests": int(k["requests_total"]),
        }
    return {"id": dataset_id, "name": name, "start": start, "engineers": engineers, "totals": totals}


def build() -> dict:
    zones = []
    for info in dataset_infos():
        if info.source != "customer":
            continue  # свои загруженные файлы в отчёт не идут
        data = load_dataset(info.id)
        if not data.control:
            continue  # дни без контрольного распределения сравнивать не с чем
        zones.append(zone(info.id, info.name))
    # «Вся Москва» — те же заявки одним планом без границ участков: после участков.
    zones.sort(key=lambda z: z["id"] == "moskva")
    for z in zones:
        if z["id"] == "moskva":
            z["name"] = f"{z['name']} (без границ участков)"
    return {"date": date.today().isoformat(), "commit": _commit(),
            "plans": [{"key": k, "label": label} for k, label in PLANS], "zones": zones}


def _num(x: float) -> str:
    return f"{x:,.1f}".replace(",", " ").replace(".", ",") if x else "—"


def markdown(report: dict) -> str:
    lines = ["# Отчёт по исполнителям", "",
             f"Пробег каждого исполнителя и суммарно по плану (п. 2.3 задания). Прогон {report['date']}"
             + (f", коммит {report['commit']}" if report.get("commit") else "") + ".", "",
             "Исполнитель — бригада, которой назначена хотя бы одна заявка. «—» — в этом плане заявок нет.", "",
             "## Сводка", "",
             "| Набор | План | Исполнителей | Пробег, км | В срок | Без исполнителя |", "|---|---|---:|---:|---:|---:|"]
    labels = dict((p["key"], p["label"]) for p in report["plans"])
    for z in report["zones"]:
        for key, t in z["totals"].items():
            lines.append(f"| {z['name']} | {labels[key]} | {t['engineers']} | {_num(t['km'])} | {t['on_time']} | {t['unassigned']} |")
    for z in report["zones"]:
        lines += ["", f"## {z['name']}", "",
                  "| Исполнитель | Контроль, км | визитов | Базовый, км | визитов | Наш план, км | визитов |",
                  "|---|---:|---:|---:|---:|---:|---:|"]
        for e in z["engineers"]:
            cells = " | ".join(f"{_num(e[k]['km'])} | {e[k]['stops'] or '—'}" for k in ("control", "baseline", "solver"))
            lines.append(f"| {e['name']} | {cells} |")
        cells = " | ".join(f"**{_num(z['totals'][k]['km'])}** | **{sum(e[k]['stops'] for e in z['engineers'])}**"
                           for k in ("control", "baseline", "solver"))
        lines.append(f"| **Итого** | {cells} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    report = build()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (REPORT_DIR / "report.md").write_text(markdown(report), encoding="utf-8")
    for z in report["zones"]:
        print(z["name"], {k: (t["engineers"], t["km"]) for k, t in z["totals"].items()}, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
