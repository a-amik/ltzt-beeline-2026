"""Замер нагрузки и злоупотреблений на живом API.

Три проверки, каждая тем же запросом, каким ходит экран:

1. **Ступени чтения.** N одновременных экранов без пауз читают то, что
   экран диспетчера читает весь день: набор, последний план, контроль,
   отчёты. На каждой ступени — запросов в секунду, медиана, p95, p99
   и ошибки.
2. **Одновременные расчёты.** K диспетчеров разом жмут «Спланировать»:
   сколько ждёт последний и не ломается ли чтение, пока идёт расчёт.
3. **Злоупотребления.** Битый JSON, чужой набор, бюджет поиска в час,
   сценарий на десять тысяч заявок, огромный файл заявок: сервер обязан
   ответить отказом быстро, а не лечь.

Запуск: `uv run python -m bee_routing.loadtest --base http://127.0.0.1:8000`
пишет `data/load/report.json` и `report.md`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from pathlib import Path

import httpx

from .geocode import DATA_DIR

LOAD_DIR = DATA_DIR / "load"
READS = ["/datasets/{ds}", "/plan/latest?dataset_id={ds}", "/datasets/{ds}/control", "/reports"]


def pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    return values[min(len(values) - 1, round(q * (len(values) - 1)))]


async def reader(client: httpx.AsyncClient, ds: str, until: float, out: list[float], errors: list[str]) -> None:
    i = 0
    while time.perf_counter() < until:
        path = READS[i % len(READS)].format(ds=ds)
        i += 1
        started = time.perf_counter()
        try:
            r = await client.get(path)
            if r.status_code >= 500:
                errors.append(f"{r.status_code} {path}")
        except httpx.HTTPError as error:
            errors.append(f"{type(error).__name__} {path}")
        out.append((time.perf_counter() - started) * 1000)


async def step(base: str, ds: str, users: int, seconds: float) -> dict:
    lat: list[float] = []
    errors: list[str] = []
    limits = httpx.Limits(max_connections=users, max_keepalive_connections=users)
    async with httpx.AsyncClient(base_url=base, timeout=30, limits=limits) as client:
        until = time.perf_counter() + seconds
        started = time.perf_counter()
        await asyncio.gather(*(reader(client, ds, until, lat, errors) for _ in range(users)))
        took = time.perf_counter() - started
    return {"users": users, "requests": len(lat), "rps": round(len(lat) / took, 1),
            "p50_ms": round(statistics.median(lat), 1) if lat else 0, "p95_ms": round(pct(lat, 0.95), 1),
            "p99_ms": round(pct(lat, 0.99), 1), "errors": len(errors), "error_sample": errors[:3]}


async def solves(base: str, ds: str, k: int) -> dict:
    async with httpx.AsyncClient(base_url=base, timeout=300) as client:
        async def one() -> tuple[float, int]:
            started = time.perf_counter()
            r = await client.post("/plan", json={"dataset_id": ds, "algorithm": "solver", "remember_latest": False})
            return time.perf_counter() - started, r.status_code
        # Пока идут расчёты, один экран читает: видно, держит ли сервер чтение.
        lat: list[float] = []
        errors: list[str] = []
        done = asyncio.Event()

        async def watch() -> None:
            while not done.is_set():
                started = time.perf_counter()
                try:
                    await client.get(f"/datasets/{ds}")
                except httpx.HTTPError as error:
                    errors.append(type(error).__name__)
                lat.append((time.perf_counter() - started) * 1000)
                await asyncio.sleep(0.2)

        watcher = asyncio.create_task(watch())
        results = await asyncio.gather(*(one() for _ in range(k)))
        done.set()
        await watcher
    return {"parallel": k, "slowest_s": round(max(t for t, _ in results), 1),
            "fastest_s": round(min(t for t, _ in results), 1),
            "statuses": sorted({s for _, s in results}),
            "read_during_p95_ms": round(pct(lat, 0.95), 1), "read_during_max_ms": round(max(lat, default=0), 1)}


async def abuse(base: str, ds: str) -> list[dict]:
    cases = [
        ("Битый JSON в расчёт", "POST", "/plan", {"content": b"{not json", "headers": {"content-type": "application/json"}}),
        ("Чужой набор", "GET", "/datasets/../../etc/passwd", {}),
        ("Несуществующий набор в расчёт", "POST", "/plan", {"json": {"dataset_id": "nope", "algorithm": "solver"}}),
        ("Бюджет поиска в час", "POST", "/plan", {"json": {"dataset_id": ds, "algorithm": "solver", "remember_latest": False,
                                                          "settings": {"options": {"time_limit_s": 3600}}}}),
        ("Сценарий на 10 000 заявок", "POST", "/simulate", {"json": {"dataset_id": ds, "new_requests": 10000, "policy": "static"}}),
        ("Сценарий: зерно и счётчики меньше нуля", "POST", "/race/day", {"json": {"dataset_id": ds, "cancels": -5, "seed": -1}}),
        ("Файл заявок 20 МБ", "POST", "/datasets/upload", {"json": {"filename": "big.csv", "content": "a;b;c\n" * 3_500_000}}),
    ]
    out = []
    async with httpx.AsyncClient(base_url=base, timeout=180) as client:
        for label, method, path, kw in cases:
            started = time.perf_counter()
            try:
                r = await client.request(method, path, **kw)
                status = r.status_code
            except httpx.HTTPError as error:
                status = type(error).__name__
            out.append({"case": label, "status": status, "seconds": round(time.perf_counter() - started, 2)})
    return out


async def main_async(args: argparse.Namespace) -> dict:
    report: dict = {"base": args.base, "dataset": args.dataset, "steps": [], "solves": [], "abuse": []}
    for users in [int(u) for u in args.users.split(",")]:
        report["steps"].append(await step(args.base, args.dataset, users, args.seconds))
        print("чтение", report["steps"][-1], flush=True)
    for k in [int(v) for v in args.solves.split(",")]:
        report["solves"].append(await solves(args.base, args.dataset, k))
        print("расчёты", report["solves"][-1], flush=True)
    if not args.no_abuse:
        report["abuse"] = await abuse(args.base, args.dataset)
        for row in report["abuse"]:
            print("злоупотребление", row, flush=True)
    return report


def to_md(report: dict) -> str:
    lines = [f"# Нагрузка: {report['base']}, набор {report['dataset']}", "",
             "| Экранов | Запросов/с | Медиана, мс | p95, мс | p99, мс | Ошибок |", "|---|---|---|---|---|---|"]
    lines += [f"| {s['users']} | {s['rps']} | {s['p50_ms']} | {s['p95_ms']} | {s['p99_ms']} | {s['errors']} |" for s in report["steps"]]
    lines += ["", "| Расчётов разом | Самый долгий, с | Самый быстрый, с | Коды | Чтение во время, p95 мс |", "|---|---|---|---|---|"]
    lines += [f"| {s['parallel']} | {s['slowest_s']} | {s['fastest_s']} | {s['statuses']} | {s['read_during_p95_ms']} |" for s in report["solves"]]
    if report["abuse"]:
        lines += ["", "| Злоупотребление | Ответ | Секунд |", "|---|---|---|"]
        lines += [f"| {a['case']} | {a['status']} | {a['seconds']} |" for a in report["abuse"]]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Замер нагрузки и злоупотреблений на живом API")
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--dataset", default="yugo-vostok")
    parser.add_argument("--users", default="10,25,50,100")
    parser.add_argument("--seconds", type=float, default=20)
    parser.add_argument("--solves", default="1,3,5")
    parser.add_argument("--no-abuse", action="store_true")
    parser.add_argument("--out", default=str(LOAD_DIR / "report"))
    args = parser.parse_args(argv)
    report = asyncio.run(main_async(args))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    out.with_suffix(".md").write_text(to_md(report), encoding="utf-8")
    print(f"→ {out}.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
