"""Вставка заявки в готовый маршрут: предложения с бонусом и ручная замена.

Одна операция под двумя именами. Диспетчер переставляет заявку другой
бригаде руками — это `assign`. Система предлагает неназначенную заявку
бригаде, у которой она дешевле всего встаёт в маршрут, за бонус сверх
нормы — это `build_offers`. В обоих случаях маршрут перестраивается
последовательно через те же проверки `checks.check_visit`, что и план,
и замороженные визиты (начатые до события) не двигаются.

Механика предложений — как у агрегаторов: цена вставки считается для каждой
готовой бригады (`extra_load`), предложение уходит нескольким лучшим
по дороге, бонус — нормо-минуты заявки по повышенной ставке, умноженные
на дефицит окна. Ответ бригады прототип не ждёт: принятие предложения —
это `assign` с тем же `engineer_id`.

Три вещи, которые нельзя ломать:

1. **Вставка не ломает остальной маршрут.** После вставки все визиты
   пересчитываются от точки старта и проверяются заново; одно нарушение —
   и место не годится.
2. **Предел нагрузки уважается.** Бригада без `extra_load` не получает
   ничего сверх нормы дня; с флагом — не больше `extra_limit_min` сверх.
3. **Причина отказа возвращается словами**, а не кодом ошибки: диспетчер
   должен понимать, почему замена невозможна.
4. **Заявку примеряют ближайшим бригадам, а не всем.** Примерка — это
   перестройка маршрута на каждое место, и при ста бригадах она стоила
   дороже самого поиска: на 1 000 заявок × 100 бригад хвост после
   решателя занимал 27 секунд из 31. Кандидаты берутся по прямой от заявки
   до ближайшей точки маршрута бригады, числом `scan_limit` (12);
   у регионов заказчика бригад меньше, и там примеряют всех, как прежде.
   Диспетчерская замена руками (`assign`) кандидатов не отбирает — там
   бригада уже названа.
"""

from __future__ import annotations

from datetime import UTC, datetime

from . import settings
from .baseline import RouteState, append, new_states
from .checks import check_visit, feasible, first_failure, to_clock, to_min, visit_times
from .distance import haversine_km
from .economy import deficit_by_window, deficit_coef, norm_minutes, summarize, tariffs
from .explain import REASON_TEMPLATES, explain_assignments, unassigned_reason
from .matrices import Matrices
from .metrics import compute_metrics
from .models import (
    Dataset,
    Engineer,
    Event,
    Offer,
    OfferCandidate,
    Plan,
    Request,
    Unassigned,
)
from .solver import break_conf
from .travel import leg


def stock_labels(devices: list[str]) -> list[str]:
    """Подписи устройств по-русски — из допущений."""
    from .geocode import load_assumptions

    labels = load_assumptions().get("equipment", {}).get("labels", {})
    return [labels.get(d, d) for d in devices]


def requests_of(dataset: Dataset, plan: Plan | None = None) -> dict[str, Request]:
    """Заявки региона вместе с заявками событий — набора и истории плана."""
    by_id = {req.id: req for req in dataset.requests}
    for event in dataset.events:
        if event.request is not None:
            by_id.setdefault(event.request.id, event.request)
    for event in plan.history if plan else []:
        if event.request is not None:
            by_id[event.request.id] = event.request
        elif event.type == "reschedule" and event.request_id in by_id:
            req = by_id[event.request_id]
            by_id[req.id] = req.model_copy(update={
                "window_start": event.window_start or req.window_start,
                "window_end": event.window_end or req.window_end,
            })
    return by_id


