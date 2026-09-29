"""Контроль по отметкам: доказуемость работы и честная оплата, а не слежка.

Признаки собраны из практики выездного сервиса (журнал статусов Dynamics 365
Field Service: traveling → on site → completed с меткой источника) и из правил
проверки GPS-отметок (скорость между точками, одинаковые координаты входа
и выхода при коротком визите, отметка не с адреса). Каждый признак несёт
действие: что диспетчерской делать, а не только «подозрительно».

Три вещи, которые нельзя ломать:

1. **Признак — повод проверить, а не приговор.** У каждого флага есть
   `action`; бонус не начисляется до подтверждения, но и не снимается
   молча: сырые отметки остаются в журнале.
2. **Порогов немного, и они в допущениях.** Слишком быстрая работа — меньше
   половины норматива; отметка не с адреса — дальше 300 м; простой без
   обеда — дольше 45 минут; телепорт — быстрее 120 км/ч.
3. **Флаг привязан к заявке и бригаде**, чтобы его можно было открыть
   и разобрать, а не читать общим счётчиком.
"""

from __future__ import annotations

from .checks import to_min
from .distance import haversine_km
from .economy import tariffs
from .insertion import requests_of
from .models import Dataset, FraudFlag, Mark, OfferResponse, Plan

TOO_FAST_SHARE = 0.5
FAR_KM = 0.3
IDLE_MIN = 45
TELEPORT_KMH = 120
DECLINES_WARN = 3
LOW_LOAD_SHARE = 0.6


