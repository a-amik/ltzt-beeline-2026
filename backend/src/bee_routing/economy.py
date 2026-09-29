"""Экономика плана в рублях: ценность заявок, оклад, бонус за норму, дорога, дефицит.

Зачем. Цели решателя названы экспертами по старшинству — заявки, бригады,
дорога, — но у диспетчера и у жюри они читаются только деньгами: «заявку
не назначили, потому что девятая бригада стоит 7 000 ₽, а заявка 2 500».
Поэтому тарифная таблица (`assumptions.json`, `economy`) одна на всё:
из неё решатель берёт веса цели, а витрина — экономику дня.

Модель мотивации — как у агрегаторов такси и доставки, только для штатных
сотрудников: оклад гарантирован (день бригады), а всё сверх нормы дня
оплачивается по повышенной ставке. Норма считается в нормо-минутах —
норматив заказчика вместе с дорогой (20 минут), — а не в штуках: иначе
выгодно брать только короткие дозаказы. Инженер может отказаться от
дополнительной нагрузки флагом профиля (`extra_load`), и тогда план
не ставит ему больше нормы.

Три вещи, которые нельзя ломать:

1. **Числа живут в допущениях, здесь их нет.** Заказчик тарифов не давал;
   всё в `economy` — оценка, и правится без кода.
2. **Бонус считается от нормо-минут сверх нормы дня**, не от числа заявок,
   и только у бригады с `extra_load`. Потолок бонуса за день — не выше
   стоимости вывода ещё одной бригады: иначе дешевле нанять.
3. **Цена ожидания у двери — рычаг, и по умолчанию он стоит на нуле.**
   Минуте простоя можно назначить цену (`wait_rub_per_min`): она одна
   в цели решателя (`SetSlackCostCoefficient`) и в экономике дня
   (`wait_rub`). Замер 19.09.2026 на трёх регионах показал, что даром это
   не даётся: простой решатель меняет на езду. При 4 ₽ ожидание падает
   на 25—60 %, на Востоке и Югоцентре освобождается бригада (10 → 9,
   8 → 7, по 7 000 ₽ в день), но дорога на визит растёт на 2—3 минуты
   и на Юго-востоке выходит выше контрольной; при 12 ₽ решатель бросает
   заявки. Загрузку смены там, где заняты все бригады и выполнены все
   заявки, цена ожидания поднимает только лишней ездой. Поэтому умолчание —
   ноль, прежние сравнения с контролем остаются в силе, а рычаг стоит
   в настройках: им показывают, сколько бригад стоит простой.
4. **Дефицит — отношение спроса к предложению в окне**, обрезанное
   в [1; 2]: он множит бонус в предложениях и показывает продажам, какие
   окна не стоит обещать клиентам.
"""

from __future__ import annotations

from collections import defaultdict

from . import settings
from .checks import to_min
from .models import Dataset, Deficit, Economy, Engineer, Plan, Request, Route

DEFAULT_ECONOMY = {
    "request_value_rub": {"connect": 7000, "emergency": 8000, "local": 3500, "upsell": 2000},
    "priority_bonus_rub": {"emergency": 200000, "connect": 20000},
    "manual_bonus_rub": {"urgent": 2000000, "high": 20000},
    "urgent_multiplier": 1.5,
    "emergency_segments": {
        "KA": {"label": "ключевой клиент", "bill_rub": 500000, "churn_pct": 12, "escalation_rub": 50000, "sla_h": 2.0},
        "A": {"label": "крупный", "bill_rub": 250000, "churn_pct": 10, "escalation_rub": 20000, "sla_h": 2.0},
        "B": {"label": "средний", "bill_rub": 35000, "churn_pct": 8, "escalation_rub": 10000, "sla_h": 4.0},
        "C": {"label": "малый", "bill_rub": 7500, "churn_pct": 5, "escalation_rub": 3000, "sla_h": 0.0},
        "D": {"label": "микро", "bill_rub": 2500, "churn_pct": 3, "escalation_rub": 1000, "sla_h": 0.0},
    },
    "contract_months": 48,
    "margin_pct": 50,
    "emergency_sla_multiplier": 2.0,
    "engineer_day_rub": 9000,
    "travel_rub_per_min": 18,
    "wait_rub_per_min": 0,
    "car_rub_per_km": 14,
    "transit_rub_per_leg": 75,
    "return_home_share": 0.5,
    "long_leg_min": 40,
    "long_leg_surcharge": 0.5,
    "km_metric_rub": 0,
    "norm_day_min": 480,
    "norm_rate_rub_per_min": 18,
    "bonus_multiplier": 1.5,
    "emergency_late_pct_per_hour": 10,
    "zone_cross_rub": 0,
    "sector_cross_rub": 0,
    "balance_rub_per_min": 5,
    "bonus_cap_rub_per_day": 9000,
    "offer_accept_minutes": 5,
    "offer_candidates": 3,
    "road_norm_min": 20,
}