def rebuild(
    state: RouteState, ordered: list[Request], matrices: Matrices, *, guard: set[str] | None = None,
) -> tuple[RouteState | None, str | None]:
    """Перестроить маршрут бригады по списку заявок от точки старта.

    Возвращает новое состояние или причину, почему так не получается.
    Замороженные визиты (`state.frozen`) переносятся как есть.

    `guard` — с какого визита держать запас надёжности (`risk.Buffer`):
    `None` — у всех; набор идентификаторов — начиная с первого из них.
    Пустой набор запас выключает: так перестраивается уже обещанное —
    рискованный визит лучше отменённого, и пересчёт дня его не выбрасывает.
    """
    from .risk import LATE_TEXT, buffer

    buf = buffer()
    acc, armed = 0.0, guard is None
    brk = break_conf()
    brk_len, brk_lo, brk_hi = int(brk["duration_min"]), to_min(brk["earliest"]), to_min(brk["latest"])
    fresh = RouteState(
        engineer=state.engineer, position=state.start_position, clock=state.start_clock,
        start_position=state.start_position, start_clock=state.start_clock, frozen=state.frozen,
    )
    for stop in state.stops[: state.frozen]:
        fresh.stops.append(stop.model_copy(deep=True))
        fresh.clock, fresh.position = to_min(stop.end), stop.request_id
        fresh.distance_km += stop.travel_km
        fresh.travel_min += stop.travel_min
    fixed = None
    if state.break_start is not None and state.break_start < fresh.clock:
        fresh.break_start, fresh.break_end = state.break_start, state.break_end  # обед уже был
    elif state.break_start is not None:
        fixed = (state.break_start, state.break_end)  # обед запланирован: держим его время
    for req in ordered:
        road = leg(fresh.engineer, fresh.position, req.id, matrices, fresh.clock)
        arrive = fresh.clock + road.minutes
        if fresh.break_start is None and brk_len and fixed is not None:
            b0, b1 = fixed
            begin = max(arrive, to_min(req.window_start))
            if b0 < fresh.clock and fresh.clock <= brk_hi:
                # Предыдущий визит затянулся дальше запланированного обеда — обед сразу после него.
                fresh.break_start, fresh.break_end = fresh.clock, fresh.clock + brk_len
                arrive += brk_len
            elif fresh.clock <= b0 < begin:
                fresh.break_start, fresh.break_end = b0, b1
                if b0 < arrive:
                    arrive += brk_len  # обед пришёлся на дорогу
                elif b1 > begin:
                    arrive = b1  # обед в ожидании окна затянулся дальше его начала
        elif fresh.break_start is None and brk_len and brk_lo <= max(fresh.clock, brk_lo) <= brk_hi:
            # Обед не запланирован — жадно: первый просвет после начала окна обеда, до его конца.
            window_start = to_min(req.window_start)
            gap_ok = max(arrive, window_start) - max(fresh.clock, brk_lo) >= brk_len
            if fresh.clock >= brk_lo or gap_ok:
                fresh.break_start = max(fresh.clock, brk_lo)
                fresh.break_end = fresh.break_start + brk_len
                arrive = max(arrive, fresh.break_end + road.minutes if fresh.clock >= brk_lo else arrive)
        checks = check_visit(fresh.engineer, req, arrive, matrices, prev_id=fresh.position, depart_min=fresh.clock)
        if not feasible(checks):
            failed = next(c for c in checks if not c.ok)
            return None, failed.text
        times = visit_times(req, arrive)
        if buf.on:
            armed = armed or req.id in (guard or ())
            acc += buf.road(road.minutes)
            if armed and arrive + acc > to_min(req.window_end):
                return None, LATE_TEXT
            acc = buf.after_start(acc, arrive, times["start"]) + buf.job(req.duration_min)
        append(fresh, req, times, road.minutes, road.km, road.mode)
    if fresh.break_start is None and brk_len and fresh.clock <= brk_hi:
        fresh.break_start = max(fresh.clock, fixed[0] if fixed else brk_lo)
        fresh.break_end = fresh.break_start + brk_len
    return fresh, None


def movable(state: RouteState, by_id: dict[str, Request]) -> list[Request]:
    """Незамороженные заявки маршрута в текущем порядке."""
    return [by_id[s.request_id] for s in state.stops[state.frozen :] if s.request_id in by_id]


