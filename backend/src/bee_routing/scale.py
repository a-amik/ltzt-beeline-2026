"""Прогон нагрузки: как растут время и качество плана с числом заявок и бригад.

Вопрос жюри — «если бригад больше, а точек больше, не упадёт ли всё
кратно». Ответ — таблица, снятая на синтетических регионах генератора
(`loadgen.py`), и в ней три разных времени, которые нельзя смешивать:

- **загрузка** — прочитать регион и четыре матрицы с диска; растёт
  квадратом числа точек, потому что матрица — это квадрат;
- **первое решение** — от старта поиска до первого допустимого плана;
  единственное время, которое бюджет не ограничивает: пока его нет,
  показывать нечего;
- **последнее улучшение** — после него поиск тратил бюджет впустую;
  разница с бюджетом и есть то, что снимает остановка по застою.

Отдельно — **хвост после поиска**: объяснения назначений, причины отказов,
предложения бригадам. В маленьком регионе он незаметен, в большом растёт
как заявки × бригады, и в таблице стоит своей колонкой (`total − search`).

Качество меряется числом неназначенных и итогом дня в рублях; прогоны
с бюджетом 4 и 16 секунд на одном регионе показывают, сколько даёт время
и где кончается его польза. Матрица у синтетики запасная (прямая × 1,3),
поэтому рубли сравнимы только между строками одной таблицы, не с отчётом
по настоящим регионам.

Итог ложится в `data/scale/report.json` и `report.md`: таблица ниже
переносится в лист «Взгляд жюри» руками, вместе с выводом.

Запуск: `uv run python -m bee_routing.scale --sizes 66x12,250x30,1000x100 --budgets 4,16`.
Долгий прогон — в фоне: `nohup uv run python -m bee_routing.scale > data/scale/run.log 2>&1 &`.
"""

from __future__ import annotations

import argparse
import json
import resource
import sys
import time
from pathlib import Path

from . import settings
from .loader import SCALE_DIR, load_dataset, load_matrices
from .loadgen import ensure

DEFAULT_SIZES = "66x12,250x30,500x50,1000x100,2000x200"
DEFAULT_BUDGETS = "4,16"


def rss_mb() -> float:
    """Пиковая память процесса, МБ (на macOS ru_maxrss в байтах, на Linux в КБ)."""
    raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(raw / (1024 * 1024) if sys.platform == "darwin" else raw / 1024, 1)


def measure_load(dataset_id: str) -> float:
    """Секунды на чтение региона и матриц с диска, без кэша."""
    load_dataset.cache_clear()
    load_matrices.cache_clear()
    t = time.perf_counter()
    load_matrices(dataset_id)
    return round(time.perf_counter() - t, 3)


def run_one(dataset_id: str, budget_s: int, *, stall_s: float, portfolio: bool) -> dict:
    """Один прогон решателя; строка таблицы."""
    from .solver import solve

    data, matrices = load_dataset(dataset_id), load_matrices(dataset_id)
    before = rss_mb()
    overrides = {"options": {"portfolio": portfolio, "stall_s": stall_s, "time_limit_s": budget_s}}
    t = time.perf_counter()
    with settings.use(overrides):
        plan, _ = solve(data, matrices, plan_id=f"scale-{budget_s}")
    elapsed = round(time.perf_counter() - t, 3)
    timing = plan.timing
    return {
        "dataset_id": dataset_id,
        "requests": len(data.requests),
        "engineers": len(data.engineers),
        "budget_s": budget_s,
        "stall_s": stall_s,
        "portfolio": portfolio,
        "elapsed_s": elapsed,
        "setup_s": timing.get("setup_s"),
        "first_solution_s": timing.get("first_solution_s"),
        "last_improvement_s": timing.get("last_improvement_s"),
        "search_s": timing.get("search_s"),
        "tail_s": round(elapsed - float(timing.get("search_s") or 0) - float(timing.get("setup_s") or 0), 3),
        "solutions": timing.get("solutions"),
        "unassigned": len(plan.unassigned),
        "assigned": len(data.requests) - len(plan.unassigned),
        "net_rub": plan.economy.net_rub if plan.economy else None,
        "travel_min": plan.metrics.travel_min,
        "rss_mb_before": before,
        "rss_mb_after": rss_mb(),
    }


