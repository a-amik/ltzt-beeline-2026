"""Карта дефицита: где и в какие окна спрос выше мощности бригад.

Для сервисных отделов и продаж: какие окна в каком районе можно обещать
клиенту, какие — только с доплатой или переносом, где свободные бригады
простаивают и можно брать заявки день в день.

Счёт по плану, а не по датасету: мощность — это свободное время бригад
именно в этом плане. На районы и двухчасовые слоты (окна заказчика —
двухчасовые, 10—22):

- **спрос** — нормо-минуты заявок района, чьё окно покрывает слот; заявка
  с окном на весь день делится поровну между слотами окна;
- **закрыто** — нормо-минуты визитов района, начатых в этом слоте;
- **свободно** — минуты бригад, которые в слоте не едут и не работают,
  а стоят в пределах досягаемости района (по прямой не дальше 7 км —
  около получаса общественным транспортом); свободная бригада рядом
  с двумя районами делится между ними поровну;
- **давление** — спрос к «закрыто плюс свободно». Больше 1 — дефицит:
  обещать это окно новым клиентам нельзя; меньше 0,5 при часе свободы
  рядом — окно можно продавать и брать заявки день в день.

Три вещи, которые нельзя ломать:

1. **Дефицит считается по плану**, а не по числу заявок: тот же спрос при
   другом плане даёт другую карту.
2. **Свободное время не двоится:** бригада рядом с двумя районами делит
   свои минуты между ними.
3. **Подсказка — действие словами**, с числом: «не обещать 10—12 в Кашире:
   спрос 180 нормо-минут, закрыть можно 60».
"""

from __future__ import annotations

from collections import defaultdict

from .checks import to_clock, to_min
from .distance import haversine_km
from .economy import norm_minutes, tariffs
from .insertion import requests_of
from .models import Dataset, DeficitAdvice, DeficitArea, DeficitMap, DeficitSlot, Plan

SLOT_MIN = 120
REACH_KM = 7.0


def slots_of(dataset: Dataset) -> list[tuple[int, int]]:
    """Двухчасовые слоты от начала первой смены до конца последней."""
    lo = min(to_min(e.shift_start) for e in dataset.engineers)
    hi = max(to_min(e.shift_end) for e in dataset.engineers)
    return [(t, min(t + SLOT_MIN, hi)) for t in range(lo, hi, SLOT_MIN)]


def plural(n: int, one: str, few: str, many: str) -> str:
    """1 заявка, 2 заявки, 5 заявок."""
    n = abs(n)
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def minutes_word(n: int) -> str:
    return plural(n, "минута", "минуты", "минут")


def norm_word(n: int) -> str:
    return plural(n, "нормо-минута", "нормо-минуты", "нормо-минут")


def _weight(advice: DeficitAdvice) -> int:
    """Вес подсказки для порядка: число в тексте, по которому видно, насколько важно."""
    digits = [int(x) for x in __import__("re").findall(r"\d+", advice.text.replace("\u00a0", ""))]
    return max(digits) if digits else 0


def _district_advice(district: str, cells: list[DeficitSlot], slots: list[tuple[int, int]]) -> list[DeficitAdvice]:
    """Подряд идущие окна одного уровня — одной подсказкой: «не обещать 10:00—16:00»."""
    out: list[DeficitAdvice] = []
    i = 0
    while i < len(cells):
        level = cells[i].level
        j = i
        while j + 1 < len(cells) and cells[j + 1].level == level:
            j += 1
        run = cells[i:j + 1]
        window = f"{to_clock(slots[i][0])}–{to_clock(slots[j][1])}"
        d = sum(c.demand_min for c in run)
        cap = sum(c.served_min + c.free_min for c in run)
        miss = sum(c.unassigned for c in run)
        free = sum(c.free_min for c in run)
        if level == "deficit" and (d - cap >= 30 or miss):
            reason = (f"спрос {d} {norm_word(d)}, закрыть можно {cap}" if d > cap
                      else "по времени бригады есть, но с нужным навыком рядом нет")
            out.append(DeficitAdvice(
                district=district, window=window, level=level,
                text=(f"Не обещать {window} в районе {district}: {reason}"
                      + (f"; {miss} {plural(miss, 'заявка', 'заявки', 'заявок')} уже без бригады" if miss else "")
                      + ". Предлагать соседнее окно или доплату за срочность"),
            ))
        elif level == "free" and free >= 150:
            visits = free // 90
            out.append(DeficitAdvice(
                district=district, window=window, level=level,
                text=(f"Продавать {window} в районе {district}: рядом {free} свободных {minutes_word(free)} бригад — "
                      f"ещё {visits} {plural(visits, 'визит', 'визита', 'визитов')} день в день"),
            ))
        i = j + 1
    return out


def _level(pressure: float, free_min: int, missing: int = 0) -> str:
    if pressure >= 1.1 or missing:
        return "deficit"
    if pressure >= 0.8:
        return "tight"
    if pressure < 0.5 and free_min >= 60:
        return "free"
    return "ok"


