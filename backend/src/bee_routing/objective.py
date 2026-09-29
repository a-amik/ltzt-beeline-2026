"""Порядок целей плана: вовремя → бригады → итог в рублях.

Эксперты Билайна назвали цели по старшинству: сначала больше заявок, взятых
вовремя, затем меньше бригад, остальное — деньги. Одна сумма в рублях этот
порядок не держит: дешёвая дорога могла перевесить лишнюю бригаду, а лишняя
бригада — невзятую заявку. Порядок задаёт настройка `objective_order`:

- `on_time_crews_rub` — вовремя → бригады → итог в рублях (по умолчанию);
- `on_time_rub_crews` — вовремя → итог → бригады;
- `sum` — прежний счёт одной суммой.

Как порядок доходит до поиска. Решатель, доводка большим соседством
и полировка вставкой считают одну сумму — иначе они не умеют. Старшинство
в неё вносят две добавки (`weights`), и обе выведены из тарифов, а не назначены:

- **бригада** дороже всего, что она может сберечь: к цене дня добавляется
  дорога на всю смену и предел бонуса дня — больше бригада не сэкономит;
- **невзятая заявка** дороже лишней бригады: взять одну заявку — самое
  большее вывести одну бригаду, поэтому добавка — две цены бригады.

В деньги дня добавки не входят: итог на экране — прежние рубли.
Среди готовых планов (портфель стратегий, доводка в фоне) выбирает `key`.
"""

from __future__ import annotations

from . import settings
from .checks import to_min
from .models import Plan

ORDERS = ("on_time_crews_rub", "on_time_rub_crews", "sum")


def order() -> str:
    value = str(settings.option("objective_order") or "on_time_crews_rub")
    return value if value in ORDERS else "on_time_crews_rub"


TRADEOFFS = ("tz", "crews", "money")


def tradeoff() -> str:
    """Что может перевесить ожидание аварии: ничего (tz), бригада (crews) или всё (money)."""
    value = str(settings.option("emergency_tradeoff") or "tz")
    return value if value in TRADEOFFS else "tz"


def late_bound(requests, conf: dict, shift_min: int = 720) -> int:
    """Верхняя граница того, что стоит ожидание аварий дня: каждая ждёт всю смену.

    Ожидание аварии у ключевого клиента стоит до 150 000 ₽ в час (`economy.late_rate`) —
    больше невзятой заявки и лишней бригады. Чтобы порядок целей ТЗ держался,
    добавки старшинства должны быть больше всего, что можно выиграть на ожидании.
    """
    from .economy import late_rate, late_sla

    total = 0
    for req in requests or ():
        if urgent(req):
            deadline, extra = late_sla(req, conf)
            total += late_rate(req, conf) * shift_min + extra * max(0, shift_min - deadline)
    return total


def weights(conf: dict, shift_min: int = 720, requests=None) -> tuple[int, int]:
    """Добавки к цене пропуска заявки и к цене бригады в сумме поиска.

    Ожидание аварий (`late_bound`) по умолчанию младше обеих ступеней — «строго по ТЗ»
    (`options.emergency_tradeoff` = tz): ради аварии крупного клиента решатель
    не бросает заявку и не выводит лишнюю бригаду. `crews` — бригаду вывести можно,
    заявку бросить нельзя; `money` — ожидание считается наравне со всем.
    """
    mode = order()
    if mode == "sum":
        return 0, 0
    saving = int(shift_min * float(conf["travel_rub_per_min"]) + float(conf.get("bonus_cap_rub_per_day", 0)))
    late = late_bound(requests, conf, shift_min)
    trade = tradeoff()
    if trade == "tz":
        saving += late
    crew = saving if mode == "on_time_crews_rub" else 0
    skip = 2 * (int(conf["engineer_day_rub"]) + saving) + (late if trade == "crews" else 0)
    return skip, crew


