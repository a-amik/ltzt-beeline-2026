"""Локальный ремонт плана после события — вместо пересчёта всего дня.

Полный пересчёт решателем находит план получше, но переставляет полдня:
на имитации Юго-востока пять событий двигали 250 визитов. Клиенту это
читается «нам три раза меняли время». Поэтому по умолчанию план после
события ремонтируется локально, как советует обзор динамических VRP
(Pillac et al.): порядок визитов у каждой бригады сохраняется, времена
пересчитываются от точки, где бригада стоит; выпавшие визиты и новые заявки
встают дешёвой вставкой к той бригаде, которой это стоит меньше всего дороги.
Полный пересчёт остаётся настройкой `replan_mode: full` — для случаев, когда
диспетчер готов менять день ради результата.

Три вещи, которые нельзя ломать:

1. **Порядок визитов бригады не меняется сам.** Только времена — и только
   в пределах допустимого сдвига и окна клиента (окна уже сжаты в `replan`).
2. **Визит, который перестал помещаться, не пропадает молча:** он идёт
   в очередь на вставку к другим бригадам, а если никто не берёт — в
   «не назначены» с причиной и предложениями за бонус.
3. **Норма дня уважается при вставке:** бригаде без согласия на нагрузку
   сверх нормы ничего не добавляют, с согласием — не больше её предела.
"""

from __future__ import annotations

from datetime import UTC, datetime

from . import settings
from .baseline import RouteState
from .economy import norm_minutes, summarize, tariffs
from .explain import explain_assignments, unassigned_reason
from .insertion import best_insertion, build_offers, nearest_states, rebuild
from .matrices import Matrices
from .models import Dataset, Engineer, Plan, Request, Unassigned


def _norm_of(state: RouteState, by_id: dict[str, Request], conf: dict) -> int:
    return sum(norm_minutes(by_id[s.request_id], conf) for s in state.stops
               if s.request_id in by_id and s.status != "no_show")


def _fits_norm(state: RouteState, request: Request, by_id: dict[str, Request], conf: dict) -> bool:
    eng = state.engineer
    after = _norm_of(state, by_id, conf) + norm_minutes(request, conf)
    from .economy import norm_limit

    return after <= norm_limit(eng, conf)


def keep_order(
    state: RouteState, order: list[str], rest_by_id: dict[str, Request], matrices: Matrices,
) -> list[Request]:
    """Перестроить маршрут в прежнем порядке; вернуть визиты, которые не поместились.

    `order` — порядок заявок бригады в прежнем плане; замороженный префикс
    уже стоит в `state.stops`, остальное перестраивается за ним.
    """
    done = {s.request_id for s in state.stops}
    tail = [rest_by_id[rid] for rid in order if rid not in done and rid in rest_by_id]
    kept: list[Request] = []
    orphans: list[Request] = []
    for req in tail:
        fresh, _ = rebuild(state, [*kept, req], matrices, guard=set())
        if fresh is None:
            orphans.append(req)
        else:
            kept.append(req)
    fresh, _ = rebuild(state, kept, matrices, guard=set())
    if fresh is not None:
        state.stops, state.clock, state.position = fresh.stops, fresh.clock, fresh.position
        state.distance_km, state.travel_min, state.work_min = fresh.distance_km, fresh.travel_min, fresh.work_min
        state.break_start, state.break_end = fresh.break_start, fresh.break_end
    return orphans


def is_hot(request: Request) -> bool:
    """Авария и срочная: их ставят как можно раньше, а не как можно дешевле."""
    return bool(settings.option("emergency_first")) and (
        settings.is_urgent(request) or request.skill.value == "emergency"
    )


def cheapest_insertion(
    states: dict[str, RouteState], request: Request, matrices: Matrices, by_id: dict[str, Request], conf: dict,
) -> tuple[str, RouteState] | None:
    """Кому заявка обходится дешевле всего по дороге с учётом навыка, транспорта и нормы.

    Аварии — не дешевле, а раньше: у кого она начнётся первой.
    """
    hot = is_hot(request)
    best: tuple[tuple[int, int], str, RouteState] | None = None
    able = {
        eng_id: st for eng_id, st in states.items()
        if request.skill in st.engineer.skills
        and (request.transport is None or request.transport in st.engineer.transports)
    }
    for state in nearest_states(able, request, matrices):
        eng, eng_id = state.engineer, state.engineer.id
        if not _fits_norm(state, request, by_id, conf) and not (hot and eng.extra_load):
            continue  # авария берётся сверх предела нагрузки, но только у согласной на неё бригады
        found = best_insertion(state, request, matrices, by_id, earliest=hot)
        if found is None:
            continue
        fresh, delta, _ = found
        from .checks import to_min
        from .economy import sector_entries

        # Въезд в чужой участок — в минутах дороги по тарифу: чужая бригада берёт
        # заявку, только когда своя не может или дорога своей дороже этой цены.
        rate = int(conf.get("sector_cross_rub", 0))
        if rate and eng.sector and request.sector and eng.sector != request.sector:
            ids = [s.request_id for s in fresh.stops]
            extra = sector_entries(eng, ids, {**by_id, request.id: request}) - sector_entries(
                eng, [i for i in ids if i != request.id], by_id)
            delta += extra * rate // max(1, int(conf["travel_rub_per_min"]))
        begin = to_min(next(s.start for s in fresh.stops if s.request_id == request.id))
        key = (begin, delta) if hot else (delta, begin)
        if best is None or key < best[0]:
            best = (key, eng_id, fresh)
    return (best[1], best[2]) if best else None