def _positions(plan: Plan, dataset: Dataset, by_id: dict, mid: int) -> dict[str, tuple[float, float, int]]:
    """Где каждая бригада в середине слота и сколько минут слота у неё свободно."""
    out: dict[str, tuple[float, float, int]] = {}
    start_pt = (dataset.office.lat, dataset.office.lon)
    homes = {e.id: (e.home.lat, e.home.lon) for e in dataset.engineers if e.home is not None}
    crews = (plan.settings or {}).get("crews", {})
    shifts = {e.id: (to_min(e.shift_start), to_min(e.shift_end)) for e in dataset.engineers}
    lo, hi = mid - SLOT_MIN // 2, mid + SLOT_MIN // 2
    for route in plan.routes:
        own = crews.get(route.engineer_id, {}).get("home")
        home = (own["lat"], own["lon"]) if own else homes.get(route.engineer_id)
        point = home if plan.start == "home" and home else start_pt
        s0, s1 = shifts.get(route.engineer_id, (lo, hi))
        busy = 0
        for stop in route.stops:
            req = by_id.get(stop.request_id)
            a, b = to_min(stop.depart_prev), to_min(stop.end)
            busy += max(0, min(b, hi) - max(a, lo)) - max(
                0, min(to_min(stop.start), hi) - max(to_min(stop.arrive), lo))  # ожидание — свободно
            if req is not None and to_min(stop.depart_prev) <= mid:
                point = (req.lat, req.lon)
        if route.break_start and route.break_end:
            busy += max(0, min(to_min(route.break_end), hi) - max(to_min(route.break_start), lo))
        on_shift = max(0, min(s1, hi) - max(s0, lo))
        out[route.engineer_id] = (point[0], point[1], max(0, on_shift - busy))
    return out


def deficit_map(plan: Plan, dataset: Dataset) -> DeficitMap:
    """Районы × слоты: спрос, закрыто, свободно рядом, давление и подсказки."""
    conf = tariffs()
    by_id = requests_of(dataset, plan)
    requests = [by_id[i] for i in {s.request_id for r in plan.routes for s in r.stops}
                | {u.request_id for u in plan.unassigned} if i in by_id]
    unassigned = {u.request_id for u in plan.unassigned}
    slots = slots_of(dataset)
    names = [f"{to_clock(a)}–{to_clock(b)}" for a, b in slots]

    groups: dict[str, list] = defaultdict(list)
    for req in requests:
        groups[req.district or "—"].append(req)
    centers = {d: (sum(r.lat for r in rs) / len(rs), sum(r.lon for r in rs) / len(rs)) for d, rs in groups.items()}

    demand = defaultdict(float)
    served = defaultdict(float)
    missing = defaultdict(int)
    for req in requests:
        ws, we = to_min(req.window_start), to_min(req.window_end)
        covered = [i for i, (a, b) in enumerate(slots) if a < we and b > ws]
        share = norm_minutes(req, conf) / max(len(covered), 1)
        for i in covered:
            demand[(req.district or "—", i)] += share
            if req.id in unassigned:
                missing[(req.district or "—", i)] += 1
    for route in plan.routes:
        for stop in route.stops:
            req = by_id.get(stop.request_id)
            if req is None or stop.status == "no_show":
                continue
            t = to_min(stop.start)
            i = next((k for k, (a, b) in enumerate(slots) if a <= t < b), None)
            if i is not None:
                served[(req.district or "—", i)] += norm_minutes(req, conf)

    free = defaultdict(float)
    for i, (a, b) in enumerate(slots):
        for lat, lon, minutes in _positions(plan, dataset, by_id, (a + b) // 2).values():
            if minutes <= 0:
                continue
            near = [d for d, (clat, clon) in centers.items() if haversine_km(lat, lon, clat, clon) <= REACH_KM]
            for d in near:
                free[(d, i)] += minutes / len(near)

    areas: list[DeficitArea] = []
    advice: list[DeficitAdvice] = []
    totals = [defaultdict(float) for _ in slots]
    for district, reqs in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        cells = []
        for i, name in enumerate(names):
            d, s, f = demand[(district, i)], served[(district, i)], free[(district, i)]
            pressure = round(d / max(s + f, 1.0), 2) if d else 0.0
            level = _level(pressure, int(f), missing[(district, i)]) if d or f else "ok"
            if not d and f >= 60:
                level = "free"
            cells.append(DeficitSlot(window=name, demand_min=round(d), served_min=round(s), free_min=round(f),
                                     unassigned=missing[(district, i)], pressure=pressure, level=level))
            for key, value in (("d", d), ("s", s), ("f", f), ("u", missing[(district, i)])):
                totals[i][key] += value
        advice.extend(_district_advice(district, cells, slots))
        lat, lon = centers[district]
        areas.append(DeficitArea(district=district, lat=round(lat, 5), lon=round(lon, 5), requests=len(reqs), slots=cells))

    total_rows = []
    for i, name in enumerate(names):
        t = totals[i]
        pressure = round(t["d"] / max(t["s"] + t["f"], 1.0), 2) if t["d"] else 0.0
        total_rows.append(DeficitSlot(window=name, demand_min=round(t["d"]), served_min=round(t["s"]),
                                      free_min=round(t["f"]), unassigned=int(t["u"]), pressure=pressure,
                                      level=_level(pressure, int(t["f"]), int(t["u"]))))
    for row in total_rows:
        if row.level == "free" and row.free_min >= 180:
            visits = row.free_min // 90
            advice.append(DeficitAdvice(
                district="весь регион", window=row.window, level="free",
                text=(f"По региону в {row.window} свободно {row.free_min} {minutes_word(row.free_min)} бригад — около "
                      f"{visits} {plural(visits, 'визита', 'визитов', 'визитов')}. Продавать это окно "
                      "и брать в него заявки день в день"),
            ))
    order = {"deficit": 0, "free": 1}
    advice.sort(key=lambda a: (order.get(a.level, 2), -_weight(a)))
    return DeficitMap(plan_id=plan.id, windows=names, areas=areas, totals=total_rows, advice=advice[:12])