def audit(plan: Plan, dataset: Dataset, marks: list[Mark], responses: list[OfferResponse]) -> list[FraudFlag]:
    """Пройти по журналу отметок и ответов и назвать аномалии словами."""
    by_id = requests_of(dataset, plan)
    conf = tariffs()
    flags: list[FraudFlag] = []
    engineers = {eng.id: eng for eng in dataset.engineers}
    breaks = {r.engineer_id: (r.break_start, r.break_end) for r in plan.routes}

    for eng_id, eng in engineers.items():
        mine = sorted((m for m in marks if m.engineer_id == eng_id), key=lambda m: to_min(m.time))
        by_req: dict[str, dict[str, Mark]] = {}
        for m in mine:
            by_req.setdefault(m.request_id, {})[m.kind] = m

        # 1. Работа быстрее половины норматива.
        for rid, kinds in by_req.items():
            req = by_id.get(rid)
            if req and "start" in kinds and "done" in kinds:
                spent = to_min(kinds["done"].time) - to_min(kinds["start"].time)
                if spent < req.duration_min * TOO_FAST_SHARE:
                    flags.append(FraudFlag(
                        engineer_id=eng_id, request_id=rid, code="too_fast", severity="alert",
                        text=f"{eng.name}: работа по заявке {rid} закрыта за {spent} мин при нормативе {req.duration_min}",
                        action="Норму по визиту не засчитывать до подтверждения клиентом (код, подпись, звонок)",
                    ))

        # 2. Отметка не с адреса заявки.
        for rid, kinds in by_req.items():
            req = by_id.get(rid)
            if req is None:
                continue
            for kind in ("arrive", "start", "done", "no_show"):
                m = kinds.get(kind)
                if m and m.lat is not None and m.lon is not None:
                    km = haversine_km(m.lat, m.lon, req.lat, req.lon)
                    if km > FAR_KM:
                        flags.append(FraudFlag(
                            engineer_id=eng_id, request_id=rid, code="far_from_address", severity="warn",
                            text=f"{eng.name}: отметка «{kind}» по заявке {rid} в {round(km * 1000)} м от адреса",
                            action="Спросить бригаду, где она; при отметке «клиента нет» перезвонить клиенту",
                        ))
                        break

        # 3. Начал следующий визит, не закончив предыдущий.
        open_visit: str | None = None
        for m in mine:
            if m.kind == "start":
                if open_visit and open_visit != m.request_id:
                    flags.append(FraudFlag(
                        engineer_id=eng_id, request_id=m.request_id, code="overlap", severity="alert",
                        text=f"{eng.name}: начата заявка {m.request_id}, а {open_visit} не закрыта",
                        action="Уточнить статус обеих заявок; в оплату идёт только одна",
                    ))
                open_visit = m.request_id
            elif m.kind in ("done", "no_show") and m.request_id == open_visit:
                open_visit = None

        # 4. Простой между визитами дольше допустимого и не в обед.
        brk = breaks.get(eng_id, (None, None))
        prev_done: Mark | None = None
        for m in mine:
            if m.kind == "depart" and prev_done is not None:
                gap = to_min(m.time) - to_min(prev_done.time)
                in_break = brk[0] is not None and to_min(brk[0]) <= to_min(prev_done.time) <= to_min(brk[1])
                if gap > IDLE_MIN and not in_break:
                    flags.append(FraudFlag(
                        engineer_id=eng_id, request_id=m.request_id, code="idle_gap", severity="warn",
                        text=f"{eng.name}: {gap} мин между «закончил» и «выехал» без обеда",
                        action="Простой не оплачивается как работа; спросить причину, проверить геотрек",
                    ))
            if m.kind in ("done", "no_show"):
                prev_done = m
            elif m.kind == "depart":
                prev_done = None

        # 5. Телепорт: две отметки с координатами быстрее 120 км/ч.
        located = [m for m in mine if m.lat is not None and m.lon is not None]
        for a, b in zip(located, located[1:]):
            minutes = to_min(b.time) - to_min(a.time)
            km = haversine_km(a.lat, a.lon, b.lat, b.lon)
            if km > 0.5 and minutes >= 0 and km / max(minutes, 1) * 60 > TELEPORT_KMH:
                flags.append(FraudFlag(
                    engineer_id=eng_id, request_id=b.request_id, code="teleport", severity="alert",
                    text=f"{eng.name}: {round(km, 1)} км за {minutes} мин между отметками",
                    action="Координаты отметок подменены или введены руками: сверить с геотреком",
                ))

        # 6. Несколько «клиента нет» за день у одной бригады.
        no_shows = [m for m in mine if m.kind == "no_show"]
        if len(no_shows) >= 2:
            flags.append(FraudFlag(
                engineer_id=eng_id, request_id=None, code="no_show_streak", severity="warn",
                text=f"{eng.name}: {len(no_shows)} визита с отметкой «клиента нет» за день",
                action="Перезвонить клиентам; при подтверждении — оплачивается дорога и ожидание, не работа",
            ))

        # 7. Частые отказы от предложений.
        declined = [r for r in responses if r.engineer_id == eng_id and not r.accepted]
        if len(declined) >= DECLINES_WARN:
            flags.append(FraudFlag(
                engineer_id=eng_id, request_id=None, code="declines", severity="info",
                text=f"{eng.name}: {len(declined)} отказа от предложений за день",
                action="Снять флаг «готова брать сверх нормы» в профиле, если отказы без причины",
            ))

        # 8. Ранний конец дня при недоборе нормы.
        route = next((r for r in plan.routes if r.engineer_id == eng_id), None)
        dones = [m for m in mine if m.kind == "done"]
        if route and route.stops and dones:
            last = max(to_min(m.time) for m in dones)
            all_done = all(any(m.request_id == s.request_id for m in dones) for s in route.stops if s.status != "no_show")
            norm_day = int(conf["norm_day_min"])
            if all_done and route.norm_min < norm_day * LOW_LOAD_SHARE and last < to_min(eng.shift_end) - 120:
                flags.append(FraudFlag(
                    engineer_id=eng_id, request_id=None, code="low_load", severity="info",
                    text=f"{eng.name}: маршрут закрыт за два часа до конца смены при {route.norm_min} нормо-мин из {norm_day}",
                    action="Предложить заявку из очереди на завтра или отложенную; учесть в балансировке завтра",
                ))
    return flags