def best_insertion(
    state: RouteState, request: Request, matrices: Matrices, by_id: dict[str, Request],
    insert_after: str | None = None, *, earliest: bool = False, buffered: bool = True,
) -> tuple[RouteState, int, str | None] | None:
    """Лучшее место заявки в маршруте: новое состояние, добавка дороги, после кого.

    `earliest` — для аварии: место выбирается по самому раннему началу
    работ, а не по добавке дороги; дорога идёт вторым ключом.
    `buffered=False` — примерка без запаса надёжности: так выясняют, что
    место в маршруте есть, но только впритык.
    """
    from . import stock

    # Устройства заявки должны остаться у бригады: запас утренний, днём он конечен.
    if stock.missing(state.engineer.id, state.stops, request, by_id):
        return None
    tail = movable(state, by_id)
    positions = range(len(tail) + 1)
    if insert_after is not None:
        idx = next((i + 1 for i, req in enumerate(tail) if req.id == insert_after), None)
        if idx is None and state.frozen and state.stops[state.frozen - 1].request_id == insert_after:
            idx = 0
        if idx is None:
            return None
        positions = [idx]
    best = None
    # Маршрут упорядочен по времени: место после визита, который начинается
    # позже конца окна заявки, не годится само и не годятся все следующие.
    starts = {s.request_id: to_min(s.start) for s in state.stops}
    window_end = to_min(request.window_end)
    for pos in positions:
        if pos > 0 and starts.get(tail[pos - 1].id, 0) > window_end:
            break
        ordered = tail[:pos] + [request] + tail[pos:]
        fresh, _ = rebuild(state, ordered, matrices, guard={request.id} if buffered else set())
        if fresh is None:
            continue
        delta = fresh.travel_min - state.travel_min
        begin = to_min(next(s.start for s in fresh.stops if s.request_id == request.id))
        key = (begin, delta) if earliest else (delta, begin)
        if best is None or key < best[3]:
            prev = ordered[pos - 1].id if pos > 0 else (
                state.stops[state.frozen - 1].request_id if state.frozen else None
            )
            best = (fresh, delta, prev, key)
    return best[:3] if best else None


def nearest_states(
    states: dict[str, RouteState], request: Request, matrices: Matrices, limit: int | None = None,
) -> list[RouteState]:
    """Бригады, чей маршрут проходит ближе всего к заявке, — по прямой, числом `limit`.

    Бригад не больше предела — возвращаются все в исходном порядке, и отбор
    ничего не меняет. Точки без координат считаются далёкими.
    """
    limit = int(settings.option("scan_limit") or 0) if limit is None else limit
    ordered = list(states.values())
    if limit <= 0 or len(ordered) <= limit:
        return ordered
    here = matrices.coords.get(request.id)
    if here is None:
        return ordered[:limit]

    def distance(state: RouteState) -> float:
        points = [state.position, *(s.request_id for s in state.stops)]
        known = [matrices.coords.get(matrices.aliases.get(p, p)) for p in points]
        return min((haversine_km(here[0], here[1], c[0], c[1]) for c in known if c), default=1e9)

    return sorted(ordered, key=distance)[:limit]


