"""Сборщик рядов 2ГИС: профиль часа, виды транспорта и живые пробки по точкам региона.

Зачем. Архив пробок 2013—2015 годов даёт форму суток, но не сегодняшний
масштаб. Сборщик снимает у 2ГИС три ряда по одним и тем же 12 парам
точек Юго-востока (офис и центральные заявки зон) и сводит их с OSRM:

- `sweep`, статистика: автомобиль по статистике пробок на каждый час
  рабочего дня, вечер пятницы и субботу — форма суток сегодняшней Москвы;
- `sweep`, виды транспорта: велосипед, самокат, пешком в 13:00 и общественный
  транспорт по расписанию в 10, 13 и 19 — во сколько раз наши профили OSRM
  расходятся с 2ГИС;
- `live`, текущие пробки: четыре пары от офиса, запускается заданием launchd
  в будни в 7, 10, 13, 16, 19 и 21 — насколько статистика совпадает с днём.

Три вещи, которые нельзя ломать:

1. **Сырые ответы живут вне репозитория**, в `~/.bee-ltzp/traffic-2gis/`.
   Хранить их позволяет разрешение 2ГИС, полученное командой
   16.09.2026 (без него п. 3.1 оферты запрещает). В git и на сайт уходят
   только сводные коэффициенты из `report`.
2. **Задание не повторяется.** Каждое снятие статистики записано
   в `done.json`, и повторный `sweep` доснимает только то, чего нет:
   бюджет демо-ключа — 1 000 пар на весь срок.
3. **Живой ряд не трогает запас пятницы** (`FRIDAY_RESERVE`). Ключей
   несколько, и расходуются они по порядку; живой сбор спрашивает, пока
   на всех ключах вместе остаётся больше запаса на пересъёмку пятницы,
   а дойдя до него, ничего не спрашивает и пишет об этом в журнал.

Запуск:
    uv run python -m bee_routing.dgis_collect plan
    uv run python -m bee_routing.dgis_collect sweep
    uv run python -m bee_routing.dgis_collect live
    uv run python -m bee_routing.dgis_collect report --out <файл.json>
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from .dgis import (
    DEFAULT_PICK,
    HOME_DIR,
    MSK,
    BudgetExceeded,
    DgisMatrix,
    RateLimited,
    Usage,
    load_key,
    msk_to_rfc3339,
    next_weekday,
    total_left,
    units_for,
)

DATA_DIR = HOME_DIR / "traffic-2gis"
RAW_PATH = DATA_DIR / "raw.jsonl"
DONE_PATH = DATA_DIR / "done.json"
DATASET = "yugo-vostok"
LIVE_HOURS = (7, 10, 13, 16, 19, 21)
# Пересъёмка пятницы: 16 часов × 12 пар; живой ряд её не съедает.
FRIDAY_RESERVE = 192
DAY_WEEKDAY = {"workday": 1, "friday": 4, "saturday": 5, "sunday": 6}


@dataclass(frozen=True)
class Task:
    """Одно снятие: профиль, тип дня и час старта по Москве."""

    kind: str
    profile: str
    day_type: str
    hour: int

    @property
    def id(self) -> str:
        return f"{self.kind}:{self.profile}:{self.day_type}:{self.hour:02d}"


def sweep_tasks() -> list[Task]:
    """Всё, что снимается один раз: профиль автомобиля и виды транспорта."""
    # Профиль часа по каждому типу дня целиком: пятница тяжелее будней
    # с обеда, выходные легче весь день, и форма суток у них своя.
    tasks = [Task("stats", "car", day, h) for day in ("workday", "friday", "saturday", "sunday")
             for h in range(7, 23)]
    tasks += [Task("modes", p, "workday", 13) for p in ("bike", "scooter", "foot")]
    # Общественный транспорт по расписанию: каждый час будней и выходных —
    # у выходных своё расписание. Ответ зависит от расписания на дату,
    # а не от дня запроса (19.09.2026: суббота повторила среду до секунды).
    tasks += [Task("modes", "transit", day, h) for day in ("workday", "saturday", "sunday")
              for h in range(7, 23)]
    return tasks


def load_points() -> tuple[list[str], list[tuple[float, float]], list[int], list[int]]:
    from .matrices import DATASETS_DIR, points_of

    dataset = json.loads((DATASETS_DIR / f"{DATASET}.json").read_text(encoding="utf-8"))
    ids, coords = points_of(dataset)
    index = {name: i for i, name in enumerate(ids)}
    pick = DEFAULT_PICK[DATASET]
    return ids, coords, [index[n] for n in pick["sources"]], [index[n] for n in pick["targets"]]


def read_json(path: Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def append_raw(records: list[dict], path: Path = RAW_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def records_of(legs, ids, task: Task, day: date, mode: str) -> list[dict]:
    asked = datetime.now(MSK).isoformat(timespec="seconds")
    return [
        {
            "task": task.id, "kind": task.kind, "mode": mode, "profile": task.profile,
            "day_type": task.day_type, "date": day.isoformat(), "hour_msk": task.hour,
            "asked_at": asked, "source": ids[leg.source], "target": ids[leg.target],
            "status": leg.status, "duration_s": leg.duration_s, "distance_m": leg.distance_m,
        }
        for leg in legs
    ]


# Виды общественного транспорта Москвы для расписания 2ГИС.
TRANSIT_MODES = ["bus", "trolleybus", "tram", "shuttle_bus", "metro", "suburban_train"]
PAUSE_S = 65


def with_retry(call, attempts: int = 3):
    """Поминутный предел ключа 2ГИС: переждать минуту и повторить."""
    for attempt in range(attempts):
        try:
            return call()
        except RateLimited:
            if attempt == attempts - 1:
                raise
            print(f"2ГИС: поминутный предел, жду {PAUSE_S} с")
            time.sleep(PAUSE_S)
    return None


def client(need: int = 1) -> DgisMatrix:
    """Клиент на первом ключе, у которого осталось `need` единиц."""
    usage = Usage()
    key, budget = load_key(usage=usage, need=need)
    if not key:
        raise SystemExit("Ключа 2ГИС нет: ~/.bee-ltzp/2gis.json или DGIS_API_KEY")
    return DgisMatrix(key, budget, usage)


def cmd_plan() -> int:
    ids, _, sources, targets = load_points()
    done = set(read_json(DONE_PATH, []))
    pairs = units_for(len(sources), len(targets))
    todo = [t for t in sweep_tasks() if t.id not in done]
    left = total_left()
    print(f"Пары: {[ids[i] for i in sources]} × {[ids[i] for i in targets]} = {pairs}")
    print(f"sweep: заданий {len(sweep_tasks())}, осталось {len(todo)} → {len(todo) * pairs} единиц")
    live_spent = sum(1 for r in read_raw() if r["kind"] == "live")
    print(f"live: снято {live_spent} пар, по 4 единицы за прогон; запас пятницы {FRIDAY_RESERVE}")
    print(f"Ключи: осталось {left} единиц на всех вместе")
    return 0


def cmd_sweep() -> int:
    ids, coords, sources, targets = load_points()
    api = client()
    done = read_json(DONE_PATH, [])
    for task in sweep_tasks():
        if task.id in done:
            continue
        day = next_weekday(DAY_WEEKDAY[task.day_type])
        start = msk_to_rfc3339(day, task.hour)
        mode = "statistics" if task.profile == "car" else "jam"
        try:
            legs = with_retry(
                lambda t=task, st=start, m=mode, a=api: a.matrix(
                    coords, sources, targets, t.profile, [st], m, TRANSIT_MODES
                )
            )
        except BudgetExceeded as err:
            # Этот ключ кончился — следующий по списку, если у него хватает.
            api = client(need=units_for(len(sources), len(targets)))
            if api.left < units_for(len(sources), len(targets)):
                print(f"Стоп: {err}; ключей с запасом больше нет")
                break
            print(f"Ключ исчерпан, дальше ключ {api.key[:4]}…")
            try:
                legs = with_retry(
                    lambda t=task, st=start, m=mode, a=api: a.matrix(
                        coords, sources, targets, t.profile, [st], m, TRANSIT_MODES
                    )
                )
            except BudgetExceeded as err2:
                print(f"Стоп: {err2}")
                break
        append_raw(records_of(legs, ids, task, day, mode))
        done.append(task.id)
        DONE_PATH.write_text(json.dumps(done, ensure_ascii=False, indent=1) + "\n")
        ok = sum(1 for leg in legs if leg.status == "OK")
        print(f"{task.id}: {ok}/{len(legs)} OK, израсходовано {api.usage.spent}")
    return 0


def cmd_friday() -> int:
    """Пятница снимается в пятницу: статистика 2ГИС зависит от дня запроса.

    Задание launchd запускает это по пятницам утром; в другие дни команда ничего не
    спрашивает. Снятия пятницы из прошлых прогонов снимаются с учёта и
    доснимаются заново на ближайшую пятницу, то есть на сегодня плюс неделя.
    """
    now = datetime.now(MSK)
    if now.weekday() != 4:
        print(f"{now:%Y-%m-%d %H:%M} friday: не пятница, запросов нет")
        return 0
    done = read_json(DONE_PATH, [])
    asked_today = {r["task"] for r in read_raw() if r["kind"] == "stats" and r["asked_at"][:10] == now.date().isoformat()}
    keep = [t for t in done if not t.startswith("stats:car:friday:") or t in asked_today]
    DONE_PATH.write_text(json.dumps(keep, ensure_ascii=False, indent=1) + "\n")
    return cmd_sweep()


def cmd_live(force: bool = False) -> int:
    ids, coords, _, targets = load_points()
    now = datetime.now(MSK)
    if total_left() - len(targets) < FRIDAY_RESERVE:
        print(f"{now:%Y-%m-%d %H:%M} live: на ключах остался только запас пятницы, "
              f"запросов нет; нужен новый ключ в ~/.bee-ltzp/2gis.json")
        return 0
    if not force and (now.weekday() >= 5 or now.hour not in LIVE_HOURS):
        print(f"{now:%Y-%m-%d %H:%M} live: не рабочий час, запросов нет")
        return 0
    api = client(need=len(targets))
    office = ids.index("office")
    task = Task("live", "car", "friday" if now.weekday() == 4 else "workday", now.hour)
    try:
        legs = with_retry(lambda: api.matrix(coords, [office], targets, "car", None, "jam"))
    except BudgetExceeded as err:
        print(f"{now:%Y-%m-%d %H:%M} live: бюджет ключа исчерпан ({err}), нужен новый ключ в ~/.bee-ltzp/2gis.json")
        return 0
    append_raw(records_of(legs, ids, task, now.date(), "jam"))
    print(f"{now:%Y-%m-%d %H:%M} live: {len(legs)} пар, израсходовано {api.usage.spent}")
    return 0


def read_raw(path: Path = RAW_PATH) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


OSRM_PROFILE = {"car": "car", "bike": "bike", "scooter": "bike", "foot": "foot", "transit": "transit"}


def summarize(raw: list[dict], osrm: dict[str, dict]) -> dict:
    """Сводка: отношение 2ГИС к OSRM по сумме пар, без сырых времён."""

    def ratio(rows: list[dict]) -> dict | None:
        good = []
        for r in rows:
            table = osrm.get(OSRM_PROFILE[r["profile"]])
            if r["status"] != "OK" or not table:
                continue
            i, j = table["index"][r["source"]], table["index"][r["target"]]
            good.append((r["duration_s"] / 60, table["duration_min"][i][j]))
        base = sum(b for _, b in good)
        if not good or base <= 0:
            return None
        return {"k": round(sum(d for d, _ in good) / base, 2), "pairs": len(good)}

    groups: dict[tuple, list[dict]] = {}
    for r in raw:
        groups.setdefault((r["kind"], r["profile"], r["day_type"], r["hour_msk"]), []).append(r)
    out: dict = {"stats": {}, "modes": {}, "live": {}}
    for (kind, profile, day_type, hour), rows in sorted(groups.items()):
        value = ratio(rows)
        if value is None:
            continue
        if kind == "stats":
            out["stats"].setdefault(day_type, {})[str(hour)] = value
        elif kind == "modes":
            out["modes"].setdefault(profile, {})[str(hour)] = value
        else:
            out["live"].setdefault(day_type, {})[str(hour)] = value
    live_vs_stats = []
    for day_type, hours in out["live"].items():
        for hour, value in hours.items():
            stat = out["stats"].get("workday", {}).get(hour)
            if stat:
                live_vs_stats.append({"day_type": day_type, "hour": int(hour),
                                      "live_k": value["k"], "stats_k": stat["k"]})
    out["live_vs_stats"] = live_vs_stats
    return out


def load_osrm() -> dict[str, dict]:
    from .matrices import MATRICES_DIR

    tables = {}
    for profile in ("car", "bike", "foot", "transit"):
        path = MATRICES_DIR / f"{DATASET}-{profile}.json"
        if path.exists():
            table = json.loads(path.read_text(encoding="utf-8"))
            table["index"] = {name: i for i, name in enumerate(table["ids"])}
            tables[profile] = table
    return tables


def cmd_report(out: str | None) -> int:
    summary = summarize(read_raw(), load_osrm())
    summary["_"] = (
        "2ГИС / OSRM по сумме 12 пар Юго-востока (3 точки × 4). k = во сколько раз "
        "время 2ГИС больше свободной сети OSRM. Сырых времён 2ГИС здесь нет."
    )
    summary["dataset"] = DATASET
    text = json.dumps(summary, ensure_ascii=False, indent=1)
    if out:
        Path(out).write_text(text + "\n", encoding="utf-8")
        print(f"Сводка записана: {out}")
    else:
        print(text)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bee_routing.dgis_collect",
                                     description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("plan", help="что снято, что осталось и сколько стоит")
    sub.add_parser("sweep", help="снять статистику и виды транспорта")
    sub.add_parser("friday", help="в пятницу переснять статистику пятницы")
    live = sub.add_parser("live", help="один прогон по текущим пробкам")
    live.add_argument("--force", action="store_true", help="не смотреть на час и день")
    rep = sub.add_parser("report", help="сводка 2ГИС против OSRM")
    rep.add_argument("--out")
    args = parser.parse_args(argv)
    if args.cmd == "plan":
        return cmd_plan()
    if args.cmd == "sweep":
        return cmd_sweep()
    if args.cmd == "friday":
        return cmd_friday()
    if args.cmd == "live":
        return cmd_live(args.force)
    return cmd_report(args.out)


if __name__ == "__main__":
    raise SystemExit(main())
