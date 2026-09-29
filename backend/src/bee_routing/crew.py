"""День бригады глазами её приложения: маршрут, предложения, заработок, отметки.

Приложение бригады — упрощённый аналог приложения курьера: маршрут по порядку,
предложение новой заявки с бонусом, «принять» и «отказаться» с причиной,
статусы «выехал, прибыл, начал, закончил, клиента нет». Настоящих устройств
у прототипа нет: отметки приходят кнопками и идут в тот же журнал, из которого
считаются оплата и контроль (`fraud.py`).

Три вещи, которые нельзя ломать:

1. **Оклад гарантирован планом, бонус — подтверждённой работой.** Бонус
   в приложении показан дважды: по плану («заработаете, если всё сделаете»)
   и по факту — только за визиты с отметкой «закончил». Иначе бонус
   начислялся бы за нарисованный маршрут.
2. **Отказ не бывает молчаливым.** У ответа на предложение есть причина
   словами; предложение без ответа в срок уходит следующему кандидату,
   как у агрегаторов (приоритет Яндекс Про: −3 за пропуск, −7 за отмену
   принятого).
3. **Заявку из маршрута бригада сама не выкидывает.** Убрать визит может
   только событие диспетчерской (отмена, перенос) или отметка «клиента нет»,
   которая уводит заявку на завтра и остаётся в журнале с геопозицией.
"""

from __future__ import annotations

from . import settings
from .checks import to_min
from .economy import bonus_for, norm_minutes, tariffs
from .insertion import assign, requests_of
from .matrices import Matrices
from .models import (
    CrewDay,
    CrewOffer,
    Dataset,
    Deferred,
    Earnings,
    Engineer,
    Mark,
    OfferResponse,
    Plan,
    Request,
)

DONE_KINDS = ("done", "no_show")


def _engineer(dataset: Dataset, engineer_id: str) -> Engineer:
    for eng in settings.effective_engineers(dataset.engineers):
        if eng.id == engineer_id:
            return eng
    raise KeyError(engineer_id)


def earnings(plan: Plan, dataset: Dataset, engineer_id: str, marks: list[Mark]) -> Earnings:
    """Оклад, бонус по плану и по подтверждённому, норма дня и прогресс по ней."""
    conf = tariffs()
    by_id = requests_of(dataset, plan)
    engineer = _engineer(dataset, engineer_id)
    route = next((r for r in plan.routes if r.engineer_id == engineer_id), None)
    stops = [s for s in (route.stops if route else []) if s.status != "no_show"]
    done = {m.request_id for m in marks if m.engineer_id == engineer_id and m.kind == "done"}
    norm_planned = sum(norm_minutes(by_id[s.request_id], conf) for s in stops if s.request_id in by_id)
    norm_confirmed = sum(
        norm_minutes(by_id[s.request_id], conf) for s in stops if s.request_id in by_id and s.request_id in done
    )
    norm_day = int(conf["norm_day_min"])
    return Earnings(
        day_rub=int(conf["engineer_day_rub"]) if stops else 0,
        bonus_planned_rub=bonus_for(max(0, norm_planned - norm_day), engineer, conf),
        bonus_confirmed_rub=bonus_for(max(0, norm_confirmed - norm_day), engineer, conf),
        norm_day_min=norm_day,
        norm_planned_min=norm_planned,
        norm_confirmed_min=norm_confirmed,
        over_norm_min=max(0, norm_planned - norm_day),
    )


def crew_offers(plan: Plan, dataset: Dataset, engineer_id: str) -> list[CrewOffer]:
    """Предложения, адресованные этой бригаде: адрес, окно, когда приедет, бонус."""
    by_id = requests_of(dataset, plan)
    timeout = int(settings.option("offer_timeout_min") or 5)
    out: list[CrewOffer] = []
    for offer in plan.offers:
        req = by_id.get(offer.request_id)
        if req is None:
            continue
        for candidate in offer.candidates:
            if candidate.engineer_id != engineer_id:
                continue
            out.append(CrewOffer(
                request_id=req.id, address=req.address,
                window=f"{req.window_start}–{req.window_end}", duration_min=req.duration_min,
                arrive=candidate.arrive, delta_travel_min=candidate.delta_travel_min,
                bonus_rub=candidate.bonus_rub, text=candidate.text, expires_in_min=timeout,
            ))
    return out