def tariffs() -> dict:
    """Тарифная таблица текущего запроса: допущения, переопределения, запасные значения."""
    conf = settings.section("economy")
    out = dict(DEFAULT_ECONOMY)
    out.update({k: v for k, v in conf.items() if not k.startswith("_")})
    values = dict(DEFAULT_ECONOMY["request_value_rub"])
    values.update({k: v for k, v in out.get("request_value_rub", {}).items() if not k.startswith("_")})
    out["request_value_rub"] = values
    bonus = dict(DEFAULT_ECONOMY["priority_bonus_rub"])
    bonus.update({k: v for k, v in out.get("priority_bonus_rub", {}).items() if not k.startswith("_")})
    out["priority_bonus_rub"] = bonus
    manual = dict(DEFAULT_ECONOMY["manual_bonus_rub"])
    manual.update({k: v for k, v in out.get("manual_bonus_rub", {}).items() if not k.startswith("_")})
    out["manual_bonus_rub"] = manual
    segments = {k: dict(v) for k, v in DEFAULT_ECONOMY["emergency_segments"].items()}
    for key, part in (out.get("emergency_segments") or {}).items():
        if key in segments and isinstance(part, dict):
            segments[key].update({k: v for k, v in part.items() if not k.startswith("_")})
    out["emergency_segments"] = segments
    return out


# Тип BK, который стоит отдельно от своего навыка. Дозаказ делает бригада
# с навыком подключения, но по приоритету он на ступени ремонта: письменный
# ответ Билайна, п. 15 — авария → подключение → ремонт / дозаказ.
VALUE_BY_TYPE_BK = {"Дозаказ": "upsell"}


def is_emergency(request: Request) -> bool:
    return VALUE_BY_TYPE_BK.get(request.type_bk, request.skill.value) == "emergency"


def segment_of(request: Request) -> str | None:
    """Сегмент клиента аварии: руками диспетчера, из набора или синтетика; у прочих заявок нет."""
    if not is_emergency(request):
        return None
    return settings.manual_segment(request.id) or request.segment


def weight_text(request: Request, conf: dict | None = None) -> str | None:
    """Сегмент и цена аварии словами — для карточки заявки и объяснения; у прочих заявок нет."""
    conf = conf or tariffs()
    segment = segment_of(request)
    if segment is None:
        return None
    from .segments import text

    return text(segment, request_value(request, conf), conf)


def request_value(request: Request, conf: dict | None = None) -> int:
    """Сколько компания теряет, если заявку сегодня не выполнили: по навыку, срочная дороже.

    Цена пропуска и задаёт приоритет при нехватке бригад: подключение 7 000,
    ремонт 3 500, дозаказ 2 000 ₽. Авария — по сегменту клиента (`segments.py`):
    счёт × срок договора × маржа × риск ухода + эскалация — от 2 800 ₽ у микро-
    клиента до 1 490 000 у ключевого.
    """
    conf = conf or tariffs()
    segment = segment_of(request)
    if segment is not None:
        from .segments import value_rub

        value = value_rub(segment, conf)
    else:
        key = VALUE_BY_TYPE_BK.get(request.type_bk, request.skill.value)
        value = conf["request_value_rub"].get(key, conf["request_value_rub"].get(request.skill.value, 0))
    manual = settings.manual_priority(request.id)
    if settings.is_urgent(request):
        value = value * float(conf["urgent_multiplier"])
    elif manual == "low":
        value = value * float(conf.get("low_priority_multiplier", 0.5))
    return round(value)


