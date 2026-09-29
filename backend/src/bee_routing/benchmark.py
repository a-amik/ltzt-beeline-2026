"""Сравнение нашего плана с тем, что было в исходных данных заказчика.

Три плана на одном регионе и одной модели дороги:

- **контрольное распределение** — как диспетчеры распределили заявки
  17 августа (файл заказчика; порядок визитов восстановлен по окнам);
- **базовый вариант** из п. 2.3 задания — по порядку, первому подходящему;
- **наш план** — решатель с текущими настройками; для отчёта считается
  дважды, со стартом из офиса и из дома.

Показатели одни на все планы (`kpis`), и сравнение честное: дорога у всех
считается нашей моделью, опоздание — начало работы позже конца окна.
Контрольный план оставлен таким, каким он был, с опозданиями, — его
никто не чинит.

Три вещи, которые нельзя ломать:

1. **Выполненная вовремя заявка и выполненная с опозданием — разные числа.**
   План, который назначил всё, но треть с опозданием, не лучше плана,
   который назначил на пять заявок меньше, но вовремя.
2. **Показатели считаются из плана, а не берутся из его метрик на веру** —
   одинаково для всех трёх.
3. **Отчёт воспроизводим:** `python -m bee_routing.benchmark` пишет
   `data/benchmark/report.md` и `report.json`; тесты `test_benchmark.py`
   держат те же утверждения, что стоят в отчёте. Поиск в отчёте и тестах
   ограничен шагами, а не секундами (`REPORT_SETTINGS`): план по секундам
   зависел от скорости и загрузки машины — пять прогонов одной настройки
   на Юго-востоке давали от 352 до 459 км, и тест дороги на визит то
   проходил, то падал. По шагам на любой машине тот же план.

Запуск: `uv run python -m bee_routing.benchmark [--seeds N]` — с N зёрнами
доводки отчёт добавляет медиану и разброс нашего плана.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from statistics import mean

from . import settings
from .baseline import build_baseline
from .checks import to_min
from .control import control_plan
from .economy import request_value, summarize, tariffs
from .geocode import DATA_DIR
from .matrices import Matrices
from .models import Comparison, Dataset, Plan, PlanSummary
from .solver import solve

REPORT_DIR = DATA_DIR / "benchmark"

# Подписи показателей: одна таблица на отчёт, API и интерфейс.
KPI_LABELS: dict[str, tuple[str, str, bool]] = {
    # ключ: (подпись, единица, меньше — лучше)
    "requests_total": ("Заявок в регионе", "", False),
    "on_time": ("Выполнено вовремя", "", False),
    "late": ("Выполнено с опозданием", "", True),
    "late_min": ("Суммарное опоздание", "мин", True),
    "unassigned": ("Не назначено", "", True),
    "engineers_used": ("Бригад в работе", "", True),
    "travel_min": ("Время в дороге", "мин", True),
    "distance_km": ("Пробег", "км", True),
    "travel_per_visit_min": ("Дорога на визит", "мин", True),
    "wait_min": ("Ожидание у клиентов", "мин", True),
    "risk_late": ("Сорванных окон при шуме дороги, ожидаемо", "", True),
    "utilization_pct": ("Загрузка смены", "%", False),
    "emergencies_served": ("Аварий выполнено вовремя", "", False),
    "emergency_start_min": ("Авария: минут от начала смены", "мин", True),
    "over_norm_engineers": ("Бригад сверх нормы", "", False),
    "norm_spread_min": ("Разброс нагрузки между бригадами", "мин", True),
    "breaks": ("Обедов в плане", "", False),
    "value_on_time_rub": ("Ценность выполненного вовремя", "₽", False),
    "bonus_rub": ("Бонусы", "₽", True),
    "total_cost_rub": ("Затраты: оклады, бонусы, дорога", "₽", True),
    "net_rub": ("Итог дня: ценность вовремя минус затраты", "₽", False),
}


def kpis(plan: Plan, dataset: Dataset) -> dict[str, float]:
    """Показатели плана, посчитанные из его маршрутов."""
    conf = tariffs()
    economy = plan.economy or summarize(plan, dataset)
    by_id = {req.id: req for req in dataset.requests}
    shift = {eng.id: to_min(eng.shift_end) - to_min(eng.shift_start) for eng in dataset.engineers}
    stops = [(route, stop) for route in plan.routes for stop in route.stops if stop.request_id in by_id]
    on_time = [s for _, s in stops if s.late_min == 0]
    late = [s for _, s in stops if s.late_min > 0]
    used = [route for route in plan.routes if route.stops]
    emergencies = [s for _, s in stops if by_id[s.request_id].skill.value == "emergency"]
    emergency_on_time = [s for s in emergencies if s.late_min == 0]
    first_shift = min((to_min(e.shift_start) for e in dataset.engineers), default=600)
    value_on_time = sum(request_value(by_id[s.request_id], conf) for s in on_time)
    busy = [(r.travel_min + r.work_min) / max(shift.get(r.engineer_id, 720), 1) for r in used]
    from .risk import annotate

    annotate(plan, by_id)
    return {
        "requests_total": len(dataset.requests),
        "on_time": len(on_time),
        "late": len(late),
        "late_min": sum(s.late_min for s in late),
        "unassigned": len(plan.unassigned),
        "engineers_used": len(used),
        "travel_min": sum(r.travel_min for r in plan.routes),
        "distance_km": round(sum(r.distance_km for r in plan.routes), 1),
        "travel_per_visit_min": round(sum(r.travel_min for r in plan.routes) / max(len(stops), 1), 1),
        "wait_min": sum(s.wait_min for _, s in stops),
        "risk_late": plan.metrics.risk_late,
        "utilization_pct": round(100 * mean(busy), 1) if busy else 0.0,
        "emergencies_served": len(emergency_on_time),
        "emergency_start_min": round(mean(to_min(s.start) - first_shift for s in emergency_on_time), 1)
        if emergency_on_time else 0.0,
        "over_norm_engineers": sum(1 for r in used if r.over_norm_min > 0),
        "norm_spread_min": (max(r.norm_min for r in used) - min(r.norm_min for r in used)) if used else 0,
        "breaks": sum(1 for r in used if r.break_start),
        "value_on_time_rub": value_on_time,
        "bonus_rub": economy.bonus_rub,
        "total_cost_rub": economy.total_cost_rub,
        "net_rub": value_on_time - economy.total_cost_rub,
    }


LNS_S = 60  # доводка «нашего плана» в сравнении — та же, что у фоновой доводки готового плана (`ready.LNS_S`)

# Отчёт и тесты ищут шагами: одинаковый план на любой машине (`options.search_stop`).
REPORT_SETTINGS = {"options": {"search_stop": "steps"}}


def compare(
    dataset: Dataset, matrices: Matrices, user_settings: dict | None = None,
    *, time_limit_s: int | None = None, with_home: bool = False, lns_s: int = LNS_S,
    ours: Plan | None = None,
) -> Comparison:
    """Контроль, базовый и наш план на одном регионе с одними настройками.

    «Наш план» меряется таким, каким его получает диспетчер: после доводки
    большим соседством (`lns.py`). Экран отдаёт быстрый план сразу, но готовый
    план региона доводится в фоне (`ready.py`), и утром на экране лежит
    доведённый. Пятисекундный план без доводки на Юго-востоке выполнял 81
    заявку из 83 при 17,4 минуты дороги на визит против 16,4 у контроля;
    доведённый — все 83 при 13 минутах.

    `ours` — уже готовый план тех же настроек (экран сравнения берёт его
    из `ready.py`, чтобы не ждать минуту доводки); `lns_s=0` — без доводки.
    """
    # lns_s=0 — без доводки и при поиске шагами: там доводку задаёт число шагов.
    user_settings = {**(user_settings or {}),
                     "options": {"lns_s": lns_s, **({} if lns_s else {"lns_steps": 0}),
                                 **((user_settings or {}).get("options") or {})}}
    with settings.use(user_settings):
        start = settings.option("start") or "office"
        control = control_plan(dataset, matrices)
        base, _ = build_baseline(dataset, matrices, start="office")
        base.economy = summarize(base, dataset)
        if ours is None:
            ours, _ = solve(dataset, matrices, start=start, time_limit_s=time_limit_s)
        rows = [
            PlanSummary(key="control", label="Контрольное распределение", kpis=kpis(control, dataset)),
            PlanSummary(key="baseline", label="Базовый вариант, п. 2.3", kpis=kpis(base, dataset)),
            PlanSummary(key="solver", label="Наш план" + (" из дома" if start == "home" else ""),
                        kpis=kpis(ours, dataset)),
        ]
        # Тот же решатель с запасом надёжности: сколько окон он удерживает и чего это стоит.
        # Без доводки: строка показывает, чего стоит запас, и минуты LNS ей для этого не нужны.
        with settings.use({**(user_settings or {}),
                           "options": {**((user_settings or {}).get("options") or {}),
                                       "reliability": "medium", "lns_s": 0, "lns_steps": 0}}):
            robust, _ = solve(dataset, matrices, start=start, time_limit_s=time_limit_s)
            rows.append(PlanSummary(key="solver_robust", label="Наш план с запасом", kpis=kpis(robust, dataset)))
        if with_home and start != "home":
            home, _ = solve(dataset, matrices, start="home", time_limit_s=time_limit_s)
            rows.append(PlanSummary(key="solver_home", label="Наш план, старт из дома",
                                    kpis=kpis(home, dataset)))
    return Comparison(dataset_id=dataset.id, rows=rows)


def verdicts(comparison: Comparison) -> list[tuple[str, bool, str]]:
    """Утверждения отчёта: что наш план обязан делать лучше контрольного."""
    rows = {row.key: row.kpis for row in comparison.rows}
    ours, ctrl = rows["solver"], rows["control"]
    return [
        ("Вовремя выполнено не меньше, чем в контрольном",
         ours["on_time"] >= ctrl["on_time"], f"{ours['on_time']:.0f} против {ctrl['on_time']:.0f}"),
        ("Опозданий нет", ours["late"] == 0, f"{ours['late']:.0f}"),
        ("Бригад не больше, чем в контрольном",
         ours["engineers_used"] <= ctrl["engineers_used"],
         f"{ours['engineers_used']:.0f} против {ctrl['engineers_used']:.0f}"),
        ("Дороги на визит не больше, чем в контрольном",
         ours["travel_per_visit_min"] <= ctrl["travel_per_visit_min"],
         f"{ours['travel_per_visit_min']} против {ctrl['travel_per_visit_min']} мин"),
        ("Ценность выполненного вовремя не меньше",
         ours["value_on_time_rub"] >= ctrl["value_on_time_rub"],
         f"{ours['value_on_time_rub']:.0f} против {ctrl['value_on_time_rub']:.0f} ₽"),
        ("Итог дня не хуже контрольного", ours["net_rub"] >= ctrl["net_rub"],
         f"{ours['net_rub']:.0f} против {ctrl['net_rub']:.0f} ₽"),
    ]


def _fmt(value: float, unit: str) -> str:
    text = f"{value:,.1f}" if isinstance(value, float) and not float(value).is_integer() else f"{value:,.0f}"
    text = text.replace(",", " ").replace(".", ",")
    return f"{text} {unit}".strip()


SPREAD_KEYS = ("on_time", "engineers_used", "distance_km", "travel_per_visit_min", "emergency_start_min")


def spread(dataset: Dataset, matrices: Matrices, seeds: int, user_settings: dict | None = None) -> dict:
    """Наш план по нескольким зёрнам доводки: медиана и крайние значения показателей."""
    from statistics import median

    runs = []
    for seed in range(1, seeds + 1):
        over = {**(user_settings or {}),
                "options": {**((user_settings or {}).get("options") or {}), "lns_s": LNS_S, "search_seed": seed}}
        with settings.use(over):
            plan, _ = solve(dataset, matrices, start=settings.option("start") or "office")
            runs.append(kpis(plan, dataset))
    return {key: (median(r[key] for r in runs), min(r[key] for r in runs), max(r[key] for r in runs))
            for key in SPREAD_KEYS} | {"seeds": seeds}


def report(comparisons: list[Comparison], spreads: dict[str, dict] | None = None) -> str:
    """Markdown-отчёт по всем регионам."""
    lines = [
        "# Сравнение с исходными данными заказчика",
        "",
        (
            "Три плана на каждом регионе: контрольное распределение из файла заказчика, базовый вариант "
            "из п. 2.3 задания и наш план. Дорога у всех считается одной моделью; опоздание — начало "
            "работы позже конца окна клиента."
        ),
        "",
    ]
    for comparison in comparisons:
        lines.append(f"## {comparison.dataset_id}")
        lines.append("")
        head = "| Показатель | " + " | ".join(row.label for row in comparison.rows) + " |"
        lines += [head, "|" + "---|" * (len(comparison.rows) + 1)]
        for key, (label, unit, _) in KPI_LABELS.items():
            cells = [_fmt(row.kpis[key], unit) for row in comparison.rows]
            lines.append(f"| {label} | " + " | ".join(cells) + " |")
        lines.append("")
        for text, ok, detail in verdicts(comparison):
            lines.append(f"- {'✅' if ok else '❌'} {text}: {detail}")
        lines.append("")
        found = (spreads or {}).get(comparison.dataset_id)
        if found:
            lines.append(f"Наш план по {found['seeds']} зёрнам доводки — медиана (от и до):")
            lines.append("")
            for key in SPREAD_KEYS:
                label, unit, _ = KPI_LABELS[key]
                mid, lo, hi = found[key]
                lines.append(f"- {label}: {_fmt(mid, unit)} ({_fmt(lo, unit)} — {_fmt(hi, unit)})")
            lines.append("")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Посчитать сравнение по всем регионам и записать отчёт."""
    from .loader import dataset_ids, load_dataset, load_matrices

    args = list(argv if argv is not None else sys.argv[1:])
    seeds = int(args[args.index("--seeds") + 1]) if "--seeds" in args else 1
    comparisons, spreads = [], {}
    for dataset_id in dataset_ids():
        data, matrices = load_dataset(dataset_id), load_matrices(dataset_id)
        comparisons.append(compare(data, matrices, REPORT_SETTINGS, time_limit_s=8, with_home=True))
        if seeds > 1:
            spreads[dataset_id] = spread(data, matrices, seeds, REPORT_SETTINGS)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    text = report(comparisons, spreads)
    Path(REPORT_DIR / "report.md").write_text(text, encoding="utf-8")
    Path(REPORT_DIR / "report.json").write_text(
        json.dumps([c.model_dump() for c in comparisons], ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
