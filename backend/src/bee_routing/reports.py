"""Отчёты о прогонах для раздела «Отчёты»: то, что уже посчитано и лежит в `data/`.

Три страницы, каждая — из своего прогона:

1. **Сравнение с контролем** — `data/benchmark/report.json` (`python -m
   bee_routing.benchmark`): контрольное распределение заказчика, базовый
   вариант п. 2.3 и наш план по каждому участку.
2. **Имитация дня** — `data/simulation/<участок>-<зерно>-<правило>.json`
   (`python -m bee_routing.simulate`): день проживается дважды — «всё новое
   на завтра» и выбранным правилом ответа. Здесь — среднее по зёрнам.
3. **Масштаб и скорость** — `data/scale/report.json` и `report-2000.json`
   (`python -m bee_routing.scale`): время до первого решения, итог, память.

Отчёт ничего не пересчитывает: он читает файлы прогона как есть, и чисел
в нём ровно столько, сколько в прогоне. Нет файла — нет страницы, а не ошибка.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .benchmark import KPI_LABELS
from .geocode import DATA_DIR
from .loader import dataset_infos

SIM_NAME = re.compile(r"^(?P<region>.+)-(?P<seed>\d+)-(?P<policy>[a-z]+)\.json$")
POLICY_RU = {
    "static": "Всё новое — на завтра",
    "offer": "Предлагать бригадам",
    "direct": "Отдавать лучшей",
}


def _read(path: Path) -> object | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _names() -> dict[str, str]:
    return {info.id: info.name for info in dataset_infos()}


def benchmark(data_dir: Path = DATA_DIR) -> dict | None:
    """Сравнение с контролем по участкам, с подписями показателей."""
    report = _read(data_dir / "benchmark" / "report.json")
    if not isinstance(report, list):
        return None
    names = _names()
    return {
        "kpis": [
            {"key": key, "label": label, "unit": unit, "less_is_better": less}
            for key, (label, unit, less) in KPI_LABELS.items()
        ],
        "regions": [
            {"dataset_id": item["dataset_id"], "name": names.get(item["dataset_id"], item["dataset_id"]), "rows": item["rows"]}
            for item in report
        ],
    }


def simulation(data_dir: Path = DATA_DIR) -> dict | None:
    """Имитация дня: по каждому участку — среднее по зёрнам для каждого правила ответа.

    В каждом файле два прогона одного дня: «всё новое на завтра» и правило файла.
    «На завтра» встречается во всех файлах участка и усредняется по всем.
    """
    folder = data_dir / "simulation"
    if not folder.is_dir():
        return None
    sums: dict[str, dict[str, dict[str, float]]] = {}
    counts: dict[str, dict[str, int]] = {}
    seeds: dict[str, set[int]] = {}
    labels: list[dict] = []
    for path in sorted(folder.glob("*.json")):
        match = SIM_NAME.match(path.name)
        body = _read(path)
        if not match or not isinstance(body, dict):
            continue
        region = match["region"]
        labels = labels or body.get("kpi_labels", [])
        seeds.setdefault(region, set()).add(int(match["seed"]))
        for run in body.get("runs", []):
            policy = run.get("policy")
            bucket = sums.setdefault(region, {}).setdefault(policy, {})
            counts.setdefault(region, {})[policy] = counts.get(region, {}).get(policy, 0) + 1
            for key, value in (run.get("kpis") or {}).items():
                bucket[key] = bucket.get(key, 0.0) + float(value)
    if not sums:
        return None
    names = _names()
    regions = []
    for region, by_policy in sums.items():
        runs = []
        for policy in ("static", "offer", "direct"):
            if policy not in by_policy:
                continue
            n = counts[region][policy]
            runs.append(
                {
                    "policy": policy,
                    "label": POLICY_RU.get(policy, policy),
                    "runs": n,
                    "kpis": {key: round(total / n, 1) for key, total in by_policy[policy].items()},
                }
            )
        regions.append({"dataset_id": region, "name": names.get(region, region), "seeds": len(seeds[region]), "runs": runs})
    return {"kpis": labels, "regions": regions}


def scale(data_dir: Path = DATA_DIR) -> dict | None:
    """Замеры масштаба: строки основного прогона, 2000 × 200 — из отдельного, более свежего."""
    main = _read(data_dir / "scale" / "report.json")
    if not isinstance(main, dict):
        return None
    rows = list(main.get("rows", []))
    fresh = _read(data_dir / "scale" / "report-2000.json")
    if isinstance(fresh, dict) and fresh.get("rows"):
        sizes = {(row["requests"], row["engineers"]) for row in fresh["rows"]}
        rows = [row for row in rows if (row["requests"], row["engineers"]) not in sizes] + list(fresh["rows"])
    keep = (
        "requests", "engineers", "budget_s", "portfolio", "first_solution_s",
        "last_improvement_s", "elapsed_s", "assigned", "net_rub", "rss_mb_after",
    )
    return {"rows": [{key: row.get(key) for key in keep} for row in rows]}


def search(data_dir: Path = DATA_DIR) -> dict | None:
    """Три решателя портфеля и контроль по участкам при бюджете поиска 4 и 60 секунд."""
    report = _read(data_dir / "search" / "report.json")
    if not isinstance(report, dict) or not isinstance(report.get("regions"), dict):
        return None
    names = _names()
    return {
        "budgets": report.get("budgets", []),
        "regions": [{"dataset_id": key, "name": names.get(key, key), "rows": rows}
                    for key, rows in report["regions"].items()],
    }


def generalize(data_dir: Path = DATA_DIR) -> dict | None:
    """Наш план против базового на синтетических днях каждого участка."""
    report = _read(data_dir / "generalize" / "report.json")
    if not isinstance(report, dict) or not isinstance(report.get("regions"), dict):
        return None
    keep = ("on_time", "unassigned", "engineers_used", "distance_km", "net_rub")
    return {
        "meta": report.get("meta", {}),
        "regions": [
            {"dataset_id": key, "name": item.get("name", key), "requests": item.get("requests"),
             "engineers": item.get("engineers"),
             "days": [{side: {k: day[side].get(k) for k in keep} for side in ("baseline", "solver")}
                      for day in item.get("days", [])]}
            for key, item in report["regions"].items()
        ],
    }


def load(data_dir: Path = DATA_DIR) -> dict | None:
    """Замер нагрузки и злоупотреблений на живом API (`bee_routing.loadtest`)."""
    report = _read(data_dir / "load" / "report.json")
    return report if isinstance(report, dict) else None


def reports(data_dir: Path = DATA_DIR) -> dict:
    """Все страницы отчётов разом: экран строит из этого рисунки и таблицы."""
    return {"benchmark": benchmark(data_dir), "simulation": simulation(data_dir), "scale": scale(data_dir),
            "search": search(data_dir), "generalize": generalize(data_dir), "load": load(data_dir)}