def skip_extra(request, conf: dict, base: int) -> int:
    """Добавка старшинства к цене пропуска одной заявки.

    Ступени приоритета (авария → подключение → ремонт и дозаказ, `priority_bonus_rub`)
    старше счёта заявок штуками: иначе добавка, одинаковая у всех заявок, разрешила бы
    обменять одно подключение на два ремонта. Поэтому добавка растёт вместе со ступенью —
    во столько раз, во сколько надбавка ступени больше самой дешёвой заявки.
    """
    if not base:
        return 0
    from .economy import priority_tier, tier_bonus

    bonus = tier_bonus(priority_tier(request), conf)
    cheapest = max(1, min(int(v) for v in conf["request_value_rub"].values()))
    return base * (1 + bonus // cheapest)


def urgent(request) -> bool:
    """Заявка, чьё ожидание стоит денег в цели: авария или «срочно», пока включено «Авария — как можно раньше»."""
    return bool(settings.option("emergency_first")) and (
        request.skill.value == "emergency" or settings.is_urgent(request)
    )


def extra_rub(states, by_id: dict, zones: dict[str, str | None], conf: dict, matrices=None) -> int:
    """Слагаемые цели поиска, которых нет в деньгах дня.

    Решатель несёт их в модели: ожидание аварии — мягкой верхней границей
    начала на старте окна, переезд между зонами и длинный переезд — ценой
    дуги, дорога домой — ценой дуги в конец маршрута (`arcs.py`). Доводка
    и выбор среди готовых планов обязаны видеть то же: без этого доводка
    бесплатно сдвигала аварию на вечер ради чужих окон. Дорога домой
    считается, только когда переданы матрицы.
    """
    from .economy import late_rate, late_sla
    from .zones import crossings

    cross_rate = int(conf.get("zone_cross_rub", 0))
    leg_min, leg_rate = long_leg(conf)
    home_share = float(conf.get("return_home_share", 0) or 0)
    km_rub = float(conf.get("km_metric_rub", 0) or 0)
    total = 0
    # Ждать аварию начинают не раньше начала смены — как в решателе (`solver`, мягкая граница окна).
    day_start = min((to_min(st.engineer.shift_start) for st in states.values()), default=0)
    for st in states.values():
        if not st.stops:
            continue
        for stop in st.stops:
            req = by_id.get(stop.request_id)
            if req is not None and stop.status != "no_show" and urgent(req):
                since = max(to_min(req.window_start), day_start)
                total += late_rate(req, conf) * max(0, to_min(stop.start) - since)
                deadline, extra = late_sla(req, conf)
                if extra:
                    total += extra * max(0, to_min(stop.start) - since - deadline)
            if leg_rate:
                total += leg_rate * max(0, stop.travel_min - leg_min)
            if km_rub:
                total += int(stop.travel_km * km_rub)
        if cross_rate:
            points = [st.start_position] + [s.request_id for s in st.stops]
            total += cross_rate * crossings(points, zones)
        if home_share > 0 and matrices is not None:
            total += round(home_share * home_cost(st.engineer, st.stops[-1].request_id, st.start_position,
                                                  matrices, conf))
    return total


def long_leg(conf: dict) -> tuple[int, int]:
    """Порог длинного переезда в минутах и надбавка за минуту сверх него, ₽ (усталость от дороги)."""
    surcharge = float(conf.get("long_leg_surcharge", 0) or 0)
    return int(conf.get("long_leg_min", 0) or 0), round(float(conf["travel_rub_per_min"]) * surcharge)


def home_cost(engineer, last_point: str, home: str, matrices, conf: dict) -> int:
    """Полная цена дороги от последнего визита до точки, откуда бригада начала день."""
    from .travel import leg

    road = leg(engineer, last_point, home, matrices)
    return round(road.minutes * float(conf["travel_rub_per_min"])
                 + (road.km * float(conf["car_rub_per_km"]) if road.mode.value == "car" else 0)
                 + (int(conf.get("transit_rub_per_leg", 0)) if road.mode.value == "transit" and road.minutes else 0))


def shift_minutes(engineers) -> int:
    return max((to_min(e.shift_end) - to_min(e.shift_start) for e in engineers), default=720)


def on_time(plan: Plan) -> int:
    return sum(1 for r in plan.routes for s in r.stops if s.status != "no_show" and s.late_min == 0)


def crews(plan: Plan) -> int:
    return sum(1 for r in plan.routes if r.stops)


def key(plan: Plan) -> tuple:
    """Ключ сравнения планов: меньше — лучше. Потерянное по приоритету — всегда первым."""
    lost = int(plan.timing.get("priority_lost_rub", 0))
    # Итог — за вычетом того, что цель поиска считает сверх денег: ожидание аварии, переезды между зонами.
    net = (plan.economy.net_rub if plan.economy else 0) - int(plan.timing.get("objective_extra_rub", 0))
    mode = order()
    if mode == "on_time_crews_rub":
        return (lost, -on_time(plan), crews(plan), -net, plan.metrics.travel_min)
    if mode == "on_time_rub_crews":
        return (lost, -on_time(plan), -net, crews(plan), plan.metrics.travel_min)
    return (lost, len(plan.unassigned), -net, plan.metrics.travel_min)


def summary(plan: Plan) -> dict:
    """Три числа порядка целей — для экрана и отчёта."""
    return {"order": order(), "on_time": on_time(plan), "crews": crews(plan),
            "net_rub": plan.economy.net_rub if plan.economy else 0}