def crew_day(plan: Plan, dataset: Dataset, engineer_id: str, marks: list[Mark]) -> CrewDay:
    """Собрать экран дня бригады."""
    by_id = requests_of(dataset, plan)
    engineer = _engineer(dataset, engineer_id)
    route = next((r for r in plan.routes if r.engineer_id == engineer_id), None)
    if route is None:
        from .models import Route

        route = Route(engineer_id=engineer_id, distance_km=0, travel_min=0, work_min=0)
    mine = [m for m in marks if m.engineer_id == engineer_id]
    finished = {m.request_id for m in mine if m.kind in DONE_KINDS}
    next_id = next(
        (s.request_id for s in route.stops if s.status != "no_show" and s.request_id not in finished), None
    )
    requests: list[Request] = [by_id[s.request_id] for s in route.stops if s.request_id in by_id]
    for offer in crew_offers(plan, dataset, engineer_id):
        if offer.request_id in by_id and by_id[offer.request_id] not in requests:
            requests.append(by_id[offer.request_id])
    from . import stock
    from .equipment import kit_for

    day_stock = stock.of(plan, dataset, by_id)
    rest = stock.left(engineer_id, route.stops, by_id, day_stock) if stock.enabled() else None
    return CrewDay(
        stock=day_stock.get(engineer_id, {}) if stock.enabled() else {},
        stock_left={k: v for k, v in (rest or {}).items()},
        plan_id=plan.id, engineer=engineer, route=route, requests=requests, marks=mine,
        offers=crew_offers(plan, dataset, engineer_id),
        earnings=earnings(plan, dataset, engineer_id, marks), next_request_id=next_id,
        kit=kit_for(plan, dataset, engineer_id, by_id),
    )


def respond(
    plan: Plan, dataset: Dataset, matrices: Matrices, response: OfferResponse, *, plan_id: str,
) -> tuple[Plan, str]:
    """Ответ бригады: принято — заявка встаёт в маршрут; отказ — предложение идёт дальше.

    Возвращает новый план и итог словами. Отказались все — заявка явно уходит
    на следующий день, а не остаётся висеть в неназначенных.
    """
    offer = next((o for o in plan.offers if o.request_id == response.request_id), None)
    if offer is None:
        return plan, f"Предложения по заявке {response.request_id} уже нет"
    candidate = next((c for c in offer.candidates if c.engineer_id == response.engineer_id), None)
    if candidate is None:
        return plan, f"Бригаде {response.engineer_id} эту заявку не предлагали"
    if response.accepted:
        built, why = assign(
            plan, dataset, matrices, response.request_id, response.engineer_id, candidate.insert_after,
            plan_id=plan_id,
        )
        if built is None:
            return plan, f"Заявка уже не встаёт: {why}"
        built.offers = [o for o in built.offers if o.request_id != response.request_id]
        return built, f"Бригада приняла заявку {response.request_id}, приезд {candidate.arrive}"
    rest = [c for c in offer.candidates if c.engineer_id != response.engineer_id]
    new_plan = plan.model_copy(deep=True)
    new_plan.id = plan_id
    new_plan.history = list(plan.history)
    if rest:
        for item in new_plan.offers:
            if item.request_id == response.request_id:
                item.candidates = rest
        return new_plan, (
            f"Бригада отказалась{': ' + response.reason if response.reason else ''}; "
            f"предложение уходит бригаде {rest[0].engineer_id}"
        )
    new_plan.offers = [o for o in new_plan.offers if o.request_id != response.request_id]
    new_plan.unassigned = [u for u in new_plan.unassigned if u.request_id != response.request_id]
    new_plan.metrics.unassigned = len(new_plan.unassigned)
    new_plan.deferred.append(Deferred(
        request_id=response.request_id, since=response.time,
        reason="Все бригады, кому подходило, отказались: заявка переносится на следующий день",
    ))
    return new_plan, "Отказались все кандидаты — заявка на следующий день"


def is_started(route_stop_start: str, now: str) -> bool:
    """Визит уже идёт, если его начало раньше текущего времени."""
    return to_min(route_stop_start) <= to_min(now)
