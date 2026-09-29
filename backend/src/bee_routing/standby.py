"""Точка ожидания: где освободившейся бригаде ждать следующую заявку дня.

День в день приходит 10—15 % заявок (Билайн, 19.09.2026), и приходят они
туда же, откуда приходят всегда: в плотные районы. Бригада, у которой
между визитами окно или день кончился раньше смены, может ждать там, где
стоит, а может — ближе к району, откуда заявка вероятнее. Модуль называет
такое место для каждого окна без визитов.

Как выбирается место:

1. **Вероятные заявки — там, где заявки бывают:** адреса заявок региона.
   Другого прогноза у нас нет: один день данных.
2. **Цель — покрытие, а не плотность.** Первая проба вела бригаду в самый
   плотный район рядом и выигрыша не дала: бригады сбивались в одни и те же
   районы (замер 19.09.2026 — свободная бригада стала дальше от заявок дня:
   4,3 → 4,9 км на Востоке). Теперь место выбирается так, чтобы средняя дорога
   от вероятной заявки до **ближайшей свободной** бригады была меньше:
   учитываются бригады, уже ждущие в то же время. Кандидаты — центры районов
   не дальше `standby_radius_km` и само место, где бригада освободилась;
   переезд назван, только если выигрыш не меньше `standby_min_gain_pct`.
3. **Не в ущерб обещанному.** Между визитами крюк до точки ожидания и от неё
   к следующему визиту занимает не больше половины окна; иначе — на месте.
4. **Окно — от `standby_min_gap_min`**, обед из него вычитается.

Это подсказка, а не ход плана: времена визитов и пробег она не меняет.
Что она даёт, меряет `gain`: насколько ближе свободная бригада оказывается
к заявкам дня, если ждёт в названной точке, а не там, где освободилась.
Все числа — настройки (группа «День в день»).
"""

from __future__ import annotations

from collections import defaultdict
from itertools import pairwise

from . import settings
from .checks import to_clock, to_min
from .distance import ROAD_WINDING_FACTOR, haversine_km
from .models import Dataset, Event, Plan, Request, Standby

SPEED_KMH = {"car": 28.0, "bike": 15.0, "transit": 18.0, "foot": 4.5}


def districts(dataset: Dataset) -> dict[str, dict]:
    """Районы региона: доля в заявках и центр."""
    rows: dict[str, list[Request]] = defaultdict(list)
    for req in dataset.requests:
        rows[req.district or "—"].append(req)
    total = max(1, len(dataset.requests))
    return {
        name: {"share": len(reqs) / total, "lat": sum(r.lat for r in reqs) / len(reqs),
               "lon": sum(r.lon for r in reqs) / len(reqs)}
        for name, reqs in rows.items()
    }


def _km(a: tuple[float, float], b: tuple[float, float]) -> float:
    return haversine_km(a[0], a[1], b[0], b[1]) * ROAD_WINDING_FACTOR


def _cost(point: tuple[float, float], demand: list[tuple[float, float]], others: list[tuple[float, float]]) -> float:
    """Средняя дорога от вероятной заявки до ближайшей свободной бригады, если эта встанет в `point`."""
    total = 0.0
    for target in demand:
        near = _km(point, target)
        for other in others:
            near = min(near, _km(other, target))
        total += near
    return total / max(1, len(demand))