def late_rate(request: Request, conf: dict | None = None) -> int:
    """Цена минуты, на которую авария или «срочно» начаты позже начала окна: доля ценности за час.

    Бизнес без связи теряет рабочий день — около 10 часов, поэтому час ожидания стоит
    десятую часть цены аварии (`emergency_late_pct_per_hour`): у микро-клиента за 2 800 ₽ —
    5 ₽ в минуту, у крупного за 620 000 — 1 033 ₽. После срока SLA минута дороже
    (`late_sla`). Только в цели поиска.
    """
    conf = conf or tariffs()
    pct = float(conf.get("emergency_late_pct_per_hour", 0) or 0)
    return round(request_value(request, conf) * pct / 100 / 60) if pct > 0 else 0


def late_sla(request: Request, conf: dict | None = None) -> tuple[int, int]:
    """Срок восстановления по SLA в минутах и надбавка к цене минуты после него; (0, 0) — срока нет.

    KA и A — 2 часа, B — 4 часа, C и D — до конца дня (решение команды 29.09.2026).
    После срока минута стоит в `emergency_sla_multiplier` раз дороже.
    """
    conf = conf or tariffs()
    segment = segment_of(request)
    if segment is None:
        return 0, 0
    from .segments import sla_min

    deadline = sla_min(segment, conf)
    extra = round(late_rate(request, conf) * (float(conf.get("emergency_sla_multiplier", 1)) - 1))
    return (deadline, extra) if deadline > 0 and extra > 0 else (0, 0)


# Сколько заявок нижней ступени одна заявка верхней вытесняет по времени: авария
# (100 нормо-минут) — до двух подключений (90), подключение — до двух ремонтов (50)
# и до трёх дозаказов (40). Нормативы Билайна, таблица «Базовый норматив».
DISPLACES = (("emergency", "connect", 2), ("connect", "local", 2), ("connect", "upsell", 3))


def balance_issues(conf: dict | None = None) -> list[str]:
    """Где тарифы сами по себе не держат порядок ступеней — словами; пусто, если держат.

    Порядок авария → подключение → ремонт и дозаказ держится деньгами, когда заявка
    старшей ступени дороже всего, что она вытесняет по времени. Подключение и ремонт
    обязаны держать его сами. Мелкая авария (сегменты C и D) дешевле двух подключений
    сознательно: порядок организаторов для неё держит надбавка ступени
    (`options.priority_order`), а в режиме «по деньгам» она вправе уступить.
    """
    conf = conf or tariffs()
    values = {k: int(v) for k, v in conf["request_value_rub"].items()}
    from .segments import SEGMENTS, value_rub

    names = {"connect": "подключение", "local": "ремонт", "upsell": "дозаказ"}
    out = []
    for high, low, times in DISPLACES:
        if high == "emergency":
            for segment in SEGMENTS:
                price = value_rub(segment, conf)
                if price < times * values[low]:
                    out.append(f"Авария у клиента {segment} ({price:,} ₽) дешевле, чем {times} × подключение "
                               f"({times * values[low]:,} ₽): выше подключения её держит только порядок ступеней"
                               .replace(",", "\u00a0"))
        elif values[high] < times * values[low]:
            out.append(f"{names[high].capitalize()} ({values[high]:,} ₽) дешевле, чем {times} × {names[low]} "
                       f"({times * values[low]:,} ₽): порядок ступеней держат только надбавки".replace(",", "\u00a0"))
    return out


def morning_conf(conf: dict | None = None) -> dict:
    """Тарифы утреннего плана: с резервом ёмкости под заявки дня (`options.reserve_pct`)."""
    out = dict(conf or tariffs())
    out["_reserve_pct"] = float(settings.option("reserve_pct") or 0)
    return out


