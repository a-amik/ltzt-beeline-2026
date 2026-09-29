"""Профиль часа по типу дня: из свежей статистики 2ГИС, архив — запасной.

Время в пути на машине зависит и от часа, и от дня недели: пятница тяжелее
будней с обеда, выходные легче весь день, праздник похож на воскресенье.
Сырые ряды 2ГИС живут вне репозитория (`~/.bee-ltzp/traffic-2gis/raw.jsonl`,
разрешение 2ГИС от 16.09.2026); в репозиторий уходит только сводка —
`data/traffic-profile-2gis.json`: отношение времени в пути в каждый час
каждого типа дня к дневному плато будней (11—17 часов) на тех же 12 парах
Юго-востока. Плато — та точка, где снята постоянная поправка ×1,3, поэтому
множители из сводки к ней и прикладываются.

Чего в сводке 2ГИС нет (часа или типа дня), берётся из архива «Яндекс
Пробок» 2013—2015 годов (`data/traffic-profile.json`), приведённого к тому же
плато. Праздник у 2ГИС не снят и берётся как воскресенье: у архива они
совпадают до сотых.

**Статистику 2ГИС спрашивают в день того же класса.** 19.09.2026 проверено:
вторник 22 сентября на 17 часов, спрошенный в среду, дал 1 049 секунд, тот же
запрос в субботу — 903; пятница 25 сентября, спрошенная в субботу, вышла
плоской, как выходной. Ответ зависит от дня запроса, поэтому в сводку идут
только снятия, сделанные в день того же класса: будни и пятница — в будний
день, суббота и воскресенье — в выходной. Часы пятницы, которых так нет,
берутся из будней 2ГИС, умноженных на отношение «пятница к будням» архива.

Тип дня — по дате набора, если настройка `day_type` оставлена `auto`:
понедельник—четверг будни, пятница, суббота, воскресенье, официальные
праздники 2026 года — праздник.

**Общественный транспорт — своим профилем** (`transit` в сводке). Он
пробок почти не знает, зато знает расписание: ночью и в выходные поезда
и автобусы ходят реже, и ожидание на остановке длиннее. 2ГИС считает его
по расписанию на дату, и ответ от дня запроса не зависит (19.09.2026
суббота повторила среду до секунды) — фильтра по дню запроса здесь нет.
Множитель часа приведён к среднему будней в 10, 13 и 19 часов: на этих
часах снята постоянная поправка ×0,78 к модели «18 км/ч + 8 минут».
Пятница берётся как будни, праздник — как воскресенье.

Запуск: `uv run python -m bee_routing.day_profile` — пересобрать сводку из сырых рядов.
"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from datetime import date
from functools import lru_cache

from .geocode import DATA_DIR

ARCHIVE_PATH = DATA_DIR / "traffic-profile.json"
DGIS_PATH = DATA_DIR / "traffic-profile-2gis.json"
DAY_TYPES = ("workday", "friday", "saturday", "sunday", "holiday")
DAY_TYPE_RU = {
    "workday": "будни",
    "friday": "пятница",
    "saturday": "суббота",
    "sunday": "воскресенье",
    "holiday": "праздник",
}
PLATEAU = range(11, 18)
WORK_HOURS = range(10, 22)

# Нерабочие праздничные дни 2026 года по постановлению правительства о переносе выходных.
HOLIDAYS_2026 = {
    date(2026, 1, d) for d in range(1, 9)
} | {date(2026, 2, 23), date(2026, 3, 9), date(2026, 5, 1), date(2026, 5, 11),
     date(2026, 6, 12), date(2026, 11, 4), date(2026, 12, 31)}


def day_type_of(day: date | str | None) -> str:
    """Тип дня по дате: праздник, выходной, пятница или будни."""
    if day is None:
        return "workday"
    if isinstance(day, str):
        try:
            day = date.fromisoformat(day[:10])
        except ValueError:
            return "workday"
    if day in HOLIDAYS_2026:
        return "holiday"
    return {4: "friday", 5: "saturday", 6: "sunday"}.get(day.weekday(), "workday")


WEEKEND = ("saturday", "sunday", "holiday")


def asked_on_matching_day(row: dict) -> bool:
    """Снятие годится, если спрошено в день того же класса: будни — в будни, выходные — в выходные."""
    asked = row.get("asked_at", "")[:10]
    try:
        weekend_asked = date.fromisoformat(asked).weekday() >= 5
    except ValueError:
        return True
    return weekend_asked == (row.get("day_type") in WEEKEND)


def build_dgis(raw_path=None) -> dict:
    """Сводка из сырых рядов: множитель часа к будничному плато по каждой паре, среднее по парам."""
    from .dgis_collect import RAW_PATH

    path = raw_path or RAW_PATH
    with open(path, encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh]
    stats = [r for r in rows if r.get("kind") == "stats" and r.get("duration_s") and r.get("status") == "OK"
             and asked_on_matching_day(r)]
    # Час одного типа дня мог быть снят на разные даты: берётся самое свежее
    # снятие, чтобы профиль дня шёл с одной даты, а не ступеньками из двух.
    stats.sort(key=lambda r: (r["date"], r.get("asked_at", "")))
    by_pair: dict[tuple[str, str], dict[tuple[str, int], float]] = defaultdict(dict)
    for r in stats:
        by_pair[(r["source"], r["target"])][(r["day_type"], int(r["hour_msk"]))] = float(r["duration_s"])
    ratios: dict[str, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
    for series in by_pair.values():
        base = [series[("workday", h)] for h in PLATEAU if ("workday", h) in series]
        if len(base) < 4:
            continue
        plateau = statistics.mean(base)
        for (day_type, hour), seconds in series.items():
            ratios[day_type][hour].append(seconds / plateau)
    out = {
        day_type: {str(h): round(statistics.mean(v), 3) for h, v in sorted(hours.items())}
        for day_type, hours in ratios.items()
    }
    latest: dict[str, str] = {}
    for r in stats:
        latest[r["day_type"]] = max(latest.get(r["day_type"], ""), r["date"])
    dates = sorted({r["date"] for r in stats})
    transit = _transit_ratios(rows)
    return {
        "_": ("Отношение времени в пути на машине к дневному плато будней (11—17 ч) "
              "по статистике пробок 2ГИС на 12 парах Юго-востока; среднее по парам. "
              "Собирает `python -m bee_routing.day_profile` из рядов вне репозитория."),
        "source": "2ГИС Distance Matrix, режим statistics",
        "pairs": len(by_pair),
        "dates": [dates[0], dates[-1]] if dates else [],
        "day_dates": latest,
        "day_types": out,
        "transit": transit,
    }


TRANSIT_BASE_HOURS = (10, 13, 19)


def _transit_ratios(rows: list[dict]) -> dict[str, dict[str, float]]:
    """Общественный транспорт: час каждого типа дня к среднему будней в 10, 13 и 19."""
    ok = [r for r in rows if r.get("kind") == "modes" and r.get("profile") == "transit"
          and r.get("duration_s") and r.get("status") == "OK"]
    ok.sort(key=lambda r: (r["date"], r.get("asked_at", "")))
    by_pair: dict[tuple[str, str], dict[tuple[str, int], float]] = defaultdict(dict)
    for r in ok:
        by_pair[(r["source"], r["target"])][(r["day_type"], int(r["hour_msk"]))] = float(r["duration_s"])
    ratios: dict[str, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
    for series in by_pair.values():
        base = [series[("workday", h)] for h in TRANSIT_BASE_HOURS if ("workday", h) in series]
        if len(base) < len(TRANSIT_BASE_HOURS):
            continue
        mean = statistics.mean(base)
        for (day_type, hour), seconds in series.items():
            ratios[day_type][hour].append(seconds / mean)
    return {day: {str(h): round(statistics.mean(v), 3) for h, v in sorted(hours.items())}
            for day, hours in ratios.items()}


@lru_cache(maxsize=1)
def _archive() -> dict[str, dict[int, float]]:
    try:
        raw = json.loads(ARCHIVE_PATH.read_text(encoding="utf-8"))["day_types"]
    except (FileNotFoundError, KeyError, ValueError):
        return {}
    work = raw.get("workday", [])
    base = statistics.mean(r["k_mean"] for r in work if r["hour"] in PLATEAU) if work else 1.0
    return {day: {int(r["hour"]): float(r["k_mean"]) / base for r in rows} for day, rows in raw.items()}


@lru_cache(maxsize=1)
def _dgis() -> dict[str, dict[int, float]]:
    try:
        raw = json.loads(DGIS_PATH.read_text(encoding="utf-8"))["day_types"]
    except (FileNotFoundError, KeyError, ValueError):
        return {}
    return {day: {int(h): float(k) for h, k in hours.items()} for day, hours in raw.items()}


@lru_cache(maxsize=1)
def _dgis_transit() -> dict[str, dict[int, float]]:
    try:
        raw = json.loads(DGIS_PATH.read_text(encoding="utf-8")).get("transit", {})
    except (FileNotFoundError, ValueError):
        return {}
    return {day: {int(h): float(k) for h, k in hours.items()} for day, hours in raw.items()}


TRANSIT_DAY = {"friday": "workday", "holiday": "sunday"}


@lru_cache(maxsize=8)
def transit_profile(day_type: str) -> dict[int, float]:
    """Множитель часа общественного транспорта; нет снятого дня — будни, нет часа — 1."""
    table = _dgis_transit()
    day = TRANSIT_DAY.get(day_type, day_type)
    return dict(table.get(day) or table.get("workday") or {})


@lru_cache(maxsize=8)
def transit_level(day_type: str) -> float:
    """Средний множитель рабочего дня (10—22) общественного транспорта — для решателя."""
    row = transit_profile(day_type)
    hours = [h for h in WORK_HOURS if h in row]
    return round(statistics.mean(row[h] for h in hours), 3) if hours else 1.0


@lru_cache(maxsize=8)
def profile(day_type: str) -> dict[int, float]:
    """Множитель по часам для типа дня: 2ГИС, где снято; иначе архив того же типа дня."""
    fresh, old = _dgis(), _archive()
    source = "sunday" if day_type == "holiday" and "holiday" not in fresh else day_type
    out: dict[int, float] = {}
    for hour in range(24):
        if hour in fresh.get(source, {}):
            out[hour] = fresh[source][hour]
        elif hour in fresh.get("workday", {}) and hour in old.get(day_type, {}) and old["workday"].get(hour):
            # Своего часа у 2ГИС нет — будни 2ГИС в пропорции «этот день к будням» архива.
            out[hour] = fresh["workday"][hour] * old[day_type][hour] / old["workday"][hour]
        elif hour in old.get(day_type, {}):
            out[hour] = old[day_type][hour]
        elif hour in old.get("workday", {}):
            out[hour] = old["workday"][hour]
    return {h: round(k, 3) for h, k in out.items()}


@lru_cache(maxsize=8)
def day_level(day_type: str) -> float:
    """Средний множитель рабочего дня (10—22) к будням: для решателя, который часа не знает."""
    mine, work = profile(day_type), profile("workday")
    hours = [h for h in WORK_HOURS if h in mine and h in work]
    if not hours:
        return 1.0
    return round(statistics.mean(mine[h] for h in hours) / statistics.mean(work[h] for h in hours), 3)


def reset() -> None:
    """Сбросить кэш профилей — после пересборки сводки."""
    for fn in (_archive, _dgis, profile, day_level, _dgis_transit, transit_profile, transit_level):
        fn.cache_clear()


def main() -> int:
    summary = build_dgis()
    DGIS_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    reset()
    for day_type in DAY_TYPES:
        row = profile(day_type)
        print(f"{DAY_TYPE_RU[day_type]:12} уровень дня {day_level(day_type):.3f} · "
              + " ".join(f"{h}:{row.get(h, 0):.2f}" for h in range(8, 23)))
    for day_type in DAY_TYPES:
        row = transit_profile(day_type)
        print(f"транспорт {DAY_TYPE_RU[day_type]:12} уровень {transit_level(day_type):.3f} · "
              + " ".join(f"{h}:{row.get(h, 0):.2f}" for h in range(7, 23)))
    print(DGIS_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