def annotate(plan: Plan, dataset: Dataset, by_id: dict[str, Request] | None = None) -> Plan:
    """Назвать точки ожидания по всем окнам без визитов; вернуть тот же план."""
    plan.standby = []
    if not settings.option("standby"):
        return plan
    by_id = by_id or {r.id: r for r in dataset.requests}
    min_gap = int(settings.option("standby_min_gap_min") or 45)
    radius = float(settings.option("standby_radius_km") or 7)
    min_gain = float(settings.option("standby_min_gain_pct") or 0) / 100
    areas = districts(dataset)
    demand = [(r.lat, r.lon) for r in dataset.requests]
    engineers = {e.id: e for e in settings.effective_engineers(dataset.engineers)}
    windows = []
    for route in plan.routes:
        eng = engineers.get(route.engineer_id)
        stops = [s for s in route.stops if s.request_id in by_id]
        if eng is None or not stops:
            continue
        speed = max(SPEED_KMH.get(t.value, 4.5) for t in eng.transports)
        lunch = (to_min(route.break_start), to_min(route.break_end)) if route.break_start else None
        pairs = [(prev, nxt, to_min(prev.end), to_min(nxt.start) - nxt.travel_min) for prev, nxt in pairwise(stops)]
        pairs.append((stops[-1], None, to_min(stops[-1].end), to_min(eng.shift_end)))
        for prev, nxt, start, end in pairs:
            free = end - start
            if lunch and start <= lunch[0] and lunch[1] <= end:
                free -= lunch[1] - lunch[0]
            if free >= min_gap:
                windows.append((start, end, free, route.engineer_id, prev, nxt, speed))
    placed: list[tuple[int, int, tuple[float, float]]] = []
    for start, end, free, eng_id, prev, nxt, speed in sorted(windows, key=lambda w: (w[0], w[3])):
        here = (by_id[prev.request_id].lat, by_id[prev.request_id].lon)
        then = (by_id[nxt.request_id].lat, by_id[nxt.request_id].lon) if nxt else None
        others = [point for s, e, point in placed if s < end and start < e]
        stay = _cost(here, demand, others)
        best = ("", here, 0.0, stay)
        for name, area in areas.items():
            point = (area["lat"], area["lon"])
            km = _km(here, point)
            if km > radius or km < 0.5:
                continue
            if then is not None and (km + _km(point, then) - _km(here, then)) / speed * 60 > free / 2:
                continue  # крюк съел бы больше половины окна: обещанный визит важнее
            cost = _cost(point, demand, others)
            if cost < best[3]:
                best = (name, point, km, cost)
        name, point, km, cost = best
        gain_pct = round(100 * (stay - cost) / stay) if stay else 0
        if not name or (stay - cost) < min_gain * stay:
            name, point, km, gain_pct = by_id[prev.request_id].district or "—", here, 0.0, 0
            text = "Ждать на месте: переезд не приблизит бригады к вероятным заявкам"
        else:
            text = (f"Ждать в районе {name}, {km:.1f} км: вероятная заявка так ближе к свободной бригаде "
                    f"на {gain_pct} %")
        placed.append((start, end, point))
        plan.standby.append(Standby(
            engineer_id=eng_id, after_request_id=prev.request_id, before_request_id=nxt.request_id if nxt else None,
            start=to_clock(start), end=to_clock(end), lat=round(point[0], 6), lon=round(point[1], 6),
            district=name, km=round(km, 1), share_pct=gain_pct, text=text,
        ))
    return plan


def gain(plan: Plan, dataset: Dataset, events: list[Event]) -> dict:
    """Насколько ближе свободная бригада к заявкам дня, если ждёт в названной точке.

    По каждой новой заявке дня: ближайшая из бригад, у которых в эту минуту
    окно без визитов, — от места, где она освободилась, и от точки ожидания.
    """
    by_id = {r.id: r for r in dataset.requests}
    near_here, near_point, count = 0.0, 0.0, 0
    for event in events:
        if event.type != "new_request" or event.request is None:
            continue
        moment = to_min(event.time)
        target = (event.request.lat, event.request.lon)
        free = [s for s in plan.standby if to_min(s.start) <= moment <= to_min(s.end) and s.after_request_id in by_id]
        if not free:
            continue
        here = min(_km((by_id[s.after_request_id].lat, by_id[s.after_request_id].lon), target) for s in free)
        point = min(_km((s.lat, s.lon), target) for s in free)
        near_here, near_point, count = near_here + here, near_point + point, count + 1
    return {"events": count, "km_from_last_visit": round(near_here / count, 2) if count else 0.0,
            "km_from_standby": round(near_point / count, 2) if count else 0.0}