def norm_limit(engineer: Engineer, conf: dict) -> int:
    """Предел нормо-минут бригады: норма дня и согласованная добавка; утром — за вычетом резерва.

    Резерв держит только утренний план (`morning_conf`): днём он и расходуется —
    на аварии и заявки день в день. Билайн, 19.09.2026: часть ёмкости
    сознательно остаётся свободной под оперативные работы.
    """
    limit = int(conf["norm_day_min"]) + (int(engineer.extra_limit_min) if engineer.extra_load else 0)
    reserve = float(conf.get("_reserve_pct", 0) or 0)
    return round(limit * (1 - reserve / 100)) if reserve > 0 else limit


def priority_tier(request: Request) -> str:
    """Ступень приоритета: авария, подключение или остальное (ремонт, дозаказ).

    Ручной приоритет диспетчера сдвигает ступень: «срочно» — на ступень аварии,
    «выше» — на одну вверх, «ниже» — на нижнюю.
    """
    key = VALUE_BY_TYPE_BK.get(request.type_bk, request.skill.value)
    tier = key if key in ("emergency", "connect") else "rest"
    manual = settings.manual_priority(request.id)
    if manual == "urgent":
        return "emergency"
    if manual == "high":
        return {"rest": "connect", "connect": "emergency"}.get(tier, tier)
    if manual == "low":
        return "rest"
    return tier


def priority_order() -> str:
    """Порядок ступеней: как у организаторов (надбавка), строго (лесенка) или по деньгам (без надбавки).

    До 29.09.2026 «строго» включал флажок «Жёсткий порядок ступеней» (`priority_hard`).
    """
    mode = str(settings.option("priority_order") or "organizers")
    return mode if mode in ("organizers", "strict", "money") else "organizers"


HARD_TIER_STEP = 1000
"""Во столько раз ступень дороже предыдущей в жёстком режиме: больше, чем заявок в дне."""


def tier_bonus(tier: str, conf: dict) -> int:
    """Надбавка ступени: из тарифов или, в жёстком режиме, посчитанная лесенкой.

    Обычный режим — числа из тарифов (авария 200 000, подключение 20 000 ₽):
    порядок строгий на наших данных, но остаётся деньгами, и очень дорогая
    заявка нижней ступени теоретически может его перевесить.

    Строгий режим (`priority_order` = strict) — ступень старше любых денег: авария
    не оценивается вовсе. Надбавка считается от самой дешёвой заявки
    и растёт в `HARD_TIER_STEP` раз на ступень, поэтому одна авария дороже
    тысячи подключений, а одно подключение — тысячи ремонтов. Числа
    из тарифов в этом режиме не участвуют.

    Режим «по деньгам» (`money`) — надбавки нет: мелкая авария вправе уступить
    подключению, если оно дороже.
    """
    mode = priority_order()
    if mode == "money":
        return 0
    if mode == "strict":
        cheapest = max(1, min(int(v) for v in conf["request_value_rub"].values()))
        rank = {"rest": 0, "connect": 1, "emergency": 2}.get(tier, 0)
        return cheapest * HARD_TIER_STEP ** rank if rank else 0
    return int(conf.get("priority_bonus_rub", {}).get(tier, 0))