def build_offers(
    states: dict[str, RouteState], unassigned: list[Request], engineers: list[Engineer],
    matrices: Matrices, dataset: Dataset, requests: list[Request] | None = None,
) -> list[Offer]:
    """По каждой неназначенной заявке — кому и за сколько её предложить."""
    conf = tariffs()
    by_id = {**requests_of(dataset), **{r.id: r for r in requests or []}}
    deficits = deficit_by_window(dataset, requests, conf)
    norm_day = int(conf["norm_day_min"])
    by_eng = {eng.id: eng for eng in engineers}
    offers: list[Offer] = []
    for req in unassigned:
        coef = deficit_coef(req, deficits)
        found: list[OfferCandidate] = []
        able = {
            eng_id: st for eng_id, st in states.items()
            if eng_id in by_eng and req.skill in by_eng[eng_id].skills
            and (req.transport is None or req.transport in by_eng[eng_id].transports)
        }
        for state in nearest_states(able, req, matrices):
            eng = by_eng[state.engineer.id]
            best = best_insertion(state, req, matrices, by_id)
            if best is None:
                continue
            fresh, delta, prev = best
            norm_before = sum(norm_minutes(by_id[s.request_id], conf) for s in state.stops if s.request_id in by_id)
            norm_after = norm_before + norm_minutes(req, conf)
            if norm_after > norm_day + (eng.extra_limit_min if eng.extra_load else 0):
                continue
            over = max(0, norm_after - max(norm_before, norm_day))
            bonus = round(over * conf["norm_rate_rub_per_min"] * float(conf["bonus_multiplier"]) * coef)
            stop = next(s for s in fresh.stops if s.request_id == req.id)
            old_starts = {s.request_id: to_min(s.start) for s in state.stops}
            shift = max((to_min(s.start) - old_starts[s.request_id] for s in fresh.stops
                         if s.request_id in old_starts), default=0)
            where = f"после заявки {prev}" if prev else "первой в маршруте"
            road_text = f"+{delta} мин дороги" if delta > 0 else (f"дорога короче на {-delta} мин" if delta < 0 else "без лишней дороги")
            text = (
                f"{eng.name}: {where}, приезд {stop.arrive}, {road_text}"
                + (f", следующие визиты позже до {shift} мин" if shift > 0 else ", остальные визиты на месте")
                + (f", бонус {bonus} ₽ за {over} нормо-минут сверх нормы" if bonus else ", в пределах нормы дня")
            )
            found.append(OfferCandidate(
                engineer_id=eng.id, insert_after=prev, arrive=stop.arrive, start=stop.start,
                delta_travel_min=delta, delta_norm_min=norm_minutes(req, conf), delta_shift_min=max(0, shift),
                bonus_rub=bonus, text=text,
            ))
        found.sort(key=lambda c: (c.delta_shift_min > 0, c.delta_travel_min, c.bonus_rub))
        offers.append(Offer(request_id=req.id, coef=coef, candidates=found[: int(conf["offer_candidates"])]))
    return offers


def restore_states(plan: Plan, dataset: Dataset, matrices: Matrices) -> dict[str, RouteState]:
    """Состояния маршрутов из готового плана: чтобы менять его дальше."""
    by_id = requests_of(dataset, plan)
    states = new_states(dataset.engineers, plan.start)
    for route in plan.routes:
        state = states.get(route.engineer_id)
        if state is None:
            continue
        for stop in route.stops:
            state.stops.append(stop.model_copy(deep=True))
            state.clock, state.position = to_min(stop.end), stop.request_id
            state.distance_km += stop.travel_km
            state.travel_min += stop.travel_min
            if stop.status != "no_show" and stop.request_id in by_id:
                state.work_min += by_id[stop.request_id].duration_min
        if route.break_start:
            state.break_start, state.break_end = to_min(route.break_start), to_min(route.break_end)
    if plan.diff:
        frozen = set(plan.diff.frozen_requests)
        for state in states.values():
            state.frozen = sum(1 for s in state.stops if s.request_id in frozen)
    return states


