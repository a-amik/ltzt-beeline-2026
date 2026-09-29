"""«На чём ехать»: путь общественным транспортом до следующей заявки по расписанию 2ГИС.

Инженеру без машины мало знать, что до заявки 46 минут. Ему нужен путь:
дойти до остановки, сесть на автобус 891 в 10:21, пересесть на электричку.
Это даёт маршрутизатор общественного транспорта 2ГИС
(`POST /public_transport/2.0`): варианты пути с составом (пешком, автобус,
электричка, пересадка), ожиданием на каждой остановке и точными временами
отправления на ближайший час.

Четыре вещи, которые нельзя ломать:

1. **Спрашивают по требованию, а не заранее.** Один построенный маршрут —
   одна оплата, поэтому путь строится, когда бригада открыла подсказку,
   а не на каждый переезд плана. Ответ держится в памяти процесса
   на пару точек и пятиминутку выезда; на диск он не пишется.
2. **Дата — ближайший такой же день недели, а не дата набора.** День
   заказчика (17.08.2026) уже прошёл, а расписание 2ГИС отдаёт
   на будущие даты; оно повторяется по неделям, поэтому берётся
   ближайший будущий день той же недели в тот же час.
3. **Каждый маршрут списывается с ключа одной единицей.** Сколько стоит
   маршрут демо-ключу, документация не говорит; считаем по верхней оценке,
   чтобы счётчик не врал в меньшую сторону.
4. **Не построилось — говорим почему.** Нет ключа, точки дальше 50 км
   (демо-ключ их не считает), 2ГИС пути не нашёл — это разные ответы,
   и бригада видит, какой из них.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import httpx
from pydantic import BaseModel, Field

from .baseline import OFFICE, start_point
from .checks import to_min
from .dgis import MSK, DgisError, Usage, load_key
from .models import Dataset, Plan


class TransitLeg(BaseModel):
    """Участок пути: пешком, поездка или пересадка."""

    kind: str = Field(description="walk | ride | transfer")
    minutes: int
    wait_min: int = 0
    place: str = Field(default="", description="Остановка или платформа, где участок начинается")
    vehicle: str = ""
    lines: list[str] = Field(default_factory=list)
    hint: str = Field(default="", description="Метро: направление, сколько станций, какой выход")


class TransitOption(BaseModel):
    """Один вариант пути."""

    total_min: int
    arrive: str
    transfers: int
    walk: str
    departures: list[str] = Field(default_factory=list, description="Ближайшие отправления первого транспорта")
    legs: list[TransitLeg] = Field(default_factory=list)


class TransitTrip(BaseModel):
    """Путь к заявке общественным транспортом или причина, почему его нет."""

    request_id: str
    depart: str
    date: str
    origin: str
    target: str
    plan_arrive: str = Field(default="", description="Приезд по плану — с ним сверяется путь по расписанию")
    options: list[TransitOption] = Field(default_factory=list)
    note: str | None = None


ENDPOINT = "https://routing.api.2gis.com/public_transport/2.0"
TRANSPORT = ["pedestrian", "metro", "bus", "tram", "trolleybus", "shuttle_bus",
             "suburban_train", "mcc", "mcd", "light_metro", "monorail"]
KIND_RU = {
    "bus": "автобус", "trolleybus": "троллейбус", "tram": "трамвай", "shuttle_bus": "маршрутка",
    "metro": "метро", "suburban_train": "электричка", "mcc": "МЦК", "mcd": "МЦД",
    "light_metro": "лёгкое метро", "monorail": "монорельс", "river_transport": "речной трамвай",
}
DEMO_LIMIT_KM = 50

_cache: dict[tuple, TransitTrip] = {}


def trip_date(plan_day: date | str | None, today: date | None = None) -> date:
    """Ближайший будущий день той же недели, что и день плана (сегодня не годится: час мог пройти)."""
    today = today or datetime.now(MSK).date()
    if isinstance(plan_day, str):
        try:
            plan_day = date.fromisoformat(plan_day[:10])
        except ValueError:
            plan_day = None
    weekday = plan_day.weekday() if plan_day else 1
    return today + timedelta(days=(weekday - today.weekday()) % 7 or 7)


def _km(a: tuple[float, float], b: tuple[float, float]) -> float:
    from math import asin, cos, radians, sin, sqrt

    dlat, dlon = radians(b[0] - a[0]), radians(b[1] - a[1])
    h = sin(dlat / 2) ** 2 + cos(radians(a[0])) * cos(radians(b[0])) * sin(dlon / 2) ** 2
    return 2 * 6371 * asin(sqrt(h))


def endpoints(plan: Plan, dataset: Dataset, engineer_id: str, request_id: str
              ) -> tuple[tuple[float, float], tuple[float, float], str, str, str, str]:
    """Откуда и куда едет бригада к заявке, во сколько выезжает и как назвать точку отправления."""
    from . import settings

    route = next((r for r in plan.routes if r.engineer_id == engineer_id), None)
    if route is None:
        raise KeyError(f"У бригады {engineer_id} нет маршрута")
    index = next((i for i, s in enumerate(route.stops) if s.request_id == request_id), None)
    if index is None:
        raise KeyError(f"Заявки {request_id} нет в маршруте бригады")
    requests = {r.id: r for r in dataset.requests}
    for event in dataset.events or []:
        if getattr(event, "request", None) is not None:
            requests.setdefault(event.request.id, event.request)
    target = requests[request_id]
    stop = route.stops[index]
    if index > 0:
        prev = requests[route.stops[index - 1].request_id]
        return ((prev.lat, prev.lon), (target.lat, target.lon), stop.depart_prev, prev.address, target.address,
                stop.arrive)
    engineer = next(e for e in settings.effective_engineers(dataset.engineers) if e.id == engineer_id)
    point = start_point(engineer, plan.start or "office")
    if point.startswith(OFFICE) or engineer.home is None:
        # Офис участка бригады в наборе «Вся Москва», иначе офис набора.
        office = next((s.office for s in dataset.sectors if s.id == engineer.sector), dataset.office)
        return ((office.lat, office.lon), (target.lat, target.lon), stop.depart_prev,
                "офис", target.address, stop.arrive)
    return ((engineer.home.lat, engineer.home.lon), (target.lat, target.lon), stop.depart_prev,
            "дом", target.address, stop.arrive)


def parse(routes: list[dict[str, Any]], depart: datetime) -> list[TransitOption]:
    """Ответ 2ГИС → варианты пути: участки, ожидание, отправления."""
    out: list[TransitOption] = []
    for item in routes:
        legs: list[TransitLeg] = []
        for move in item.get("movements") or []:
            kind = move.get("type")
            minutes = round((move.get("moving_duration") or 0) / 60)
            wait = round((move.get("waiting_duration") or 0) / 60)
            place = (move.get("waypoint") or {}).get("name") or ""
            if kind == "passage":
                lines = [r for r in move.get("routes") or []]
                subtype = lines[0].get("subtype", "") if lines else ""
                # Одна остановка обслуживает несколько маршрутов, и 2ГИС повторяет
                # номера по числу вариантов движения: оставляем каждый один раз.
                names = list(dict.fromkeys(n for r in lines for n in (r.get("names") or [])))
                hint = ""
                metro = move.get("metro")
                if metro:
                    # У метро номеров маршрута нет: линия, направление, станции и выход.
                    subtype = subtype or "metro"
                    names = [metro["line_name"]] if metro.get("line_name") else names
                    exit_no = f"выход {metro['exit_entrance_number']}" if metro.get("exit_entrance_number") else ""
                    hint = ", ".join(x for x in (metro.get("ui_direction_suggest"), metro.get("ui_station_count"),
                                                 exit_no) if x)
                subtype = subtype or (move.get("waypoint") or {}).get("subtype", "")
                legs.append(TransitLeg(kind="ride", minutes=minutes, wait_min=wait, place=place,
                                       vehicle=KIND_RU.get(subtype, subtype), lines=names, hint=hint))
            elif kind == "crossing":
                legs.append(TransitLeg(kind="transfer", minutes=minutes, wait_min=wait, place=place))
            elif kind == "walkway" and minutes:
                legs.append(TransitLeg(kind="walk", minutes=minutes, wait_min=wait, place=place))
        departures = [s.get("precise_time") for s in item.get("schedules") or [] if s.get("precise_time")]
        total = round((item.get("total_duration") or 0) / 60)
        out.append(TransitOption(
            total_min=total,
            arrive=(depart + timedelta(minutes=total)).strftime("%H:%M"),
            transfers=int(item.get("transfer_count") or 0),
            walk=str(item.get("total_walkway_distance") or ""),
            departures=departures[:4],
            legs=legs,
        ))
    return out


def trip(plan: Plan, dataset: Dataset, engineer_id: str, request_id: str,
         http: Any = None, today: date | None = None) -> TransitTrip:
    """Путь к заявке общественным транспортом; кэш на пару точек и пятиминутку выезда."""
    origin, target, depart_clock, origin_name, target_name, plan_arrive = endpoints(
        plan, dataset, engineer_id, request_id)
    day = trip_date(dataset.date, today)
    minute = to_min(depart_clock)
    minute -= minute % 5
    depart = datetime(day.year, day.month, day.day, minute // 60, minute % 60, tzinfo=MSK)
    key = (origin, target, day, minute)
    if key in _cache:
        return _cache[key].model_copy(update={"request_id": request_id, "plan_arrive": plan_arrive})
    base = TransitTrip(request_id=request_id, depart=depart.strftime("%H:%M"), date=day.isoformat(),
                       origin=origin_name, target=target_name, plan_arrive=plan_arrive)
    if _km(origin, target) > DEMO_LIMIT_KM:
        return base.model_copy(update={"note": "Точки дальше 50 км: демо-ключ 2ГИС такой путь не строит"})
    usage = Usage()
    api_key, _ = load_key(usage=usage)
    if not api_key:
        return base.model_copy(update={"note": "Ключа 2ГИС нет: путь по расписанию построить нечем"})
    body = {
        "source": {"point": {"lat": origin[0], "lon": origin[1]}},
        "target": {"point": {"lat": target[0], "lon": target[1]}},
        "transport": TRANSPORT,
        "start_time": int(depart.timestamp()),
        "enable_schedule": True,
        "max_result_count": 3,
        "locale": "ru",
    }
    try:
        resp = (http or httpx).post(ENDPOINT, params={"key": api_key}, json=body, timeout=20)
    except httpx.HTTPError as err:
        return base.model_copy(update={"note": f"2ГИС не ответил: {err.__class__.__name__}"})
    if resp.status_code == 204:
        usage.add(1, key=api_key)
        result = base.model_copy(update={"note": "2ГИС не нашёл пути общественным транспортом"})
    elif resp.status_code != 200:
        raise DgisError(f"2ГИС ответил {resp.status_code}: {resp.text[:200]}")
    else:
        usage.add(1, key=api_key)
        result = base.model_copy(update={"options": parse(resp.json(), depart)})
    _cache[key] = result
    return result