def skip_penalty(request: Request, conf: dict | None = None) -> int:
    """Цена пропуска для решателя: ценность заявки и, если задана, надбавка приоритета.

    Приоритет при нехватке бригад задаётся **ценностью заявки**, и это
    настройка, а не код: подключение 7 000, ремонт 3 500, дозаказ 2 000 ₽,
    авария — по сегменту клиента, от 2 800 ₽ у микро-клиента до 1 490 000
    у ключевого (вкладка «Ценность и приоритет»). Внутри ступени аварии решает
    сегмент: авария у крупного клиента идёт раньше, чем у мелкого. Порядок
    ступеней из письменного ответа Билайна (п. 15) держит надбавка ниже —
    мелкая авария дешевле подключения (`balance_issues`).

    Нужен порядок жёсткий, безотносительно размера аварии, — его тоже задают
    настройкой: «Надбавка приоритета» у аварии и у подключения. Она входит
    только в цель решателя, в деньги дня — нет. Число больше всего, что
    бригада успеет сделать вместо одной заявки (авария 200 000, подключение
    20 000), делает порядок строгим: 19.09.2026 при трёх бригадах на Юго-востоке
    с такими надбавками брались 12 аварий из 12, без них — 7 из 12. С 22.09.2026
    надбавки включены по умолчанию — решение команды после третьего повторения
    порядка организатором.

    Нужен порядок, который не спорит с деньгами вовсе, — настройка «Жёсткий
    порядок ступеней»: авария не оценивается, ступени считаются лесенкой
    (`tier_bonus`).
    """
    conf = conf or tariffs()
    manual = settings.manual_priority(request.id)
    # Ручной приоритет действует и тогда, когда надбавка ступеней выключена: диспетчер
    # поднял заявку — решатель обязан это видеть (`manual_bonus_rub` в тарифах).
    extra = int(conf.get("manual_bonus_rub", {}).get(manual, 0)) if manual in ("urgent", "high") else 0
    return request_value(request, conf) + tier_bonus(priority_tier(request), conf) + extra


def norm_minutes(request: Request, conf: dict | None = None) -> int:
    """Нормо-минуты заявки: работа на точке плюс норматив дороги."""
    conf = conf or tariffs()
    return request.duration_min + int(conf["road_norm_min"])


def travel_cost(route: Route, conf: dict | None = None) -> int:
    """Дорога маршрута в рублях: минуты инженера, километры автомобиля, поездки на общественном транспорте."""
    conf = conf or tariffs()
    car_km = sum(stop.travel_km for stop in route.stops if stop.mode and stop.mode.value == "car")
    rides = sum(1 for stop in route.stops if stop.mode and stop.mode.value == "transit" and stop.travel_min > 0)
    return round(route.travel_min * conf["travel_rub_per_min"] + car_km * conf["car_rub_per_km"]
                 + rides * int(conf.get("transit_rub_per_leg", 0)))


def wait_cost(route: Route, conf: dict | None = None) -> int:
    """Ожидание у клиентов в рублях: минуты между приездом и началом работы."""
    conf = conf or tariffs()
    minutes = sum(stop.wait_min for stop in route.stops if stop.status != "no_show")
    return round(minutes * float(conf.get("wait_rub_per_min", 0)))


def bonus_for(over_norm_min: int, engineer: Engineer, conf: dict | None = None) -> int:
    """Бонус за нормо-минуты сверх нормы дня, если бригада к нагрузке готова."""
    conf = conf or tariffs()
    if over_norm_min <= 0 or not engineer.extra_load:
        return 0
    bonus = over_norm_min * conf["norm_rate_rub_per_min"] * float(conf["bonus_multiplier"])
    return round(min(bonus, conf["bonus_cap_rub_per_day"]))


def price_routes(plan: Plan, dataset: Dataset, conf: dict | None = None,
                 requests: list[Request] | None = None) -> None:
    """Проставить маршрутам нормо-минуты, бонус и заработок — на месте."""
    conf = conf or tariffs()
    by_id = {req.id: req for req in dataset.requests}
    for event in dataset.events:
        if event.request is not None:
            by_id.setdefault(event.request.id, event.request)
    for req in requests or []:
        by_id[req.id] = req
    for event in plan.history:
        if event.request is not None:
            by_id.setdefault(event.request.id, event.request)
    engineers = {eng.id: eng for eng in settings.effective_engineers(dataset.engineers)}
    for route in plan.routes:
        norm = sum(norm_minutes(by_id[s.request_id], conf) for s in route.stops
                   if s.request_id in by_id and s.status != "no_show")
        for stop in route.stops:
            if stop.request_id in by_id and stop.status != "no_show":
                stop.value_rub = request_value(by_id[stop.request_id], conf)
        route.norm_min = norm
        route.over_norm_min = max(0, norm - int(conf["norm_day_min"]))
        engineer = engineers.get(route.engineer_id)
        route.bonus_rub = bonus_for(route.over_norm_min, engineer, conf) if engineer else 0
        route.earnings_rub = (int(conf["engineer_day_rub"]) if route.stops else 0) + route.bonus_rub