def assign(
    plan: Plan, dataset: Dataset, matrices: Matrices, request_id: str, engineer_id: str,
    insert_after: str | None, *, plan_id: str,
) -> tuple[Plan | None, str | None]:
    """Отдать заявку бригаде руками: новый план или причина отказа словами."""
    from .replan import diff_of

    by_id = requests_of(dataset, plan)
    request = by_id.get(request_id)
    if request is None:
        return None, f"Заявки {request_id} в регионе нет"
    effective = settings.effective_engineers(dataset.engineers)
    matrices.adopt(effective)
    engineers = {eng.id: eng for eng in effective}
    if engineer_id not in engineers:
        return None, f"Бригады {engineer_id} в регионе нет"
    states = restore_states(plan, dataset, matrices)
    for eng_id, st in states.items():
        st.engineer = engineers[eng_id]
    owner = next((r.engineer_id for r in plan.routes for s in r.stops if s.request_id == request_id), None)
    if owner is not None:
        old = states[owner]
        if any(s.request_id == request_id for s in old.stops[: old.frozen]):
            return None, f"Заявка {request_id} уже начата, её не переставляют"
        fresh, why = rebuild(old, [r for r in movable(old, by_id) if r.id != request_id], matrices, guard=set())
        if fresh is None:
            return None, f"Без заявки маршрут {engineers[owner].name} не перестраивается: {why}"
        states[owner] = fresh
    target = states[engineer_id]
    from . import stock

    day_stock = stock.of(plan, dataset, by_id)
    with stock.use(day_stock):
        lacking = stock.missing(engineer_id, target.stops, request, by_id)
        best = best_insertion(target, request, matrices, by_id, insert_after)
    if lacking:
        names = ", ".join(stock_labels(lacking))
        return None, f"У бригады {target.engineer.name} не осталось устройств: {names}. Запас утренний, днём он не пополняется"
    if best is None:
        probe = check_visit(target.engineer, request, target.clock, matrices, prev_id=target.position)
        code = first_failure(probe) or "all_busy"
        return None, REASON_TEMPLATES.get(code, "Заявка не встаёт в маршрут").format(
            skill=request.skill.value, transport=request.transport.value if request.transport else "транспорт",
            duration=request.duration_min, window=f"{request.window_start}–{request.window_end}",
            shift_end=target.engineer.shift_end,
        ) + f" — у бригады {target.engineer.name} она не встаёт ни в одно место"
    states[engineer_id] = best[0]

    all_requests = list(by_id.values()) if plan.diff else list(dataset.requests)
    owner_map = {s.request_id: st.engineer.id for st in states.values() for s in st.stops}
    planned_ids = {s.request_id for r in plan.routes for s in r.stops} | {u.request_id for u in plan.unassigned}
    scope = [req for req in all_requests if req.id in planned_ids or req.id == request_id]
    unassigned = []
    for req in scope:
        if req.id in owner_map:
            continue
        with stock.use(day_stock, by_id):
            code, text = unassigned_reason(req, effective, states, matrices)
        unassigned.append(Unassigned(request_id=req.id, reason=text, reason_code=code))
    routes = [states[eng.id].to_route() for eng in effective]
    new_plan = Plan(
        id=plan_id, dataset_id=dataset.id, algorithm=plan.algorithm,
        created_at=datetime.now(UTC).isoformat(timespec="seconds"), start=plan.start,
        routes=routes, unassigned=unassigned,
        metrics=compute_metrics(routes, unassigned),
        explanations=explain_assignments(scope, effective, states, owner_map, matrices),
        settings=settings.current(),
    )
    event = Event(id="manual", type="manual", time=to_clock(0), request_id=request_id, engineer_id=engineer_id)
    frozen = plan.diff.frozen_requests if plan.diff else []
    new_plan.history, new_plan.deferred = list(plan.history), [d for d in plan.deferred if d.request_id != request_id]
    new_plan.diff = diff_of(plan, new_plan, event, frozen)
    new_plan.metrics.changed_requests = len(new_plan.diff.changed_requests)
    new_plan.economy = summarize(new_plan, dataset, scope)
    from .travel import resolve_day_type

    new_plan.day_type = resolve_day_type(matrices)
    new_plan.stock = day_stock
    with stock.use(day_stock, by_id):
        new_plan.offers = build_offers(states, [by_id[u.request_id] for u in unassigned], effective,
                                       matrices, dataset, scope)
    return new_plan, None
