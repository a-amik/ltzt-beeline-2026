"""Проверка обобщения: наш план против базового на десятках синтетических дней.

Настройки решателя подобраны на одном дне заказчика — 17 августа, три
региона. Упрёк «подогнали под один день» снимается только прогоном на других
днях, а других дней заказчик не давал. Поэтому дни выращиваются из настоящих
(`loadgen.py`): тот же регион, то же число заявок и бригад, те же окна,
навыки и длительности, точки — рядом с настоящими, случайность посеяна
номером дня. На каждом дне считаются базовый вариант п. 2.3 и наш план
с настройками по умолчанию, и по каждому показателю записывается,
в скольких днях из скольких наш план не хуже базового.

Матрицы дорог — OSRM, если поднят (по умолчанию так на машине разработчика),
иначе запасная оценка; источник записан в отчёте. Контрольного распределения
у синтетического дня нет, сравнение идёт только с базовым.

Запуск: `uv run python -m bee_routing.generalize --days 10`;
итог — `data/generalize/report.md` и `report.json`.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from statistics import median

from . import settings
from .baseline import build_baseline
from .benchmark import KPI_LABELS, kpis
from .economy import summarize
from .loader import DATA_DIR, dataset_ids, load_dataset, load_matrices
from .loadgen import ensure
from .solver import solve

METRICS = ("on_time", "unassigned", "engineers_used", "distance_km", "travel_min", "risk_late", "net_rub")
EXTRA_METRICS = ("requests_total", "on_time", "late", "unassigned", "emergencies_served", "engineers_used",
                 "distance_km", "travel_min", "risk_late", "net_rub")


def run_day(dataset_id: str, budget_s: int, keys: tuple[str, ...] = METRICS) -> dict:
    """Базовый и наш план на одном дне; показатели обоих."""
    data, matrices = load_dataset(dataset_id), load_matrices(dataset_id)
    with settings.use({"options": {"time_limit_s": budget_s}}):
        start = str(settings.option("start") or "office")
        base, _ = build_baseline(data, matrices, start="office")
        base.economy = summarize(base, data)
        ours, _ = solve(data, matrices, start=start, time_limit_s=budget_s)
        return {
            "dataset_id": dataset_id,
            "matrix": matrices.source(),
            "baseline": {k: kpis(base, data)[k] for k in keys},
            "solver": {k: kpis(ours, data)[k] for k in keys},
            "timing": ours.timing,
        }


def summarize_region(days: list[dict]) -> dict:
    """Медиана, размах и счёт «не хуже базового» по каждому показателю."""
    out = {}
    for key in METRICS:
        less = KPI_LABELS[key][2]
        base = [d["baseline"][key] for d in days]
        ours = [d["solver"][key] for d in days]
        wins = sum(1 for b, o in zip(base, ours, strict=True) if (o <= b if less else o >= b))
        out[key] = {
            "label": KPI_LABELS[key][0],
            "less_is_better": less,
            "baseline": {"median": median(base), "min": min(base), "max": max(base)},
            "solver": {"median": median(ours), "min": min(ours), "max": max(ours)},
            "not_worse": wins,
            "days": len(days),
        }
    return out


def _fmt(value: float) -> str:
    return f"{value:,.1f}".replace(",", " ") if isinstance(value, float) and not value.is_integer() \
        else f"{int(value):,}".replace(",", " ")


def markdown(regions: dict[str, dict], meta: dict) -> str:
    lines = [f"# Обобщение: {meta['days']} синтетических дней на регион, бюджет {meta['budget_s']} с, "
             f"матрицы {meta['matrix']}\n"]
    for region, block in regions.items():
        lines.append(f"## {block['name']}: {block['requests']} заявок, {block['engineers']} бригад\n")
        lines.append("| Показатель | Базовый, медиана (мин—макс) | Наш план, медиана (мин—макс) | Не хуже базового |")
        lines.append("|---|---|---|---|")
        for key, row in block["summary"].items():
            b, o = row["baseline"], row["solver"]
            lines.append(
                f"| {row['label']} | {_fmt(b['median'])} ({_fmt(b['min'])}—{_fmt(b['max'])}) "
                f"| {_fmt(o['median'])} ({_fmt(o['min'])}—{_fmt(o['max'])}) | {row['not_worse']} из {row['days']} |"
            )
        lines.append("")
    return "\n".join(lines) + "\n"


def run_extra(budget_s: int, out: Path) -> int:
    """Наш план против базового на днях заказчика сверх 17 августа.

    Билайн 29.09.2026 дал ещё по дню-два тех же регионов (`prepare.extra_days`):
    настоящие заявки, но без столбца «Бригада», то есть без контрольного
    распределения. Бригады и их дома — из 17 августа, как их собирает
    подготовка, поэтому сравнение идёт только с базовым вариантом.
    """
    from .geocode import load_assumptions
    from .prepare import extra_days

    days = []
    for region, day in extra_days(load_assumptions()):
        t = time.perf_counter()
        row = run_day(f"{region}-{day}", budget_s, EXTRA_METRICS)
        data = load_dataset(row["dataset_id"])
        row.update(name=data.name, requests=len(data.requests), engineers=len(data.engineers))
        days.append(row)
        print(f"{row['name']}: базовый {row['baseline']['on_time']} вовремя / "
              f"{row['baseline']['engineers_used']} бригад; наш {row['solver']['on_time']} / "
              f"{row['solver']['engineers_used']}; {time.perf_counter() - t:.1f} с", flush=True)
    if not days:
        print("Дней сверх 17 августа нет: они есть только при исходных CSV заказчика в data/raw/")
        return 0
    meta = {"budget_s": budget_s, "matrix": days[0]["matrix"]}
    out.with_suffix(".json").write_text(json.dumps({"meta": meta, "days": days}, ensure_ascii=False, indent=1),
                                        encoding="utf-8")
    lines = [f"# Дни заказчика сверх 17 августа: бюджет {budget_s} с, матрицы {meta['matrix']}\n",
             ("Контрольного распределения в этих файлах нет — сравнение с базовым вариантом п. 2.3; "
              "бригады — из 17 августа.\n")]
    for row in days:
        lines.append(f"## {row['name']}: {row['requests']} заявок, {row['engineers']} бригад\n")
        lines.append("| Показатель | Базовый | Наш план |")
        lines.append("|---|---|---|")
        for key in EXTRA_METRICS:
            lines.append(f"| {KPI_LABELS[key][0]} | {_fmt(row['baseline'][key])} | {_fmt(row['solver'][key])} |")
        lines.append("")
    out.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Итог: {out.with_suffix('.md')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Наш план против базового на синтетических днях")
    parser.add_argument("--days", type=int, default=10)
    parser.add_argument("--regions", default=",".join(dataset_ids()))
    parser.add_argument("--budget", type=int, default=4)
    parser.add_argument("--no-osrm", action="store_true", help="запасные матрицы даже при поднятом OSRM")
    parser.add_argument("--extra", action="store_true",
                        help="дни заказчика сверх 17 августа (data/raw/<регион>-<дата>-zayavki.csv) вместо синтетики")
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    if args.extra:
        out = Path(args.out or DATA_DIR / "generalize" / "extra-days")
        out.parent.mkdir(parents=True, exist_ok=True)
        return run_extra(args.budget, out)
    out = Path(args.out or DATA_DIR / "generalize" / "report")
    out.parent.mkdir(parents=True, exist_ok=True)
    regions: dict[str, dict] = {}
    matrix_source = "fallback"
    for region in args.regions.split(","):
        base = load_dataset(region)
        days = []
        for seed in range(1, args.days + 1):
            t = time.perf_counter()
            day_id = ensure(region, len(base.requests), len(base.engineers), seed=seed, osrm=not args.no_osrm)
            row = run_day(day_id, args.budget)
            matrix_source = row["matrix"]
            days.append(row)
            print(f"{region} день {seed}: базовый {row['baseline']['on_time']} вовремя / "
                  f"{row['baseline']['engineers_used']} бригад; наш {row['solver']['on_time']} / "
                  f"{row['solver']['engineers_used']}; {time.perf_counter() - t:.1f} с", flush=True)
        regions[region] = {
            "name": base.name, "requests": len(base.requests), "engineers": len(base.engineers),
            "days": days, "summary": summarize_region(days),
        }
        meta = {"days": args.days, "budget_s": args.budget, "matrix": matrix_source}
        out.with_suffix(".json").write_text(json.dumps({"meta": meta, "regions": regions}, ensure_ascii=False, indent=1),
                                            encoding="utf-8")
        out.with_suffix(".md").write_text(markdown(regions, meta), encoding="utf-8")
    print(f"Итог: {out.with_suffix('.md')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
