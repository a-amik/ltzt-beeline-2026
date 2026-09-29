"""Приложение бригады для показа: профиль, способы поездки, связь, отчёт, смена, история.

Всё здесь — для демонстрации, как у приложений курьеров (Яндекс Про, Uber
Driver), и без учётных записей: бригада выбирается на входе. Проектную
часть — план, решатель, перепланирование — модуль не меняет, с одним
исключением, и оно названо: адрес старта из профиля.

Шесть вещей, которые нельзя ломать:

1. **Адрес старта действует со следующего плана, а не с этой минуты.**
   Бригада держит несколько адресов (дом, дача, в гостях) и выбирает,
   откуда начнёт следующий день. Выбор входит только в новые планы,
   через `POST /plan` (`with_profiles`), и только если диспетчер не задал
   этой бригаде свой дом. Пересчёт сегодняшнего плана по событиям идёт
   с настройками самого плана и нового адреса не видит — сегодняшний
   маршрут не трогается.
2. **Способ поездки — дело бригады.** Каршеринг, электросамокат,
   электровелосипед, транспорт, пешком, своя машина: время и цена
   считаются для подсказки, план диспетчера по ним не пересчитывается.
3. **Прокат на карте синтетический** и помечен «демо»: открытых данных
   о машинах каршеринга и самокатах у операторов нет. Точки посеяны от
   координат места (`vehicles_near`) — то же место, те же машины.
4. **Номер клиента бригада не видит.** Звонок идёт через подменный номер
   на время окна визита; настоящего номера в данных нет вовсе, а в журнал
   ложится факт звонка, не номер.
5. **Хранится по-разному.** Профили адресов переживают перезапуск —
   `~/.bee-ltzp/crew-profiles.json`, вне репозитория; переписка, отчёты,
   звонки и смена живут в памяти процесса, как журнал отметок.
6. **Числа проката — оценка, а не тариф.** Цены взяты порядком величины
   с публичных тарифов московских операторов 2026 года и помечены как
   оценка; решатель их не видит.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from datetime import date, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, Field

from .checks import to_clock, to_min
from .dgis import MSK
from .models import Dataset, Plan

PROFILE_PATH = Path.home() / ".bee-ltzp" / "crew-profiles.json"

# Прокат: скорость к нашей модели, пешком до машины, цена. Оценка, не тариф.
WAYS = {
    "carsharing": {"label": "Каршеринг", "base": "car", "k": 1.0, "start_rub": 0, "rub_min": 12, "park_min": 5},
    "scooter": {"label": "Электросамокат", "base": "bike", "k": 0.8, "start_rub": 50, "rub_min": 8, "park_min": 1},
    "ebike": {"label": "Электровелосипед", "base": "bike", "k": 0.85, "start_rub": 40, "rub_min": 6, "park_min": 1},
}
TRANSIT_FARE_RUB = 70
WALK_KMH = 4.5
WINDING = 1.3


# ── Модели ────────────────────────────────────────────────────────────────


class Address(BaseModel):
    id: str
    label: str = Field(description="Дом, дача, в гостях — как назвала бригада")
    address: str
    lat: float
    lon: float


class CrewProfile(BaseModel):
    engineer_id: str
    addresses: list[Address] = Field(default_factory=list)
    start_id: str | None = Field(default=None, description="С какого адреса начинается следующий день")
    since: str | None = Field(default=None, description="Когда бригада выбрала адрес")
    since_plan: str | None = Field(default=None, description="План, который уже шёл в момент выбора: его не трогаем")


class Vehicle(BaseModel):
    id: str
    kind: str
    operator: str
    lat: float
    lon: float
    charge: int = Field(description="Заряд или бак, %")
    walk_min: int


class Way(BaseModel):
    kind: str
    label: str
    minutes: int
    walk_min: int = 0
    price_rub: int = 0
    arrive: str
    late_min: int = Field(default=0, description="Позже плана на столько минут")
    vehicle: Vehicle | None = None
    note: str = ""


class Ways(BaseModel):
    request_id: str
    depart: str
    plan_arrive: str
    origin: list[float]
    target: list[float]
    ways: list[Way]
    vehicles: list[Vehicle]


class Message(BaseModel):
    id: int
    author: str = Field(description="crew | dispatcher")
    kind: str = Field(default="text", description="text | problem | sos | call | report | delay")
    text: str
    time: str
    request_id: str | None = None
    read: bool = False


class MessageIn(BaseModel):
    author: str = "crew"
    kind: str = "text"
    text: str
    time: str | None = None
    request_id: str | None = None


class CallOut(BaseModel):
    request_id: str
    proxy: str
    client_masked: str
    valid_until: str
    note: str


class Report(BaseModel):
    request_id: str
    checklist: list[str] = Field(default_factory=list)
    photos_before: int = 0
    photos_after: int = 0
    equipment: list[str] = Field(default_factory=list)
    signed: bool = False
    comment: str = ""


class ShiftEvent(BaseModel):
    kind: str = Field(description="start | pause | resume | end")
    time: str


class HistoryDay(BaseModel):
    date: str
    visits: int
    on_time: int
    km: float
    earned_rub: int


class Review(BaseModel):
    date: str
    stars: int
    text: str
    type_bk: str


class History(BaseModel):
    rating: float
    reviews_count: int
    days: list[HistoryDay]
    reviews: list[Review]


# ── Профили адресов ───────────────────────────────────────────────────────


def _load_profiles() -> dict[str, CrewProfile]:
    try:
        raw = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}
    return {k: CrewProfile(**v) for k, v in raw.items()}


PROFILES: dict[str, CrewProfile] = {}
_loaded = False


def profiles() -> dict[str, CrewProfile]:
    global _loaded
    if not _loaded:
        PROFILES.update(_load_profiles())
        _loaded = True
    return PROFILES


def _key(dataset_id: str, engineer_id: str) -> str:
    return f"{dataset_id}/{engineer_id}"


def get_profile(dataset: Dataset, engineer_id: str) -> CrewProfile:
    """Профиль бригады; впервые — с домом из набора данных первым адресом."""
    store = profiles()
    key = _key(dataset.id, engineer_id)
    if key not in store:
        eng = next(e for e in dataset.engineers if e.id == engineer_id)
        addresses = []
        if eng.home is not None:
            addresses.append(Address(id="home", label="Дом", address=_home_label(dataset, eng.home.lat, eng.home.lon),
                                     lat=eng.home.lat, lon=eng.home.lon))
        store[key] = CrewProfile(engineer_id=engineer_id, addresses=addresses,
                                 start_id=addresses[0].id if addresses else None)
    # Подпись дома — адрес из набора; профили, заведённые до подписей, берут её здесь.
    eng = next((e for e in dataset.engineers if e.id == engineer_id), None)
    if eng is not None and eng.home is not None and eng.home.address:
        for a in store[key].addresses:
            if a.id == "home" and a.lat == eng.home.lat and a.lon == eng.home.lon:
                a.address = eng.home.address
    return store[key]


def _home_label(dataset: Dataset, lat: float, lon: float) -> str:
    """Подпись синтетического дома: адрес ближайшей заявки набора."""
    near = min(dataset.requests, key=lambda r: (r.lat - lat) ** 2 + (r.lon - lon) ** 2, default=None)
    if near is None:
        return f"{lat:.4f}, {lon:.4f}"
    short = near.address.removeprefix("Московская область, ").removeprefix("Москва, ")
    return f"около: {short}"


def save_profile(dataset: Dataset, profile: CrewProfile, latest_plan: str | None) -> CrewProfile:
    """Сохранить профиль. Смена адреса старта помечается планом, который уже идёт."""
    store = profiles()
    key = _key(dataset.id, profile.engineer_id)
    old = store.get(key)
    ids = {a.id for a in profile.addresses}
    if profile.start_id not in ids:
        profile.start_id = profile.addresses[0].id if profile.addresses else None
    if old is None or old.start_id != profile.start_id:
        profile.since = datetime.now(MSK).isoformat(timespec="minutes")
        profile.since_plan = latest_plan
    else:
        profile.since, profile.since_plan = old.since, old.since_plan
    store[key] = profile
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_PATH.write_text(
        json.dumps({k: v.model_dump() for k, v in store.items()}, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )
    return profile


def with_profiles(dataset_id: str, raw_settings: dict | None) -> dict | None:
    """Адреса старта из профилей бригад — в настройки нового плана.

    Дом, заданный диспетчером, главнее: он выбран для этого расчёта руками.
    """
    chosen = {}
    for key, prof in profiles().items():
        # Профиль, заведённый открытием приложения, — дом из данных; в план
        # входит только выбор, который бригада сохранила сама.
        if not key.startswith(dataset_id + "/") or not prof.start_id or not prof.since:
            continue
        addr = next((a for a in prof.addresses if a.id == prof.start_id), None)
        if addr is not None:
            chosen[prof.engineer_id] = {"lat": addr.lat, "lon": addr.lon, "address": f"{addr.label}: {addr.address}"}
    if not chosen:
        return raw_settings
    out = dict(raw_settings or {})
    crews = {k: dict(v) for k, v in (out.get("crews") or {}).items()} if isinstance(out.get("crews"), dict) else {}
    for eng_id, home in chosen.items():
        own = crews.setdefault(eng_id, {})
        own.setdefault("home", home)
    out["crews"] = crews
    return out


# ── Прокат и способы поездки ──────────────────────────────────────────────


def _km(a: tuple[float, float], b: tuple[float, float]) -> float:
    dlat, dlon = math.radians(b[0] - a[0]), math.radians(b[1] - a[1])
    h = math.sin(dlat / 2) ** 2 + math.cos(math.radians(a[0])) * math.cos(math.radians(b[0])) * math.sin(dlon / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


def _walk_min(a: tuple[float, float], b: tuple[float, float]) -> int:
    return max(1, round(_km(a, b) * WINDING / WALK_KMH * 60))


OPERATORS = {"carsharing": ["Каршеринг A", "Каршеринг B"], "scooter": ["Самокаты A", "Самокаты B"],
             "ebike": ["Велопрокат"]}
DENSITY = {"carsharing": 6, "scooter": 12, "ebike": 5}


def vehicles_near(point: tuple[float, float], radius_km: float = 0.7) -> list[Vehicle]:
    """Синтетический прокат вокруг точки: то же место — те же машины."""
    seed = int(hashlib.sha1(f"{point[0]:.3f},{point[1]:.3f}".encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)
    out: list[Vehicle] = []
    for kind, n in DENSITY.items():
        for i in range(n):
            dist = radius_km * math.sqrt(rng.random())
            ang = rng.random() * 2 * math.pi
            lat = point[0] + dist * math.cos(ang) / 111.0
            lon = point[1] + dist * math.sin(ang) / (111.0 * math.cos(math.radians(point[0])))
            where = (round(lat, 6), round(lon, 6))
            out.append(Vehicle(id=f"{kind}-{i}", kind=kind, operator=rng.choice(OPERATORS[kind]),
                               lat=where[0], lon=where[1], charge=rng.randint(25, 100),
                               walk_min=_walk_min(point, where)))
    return sorted(out, key=lambda v: v.walk_min)


def _points(plan: Plan, dataset: Dataset, engineer_id: str, request_id: str):
    from .transit_trip import endpoints

    origin, target, depart, _, _, arrive = endpoints(plan, dataset, engineer_id, request_id)
    return origin, target, depart, arrive


def ways(plan: Plan, dataset: Dataset, matrices, engineer_id: str, request_id: str) -> Ways:
    """Как доехать до заявки: время и цена по каждому способу, ближайший прокат."""
    from .travel import adjusted, resolve_day_type

    origin, target, depart, plan_arrive = _points(plan, dataset, engineer_id, request_id)
    route = next(r for r in plan.routes if r.engineer_id == engineer_id)
    index = next(i for i, s in enumerate(route.stops) if s.request_id == request_id)
    prev_id = route.stops[index - 1].request_id if index else None
    engineer = next(e for e in dataset.engineers if e.id == engineer_id)
    day_type = resolve_day_type(matrices)
    start = to_min(depart)

    def base(mode: str) -> tuple[int, float]:
        if prev_id is not None and matrices is not None:
            raw_min, raw_km = matrices.travel(mode, prev_id, request_id)
        else:
            km = _km(origin, target) * WINDING
            speed = {"car": 28.0, "bike": 15.0, "foot": 4.5, "transit": 18.0}[mode]
            raw_min, raw_km = round(km / speed * 60) + (8 if mode == "transit" else 0), km
        return adjusted(mode, raw_min, raw_km, start, day_type)

    fleet = vehicles_near(origin)
    out: list[Way] = []

    def add(kind: str, label: str, minutes: int, walk: int = 0, price: int = 0, vehicle=None, note: str = ""):
        total = walk + minutes
        arrive = start + total
        out.append(Way(kind=kind, label=label, minutes=total, walk_min=walk, price_rub=price,
                       arrive=to_clock(arrive), late_min=max(0, arrive - to_min(plan_arrive)),
                       vehicle=vehicle, note=note))

    if any(t.value == "car" for t in engineer.transports):
        add("car", "Своя машина", base("car")[0], note="с парковкой")
    transit_min, _ = base("transit")
    add("transit", "Общественный транспорт", transit_min, price=TRANSIT_FARE_RUB, note="по «Тройке», оценка")
    for kind, conf in WAYS.items():
        near = next((v for v in fleet if v.kind == kind), None)
        if near is None:
            continue
        ride = round(base(conf["base"])[0] * conf["k"]) + conf["park_min"]
        price = conf["start_rub"] + conf["rub_min"] * ride
        add(kind, conf["label"], ride, walk=near.walk_min, price=price, vehicle=near,
            note=f"{near.operator}, {'бак' if kind == 'carsharing' else 'заряд'} {near.charge} %, демо")
    add("foot", "Пешком", base("foot")[0])
    out.sort(key=lambda w: (w.late_min > 0, w.minutes))
    return Ways(request_id=request_id, depart=depart, plan_arrive=plan_arrive, origin=list(origin),
                target=list(target), ways=out, vehicles=fleet)


# ── Связь ────────────────────────────────────────────────────────────────


def proxy_call(plan: Plan, dataset: Dataset, engineer_id: str, request_id: str) -> CallOut:
    """Подменный номер на окно визита: клиент и бригада не видят номеров друг друга."""
    req = next(r for r in dataset.requests if r.id == request_id)
    digest = hashlib.sha1(f"{plan.id}:{engineer_id}:{request_id}".encode()).hexdigest()
    digits = str(int(digest[:10], 16))[-7:].rjust(7, "0")
    proxy = f"+7 495 {digits[:3]}-{digits[3:5]}-{digits[5:]}"
    tail = str(int(digest[10:14], 16))[-2:].rjust(2, "0")
    until = to_clock(min(to_min(req.window_end) + 60, 24 * 60 - 1))
    return CallOut(request_id=request_id, proxy=proxy, client_masked=f"+7 ••• •••-••-{tail}",
                   valid_until=until,
                   note="Номер клиента скрыт: звонок идёт через подменный номер, он действует до конца окна и часа после")


# ── История и отзывы: синтетика от номера бригады ──────────────────────────

REVIEW_TEXTS = [
    (5, "Пришёл вовремя, всё настроил и объяснил"),
    (5, "Вежливый мастер, убрал за собой"),
    (5, "Быстро нашёл обрыв, интернет работает"),
    (4, "Всё сделал, но опоздал на 15 минут"),
    (5, "Помог подключить телевизор, спасибо"),
    (4, "Хорошо, но пришлось ждать звонка"),
    (3, "Работу сделал, общение сухое"),
]


def history(dataset: Dataset, engineer_id: str, today: date | None = None) -> History:
    """Две недели смен и отзывы: для показа, посеяны от номера бригады."""
    rng = random.Random(int(hashlib.sha1(engineer_id.encode()).hexdigest()[:8], 16))
    today = today or date.fromisoformat(dataset.date[:10])
    days = []
    for back in range(14, 0, -1):
        day = today - timedelta(days=back)
        if day.weekday() >= 5 and rng.random() < 0.7:
            continue
        visits = rng.randint(4, 8)
        on_time = visits - (1 if rng.random() < 0.25 else 0)
        days.append(HistoryDay(date=day.isoformat(), visits=visits, on_time=on_time,
                               km=round(rng.uniform(18, 60), 1), earned_rub=7000 + rng.choice([0, 0, 540, 1080, 1620])))
    kinds = ["Подключение", "Локальная заявка", "Глобальная проблема", "Дозаказ"]
    reviews = []
    for i in range(6):
        stars, text = rng.choice(REVIEW_TEXTS)
        reviews.append(Review(date=(today - timedelta(days=i * 2 + 1)).isoformat(), stars=stars, text=text,
                              type_bk=rng.choice(kinds)))
    rating = round(sum(r.stars for r in reviews) / len(reviews) * 0.6 + 4.8 * 0.4, 2)
    return History(rating=rating, reviews_count=40 + rng.randint(0, 80), days=days, reviews=reviews)


def now_clock() -> str:
    return datetime.now(MSK).strftime("%H:%M")