def _priority(request: Request) -> tuple[int, int]:
    urgent = 0 if settings.is_urgent(request) or request.skill.value == "emergency" else 1
    from .checks import to_min

    return urgent, to_min(request.window_start)


def local_repair(
    dataset: Dataset, matrices: Matrices, *, requests: list[Request], states: dict[str, RouteState],
    engineers: list[Engineer], plan_id: str, algorithm: str, start: str, keep_unassigned: list[str],
    insert_new: list[str], order: dict[str, list[str]],
) -> tuple[Plan, dict[str, RouteState]]:
    """Собрать план локальным ремонтом: порядок прежний, времена новые, сироты вставлены.

    `keep_unassigned` — заявки, которые до события были не назначены: их тоже
    примеряют в освободившееся время. `insert_new` — заявки события: их
    вставляют, только если они в этом списке (правило `direct`); иначе они
    остаются неназначенными с предложениями бригадам.
    """
    conf = tariffs()
    matrices.adopt(engineers)
    by_id = {req.id: req for req in requests}
    by_eng = {eng.id: eng for eng in engineers}
    for eng_id, st in states.items():
        if eng_id in by_eng:
            st.engineer = by_eng[eng_id]
    planned = {rid for ids in order.values() for rid in ids} | {s.request_id for st in states.values() for s in st.stops}
    queue: list[Request] = []
    for eng_id, st in states.items():
        queue.extend(keep_order(st, order.get(eng_id, []), by_id, matrices))
    for rid in keep_unassigned:
        if rid in by_id and rid not in planned:
            queue.append(by_id[rid])
    for req in requests:
        placed = any(s.request_id == req.id for st in states.values() for s in st.stops)
        if not placed and req.id not in {q.id for q in queue} and req.id not in keep_unassigned:
            if req.id in insert_new or req.id in planned:
                queue.append(req)
    hold = {rid for rid in (r.id for r in requests) if rid not in insert_new and not any(
        s.request_id == rid for st in states.values() for s in st.stops) and rid not in planned
        and rid not in keep_unassigned}

    owner: dict[str, str] = {s.request_id: st.engineer.id for st in states.values() for s in st.stops}
    unassigned: list[Unassigned] = []
    for req in sorted(queue, key=_priority):
        found = cheapest_insertion(states, req, matrices, by_id, conf)
        if found is None:
            code, text = unassigned_reason(req, engineers, states, matrices)
            unassigned.append(Unassigned(request_id=req.id, reason=text, reason_code=code))
            continue
        eng_id, fresh = found
        states[eng_id] = fresh
        owner[req.id] = eng_id
    for rid in sorted(hold):
        req = by_id[rid]
        code, text = unassigned_reason(req, engineers, states, matrices)
        unassigned.append(Unassigned(request_id=rid, reason=text, reason_code=code))

    routes = [states[eng.id].to_route() for eng in engineers]
    from .metrics import compute_metrics

    scope = [req for req in requests if req.id in owner or req.id in {u.request_id for u in unassigned}]
    plan = Plan(
        id=plan_id, dataset_id=dataset.id, algorithm=algorithm,
        created_at=datetime.now(UTC).isoformat(timespec="seconds"), start=start,
        settings=settings.current(), routes=routes, unassigned=unassigned,
        metrics=compute_metrics(routes, unassigned),
        explanations=explain_assignments(scope, engineers, states, owner, matrices),
    )
    plan.economy = summarize(plan, dataset, requests, conf)
    from .travel import resolve_day_type

    plan.day_type = resolve_day_type(matrices)
    plan.offers = build_offers(states, [by_id[u.request_id] for u in unassigned if u.request_id in by_id],
                               engineers, matrices, dataset, requests)
    return plan, states