def deficit_by_window(dataset: Dataset, requests: list[Request] | None = None,
                      conf: dict | None = None) -> list[Deficit]:
    """Спрос нормо-минут против предложения бригад по окнам клиентов."""
    conf = conf or tariffs()
    requests = requests if requests is not None else dataset.requests
    demand: dict[tuple[str, str], int] = defaultdict(int)
    for req in requests:
        demand[(req.window_start, req.window_end)] += norm_minutes(req, conf)
    out = []
    for (ws, we), minutes in sorted(demand.items()):
        capacity = len(dataset.engineers) * max(to_min(we) - to_min(ws), 1)
        coef = min(2.0, max(1.0, minutes / capacity)) if capacity else 1.0
        out.append(Deficit(window=f"{ws}–{we}", demand_min=minutes, capacity_min=capacity, coef=round(coef, 2)))
    return out


def deficit_coef(request: Request, deficits: list[Deficit]) -> float:
    """Коэффициент дефицита окна заявки; надбавка выключена — единица."""
    if not settings.option("deficit"):
        return 1.0
    key = f"{request.window_start}–{request.window_end}"
    return next((d.coef for d in deficits if d.window == key), 1.0)


def sector_entries(engineer, request_ids: list[str], by_id: dict) -> int:
    """Въезды бригады в чужой участок: участок старта, затем участки визитов по порядку.

    Считается каждая смена участка, и возврат в свой тоже: маршрут «свой → чужой →
    свой → чужой» — та самая нерациональная логистика, о которой говорил эксперт.
    У набора одного участка участков нет, и въездов ноль.
    """
    from .zones import sector_crossings

    if not getattr(engineer, "sector", None):
        return 0
    seq = [engineer.sector] + [getattr(by_id.get(rid), "sector", None) for rid in request_ids]
    return sector_crossings(seq)


def summarize(plan: Plan, dataset: Dataset, requests: list[Request] | None = None,
              conf: dict | None = None) -> Economy:
    """Экономика плана: что заработали, что упустили, что заплатили."""
    conf = conf or tariffs()
    requests = requests if requests is not None else dataset.requests
    by_id = {req.id: req for req in dataset.requests}
    for event in dataset.events:
        if event.request is not None:
            by_id.setdefault(event.request.id, event.request)
    for event in plan.history:
        if event.request is not None:
            by_id[event.request.id] = event.request
    for req in requests:
        by_id[req.id] = req
    price_routes(plan, dataset, conf, requests)
    assigned = [s.request_id for r in plan.routes for s in r.stops if s.status != "no_show"]
    value_done = sum(request_value(by_id[i], conf) for i in assigned if i in by_id)
    value_lost = sum(request_value(by_id[u.request_id], conf) for u in plan.unassigned if u.request_id in by_id)
    payroll = sum(int(conf["engineer_day_rub"]) for r in plan.routes if r.stops)
    bonus = sum(r.bonus_rub for r in plan.routes)
    travel = sum(travel_cost(r, conf) for r in plan.routes)
    wait = sum(wait_cost(r, conf) for r in plan.routes)
    crews = {e.id: e for e in dataset.engineers}
    entries = sum(
        sector_entries(crews.get(r.engineer_id), [s.request_id for s in r.stops], by_id) for r in plan.routes if r.stops
    )
    sector = entries * int(conf.get("sector_cross_rub", 0))
    total = payroll + bonus + travel + wait + sector
    return Economy(
        value_done_rub=value_done, value_lost_rub=value_lost, payroll_rub=payroll,
        bonus_rub=bonus, travel_rub=travel, wait_rub=wait, sector_rub=sector, sector_entries=entries,
        total_cost_rub=total, net_rub=value_done - total,
        deficit=deficit_by_window(dataset, requests, conf),
    )