def measure_api(dataset_id: str) -> dict:
    """Ответ `POST /plan` целиком: первый раз — расчёт, второй — готовый план."""
    from fastapi.testclient import TestClient

    from . import ready
    from .api import app

    ready.clear()
    client = TestClient(app)
    body = {"dataset_id": dataset_id, "algorithm": "solver"}
    t = time.perf_counter()
    first = client.post("/plan", json=body)
    t_first = round(time.perf_counter() - t, 3)
    t = time.perf_counter()
    second = client.post("/plan", json=body)
    t_second = round(time.perf_counter() - t, 3)
    return {
        "dataset_id": dataset_id,
        "api_first_s": t_first,
        "api_ready_s": t_second,
        "response_kb": round(len(first.content) / 1024),
        "same_plan": first.json()["id"] == second.json()["id"],
    }


def markdown(rows: list[dict], api_rows: list[dict]) -> str:
    """Таблица для листа."""
    head = ("| Заявок×бригад | Бюджет, с | Режим | Загрузка, с | Первое решение, с | Последнее улучшение, с "
            "| Поиск, с | Хвост, с | Всего, с | Назначено | Итог, ₽ | Память, МБ |\n"
            "|---|---|---|---|---|---|---|---|---|---|---|---|\n")
    lines = []
    for r in rows:
        mode = "портфель, застой" if r["portfolio"] else ("весь бюджет" if r["stall_s"] == 0 else "застой")
        lines.append(
            f"| {r['requests']}×{r['engineers']} | {r['budget_s']} | {mode} | {r.get('load_s', '')} "
            f"| {r['first_solution_s']} | {r['last_improvement_s']} | {r['search_s']} | {r['tail_s']} "
            f"| {r['elapsed_s']} | {r['assigned']} из {r['requests']} | {r['net_rub']:,} | {r['rss_mb_after']} |"
            .replace(",", " ")
        )
    api = ""
    if api_rows:
        api = ("\n\n| Регион | Ответ API, расчёт, с | Ответ API, готовый план, с | Ответ, КБ |\n|---|---|---|---|\n"
               + "\n".join(f"| {a['dataset_id']} | {a['api_first_s']} | {a['api_ready_s']} | {a['response_kb']} |"
                           for a in api_rows))
    return head + "\n".join(lines) + api + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Прогон нагрузки решателя")
    parser.add_argument("--base", default="yugo-vostok", help="регион-образец")
    parser.add_argument("--sizes", default=DEFAULT_SIZES, help="заявок×бригад через запятую")
    parser.add_argument("--budgets", default=DEFAULT_BUDGETS, help="бюджеты поиска, с")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--osrm", action="store_true", help="матрицы от OSRM вместо запасной оценки")
    parser.add_argument("--no-portfolio", action="store_true", help="не гонять боевой режим (портфель + застой)")
    parser.add_argument("--no-api", action="store_true", help="не мерить ответ API")
    parser.add_argument("--out", default=str(SCALE_DIR / "report"))
    args = parser.parse_args(argv)

    sizes = [tuple(int(x) for x in s.split("x")) for s in args.sizes.split(",")]
    budgets = [int(b) for b in args.budgets.split(",")]
    rows: list[dict] = []
    api_rows: list[dict] = []
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    def flush() -> None:
        out.with_suffix(".json").write_text(
            json.dumps({"rows": rows, "api": api_rows}, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        out.with_suffix(".md").write_text(markdown(rows, api_rows), encoding="utf-8")

    for n_req, n_eng in sizes:
        t = time.perf_counter()
        dataset_id = ensure(args.base, n_req, n_eng, seed=args.seed, osrm=args.osrm)
        print(f"{dataset_id}: готов за {time.perf_counter() - t:.1f} с", flush=True)
        load_s = measure_load(dataset_id)
        for budget in budgets:
            row = run_one(dataset_id, budget, stall_s=0.0, portfolio=False)
            row["load_s"] = load_s
            rows.append(row)
            print(f"  бюджет {budget}: первое {row['first_solution_s']} с, последнее улучшение "
                  f"{row['last_improvement_s']} с, всего {row['elapsed_s']} с, назначено {row['assigned']}, "
                  f"итог {row['net_rub']}", flush=True)
            flush()
        if not args.no_portfolio:
            row = run_one(dataset_id, budgets[0], stall_s=1.5, portfolio=True)
            row["load_s"] = load_s
            rows.append(row)
            print(f"  боевой режим: всего {row['elapsed_s']} с, назначено {row['assigned']}, итог {row['net_rub']}",
                  flush=True)
            flush()
        if not args.no_api:
            api_rows.append(measure_api(dataset_id))
            print(f"  API: расчёт {api_rows[-1]['api_first_s']} с, готовый {api_rows[-1]['api_ready_s']} с, "
                  f"ответ {api_rows[-1]['response_kb']} КБ", flush=True)
            flush()
    print(f"Итог: {out.with_suffix('.md')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
