"""Перепланирование после события: срочная заявка, отмена, выбывшая бригада,
новая заявка по ходу дня, перенос окна, клиента нет на месте.

Правила, которые держат качество сервиса при пересчёте (настройки `options`):

1. **Начатое не трогается.** Визит, который бригада начала до времени события,
   остаётся как есть — это уже идущая работа.
2. **Обещанное близко — не двигается.** Визиты, до начала которых меньше
   `lock_horizon_min`, тоже заморожены: клиенту уже сказали «едем», и менять
   бригаду или час нельзя. Тот же приём у Google Route Optimization
   (`ConstraintRelaxation` по порогу времени) и у Dynamics 365 RSO
   (блокировка «время и ресурс»).
3. **Остальное двигается ограниченно.** Уже запланированный визит может
   уехать позже прежнего начала не больше чем на `max_shift_min` и никогда —
   за окно клиента. Реализовано сжатием окна заявки перед пересчётом: тогда
   правило видят и решатель, и базовый вариант, и тексты проверок.
4. **Новая заявка дня либо встаёт, либо явно уходит на завтра.** Правило
   `policy`: `offer` — заявка остаётся неназначенной с предложениями бригадам,
   `direct` — отдаётся лучшему кандидату сразу. Кандидатов нет — заявка
   в `deferred` с причиной словами, а не висит в «не назначенных».
5. **Бригаду с выходного штатно не зовут.** Пересчёт раскладывает день
   по тем, кто работает по утреннему плану. Вызов с выходного — эскалация
   (`idle_call`): по умолчанию только под аварию, которую не взял никто
   из работающих даже с опозданием (эксперты Билайна, 24.09.2026).
6. **Выехавшую бригаду не разворачивают.** Визит, к которому бригада уже
   едет, заморожен вместе с начатыми: под аварию маршрут перестраивается
   после текущей работы, а не посреди дороги к ней. Горизонт блокировки
   при аварии свой (`accident_lock_horizon_min`, по умолчанию 0).
7. **Клиента нет на месте.** Бригада ждёт `no_show_wait_min`, визит
   помечается `no_show`, время с этой минуты свободно, заявка уходит
   на завтра: перезвон и новое окно — дело клиентской службы.

Разница со старым планом уходит в поле `diff`.
"""

from __future__ import annotations

from . import settings
from .baseline import RouteState, build_baseline, new_states
from .checks import to_clock, to_min
from .matrices import Matrices
from .models import ChangedRequest, Dataset, Deferred, Diff, Engineer, Event, Plan, Request

OFFICE = "office"

NEW_TYPES = ("urgent", "new_request")

# Чем кончился визит к закрытой двери — и что с заявкой дальше.
NO_SHOW_REASONS = {
    "waiting": "Бригада ждала клиента положенное время и уехала: заявка на следующий день, клиентская служба перезванивает",
    "unreachable": "Клиент не отвечает на звонки: заявка на следующий день, клиентская служба перезванивает",
    "absent": "Клиента не оказалось на месте: заявка на следующий день, клиентская служба перезванивает",
    "partial": "Работа выполнена частично, нужен повторный выезд: заявка на следующий день",
    "cancelled_on_site": "Клиент отказался от работ на месте: заявка закрыта, повторный выезд не нужен",
    "client_moved": "Клиент попросил перенести визит: заявка на следующий день с новым окном",
    "we_moved": "Перенос по решению диспетчера: заявка на следующий день, клиенту сообщено",
}


def apply_event(dataset: Dataset, event: Event, requests: list[Request] | None = None) -> tuple[list[Request], list[Engineer]]:
    """Что стало с заявками и бригадами после события."""
    requests = list(requests if requests is not None else dataset.requests)
    engineers = [eng.model_copy(deep=True) for eng in dataset.engineers]
    if event.type in NEW_TYPES and event.request is not None:
        fresh = event.request.model_copy(deep=True)
        if event.type == "urgent":
            fresh.priority = fresh.priority.__class__("urgent")
        requests = [fresh, *[r for r in requests if r.id != fresh.id]]
    elif event.type in ("cancel", "no_show"):
        requests = [req for req in requests if req.id != event.request_id]
    elif event.type == "reschedule":
        requests = [
            req.model_copy(update={
                "window_start": event.window_start or req.window_start,
                "window_end": event.window_end or req.window_end,
            }) if req.id == event.request_id else req
            for req in requests
        ]
    elif event.type == "engineer_off":
        for engineer in engineers:
            if engineer.id == event.engineer_id:
                engineer.shift_end = event.time
    return requests, engineers


def freeze(
    plan: Plan, engineers: list[Engineer], moment: int, requests: dict[str, Request],
    *, horizon: int = 0, no_show: Event | None = None, own: str | None = None,
) -> tuple[dict[str, RouteState], list[str]]:
    """Перенести в новый план визиты, начатые до события или обещанные в горизонте.

    `no_show` — событие «клиента нет»: его визит остаётся в маршруте как
    отметка `no_show` с концом через время ожидания, а не как работа.
    `own` — бригада, с которой случилось событие (выбыла, задерживается):
    её обещанные визиты горизонт не держит — она их всё равно не сделает
    в срок, и их надо двигать или отдавать.
    """
    states = new_states(engineers, plan.start)
    frozen: list[str] = []
    by_id = {eng.id: eng for eng in engineers}
    wait = int(settings.option("no_show_wait_min") or 0)
    for route in plan.routes:
        state = states.get(route.engineer_id)
        if state is None:
            continue
        reach = moment if route.engineer_id == own else moment + horizon
        for stop in route.stops:
            is_no_show = no_show is not None and stop.request_id == no_show.request_id
            # Выехала к визиту до события — едет дальше; выбывшая бригада не едет никуда.
            left = to_min(stop.arrive) - int(stop.travel_min or 0)
            on_way = route.engineer_id != own and left < moment
            if not is_no_show and ((to_min(stop.start) >= reach and not on_way) or stop.request_id not in requests):
                break
            copy = stop.model_copy(deep=True)
            if is_no_show:
                end = max(to_min(stop.arrive), moment) + wait
                copy.status = "no_show"
                copy.start = to_clock(min(to_min(stop.arrive), end))
                copy.end = to_clock(end)
                copy.wait_min, copy.late_min = wait, 0
            elif stop.status == "no_show":
                pass
            state.stops.append(copy)
            state.clock = to_min(copy.end)
            state.position = stop.request_id
            state.distance_km += stop.travel_km
            state.travel_min += stop.travel_min
            if copy.status != "no_show" and stop.request_id in requests:
                state.work_min += requests[stop.request_id].duration_min
                frozen.append(stop.request_id)
            if is_no_show:
                break
        state.frozen = len(state.stops)
        if route.break_start and route.break_end:
            state.break_start, state.break_end = to_min(route.break_start), to_min(route.break_end)
        if state.stops:
            state.engineer = by_id[route.engineer_id]
    return states, frozen


def tighten(rest: list[Request], plan: Plan, max_shift: int, max_advance: int = 0,
            skip: set[str] | None = None) -> list[Request]:
    """Сжать окна уже запланированных заявок вокруг обещанного начала.

    Не позже прежнего начала плюс `max_shift` и не раньше прежнего начала минус
    `max_advance`: клиенту назвали время, и приехать на час раньше — тоже
    перемена, на которую нужно его согласие. Освободившееся время идёт новым
    заявкам, а не сдвигу обещанных.
    """
    planned = {stop.request_id: to_min(stop.start) for route in plan.routes for stop in route.stops
               if stop.status != "no_show"}
    # Авария дня, вставшая в предел реакции, в нём и остаётся: следующие пересчёты
    # двигают её не дальше срока «появление плюс предел», иначе сдвиги копятся.
    limit = int(settings.option("emergency_reaction_min") or 0)
    deadline = {
        e.request.id: to_min(e.time) + limit for e in plan.history
        if limit and e.request is not None and e.note != "reaction_missed" and default_policy(e.request) == "direct"
    }
    out = []
    for req in rest:
        if req.id in planned and req.id not in (skip or set()):
            latest = min(to_min(req.window_end), planned[req.id] + max_shift)
            if req.id in deadline and planned[req.id] <= deadline[req.id]:
                latest = min(latest, deadline[req.id])
            earliest = max(to_min(req.window_start), planned[req.id] - max_advance)
            if earliest <= latest:
                req = req.model_copy(update={"window_start": to_clock(earliest), "window_end": to_clock(latest)})
        out.append(req)
    return out


def diff_of(plan: Plan, new_plan: Plan, event: Event, frozen: list[str]) -> Diff:
    """Что поменялось: исполнители, времена начала, задетые маршруты."""
    def index(target: Plan) -> dict[str, tuple[str, str]]:
        return {
            stop.request_id: (route.engineer_id, stop.start)
            for route in target.routes
            for stop in route.stops
            if stop.status != "no_show"
        }

    before, after = index(plan), index(new_plan)
    changed: list[ChangedRequest] = []
    routes: set[str] = set()
    for request_id in sorted(set(before) | set(after)):
        old = before.get(request_id)
        new = after.get(request_id)
        if old == new:
            continue
        changed.append(
            ChangedRequest(
                request_id=request_id,
                from_engineer=old[0] if old else None,
                to_engineer=new[0] if new else None,
                from_start=old[1] if old else None,
                to_start=new[1] if new else None,
            )
        )
        routes.update(part[0] for part in (old, new) if part)
    return Diff(
        event=event,
        changed_requests=changed,
        changed_routes=sorted(routes),
        frozen_requests=frozen,
    )


def known_requests(plan: Plan, dataset: Dataset) -> list[Request]:
    """Заявки, с которыми план живёт: набор плюс пришедшие событиями дня."""
    extra = {}
    for event in dataset.events:
        if event.request is not None:
            extra[event.request.id] = event.request
    for event in plan.history:
        if event.request is not None:
            extra[event.request.id] = event.request
    base = {req.id: req for req in dataset.requests}
    ids = {s.request_id for r in plan.routes for s in r.stops} | {u.request_id for u in plan.unassigned}
    ids |= {d.request_id for d in plan.deferred}
    out = list(dataset.requests)
    for rid in ids:
        if rid not in base and rid in extra:
            out.append(extra[rid])
    return out


def restore_windows(plan: Plan, requests: list[Request]) -> list[Request]:
    """Окна, изменённые переносами в истории плана."""
    moved = {e.request_id: e for e in plan.history if e.type == "reschedule"}
    return [
        req.model_copy(update={"window_start": moved[req.id].window_start or req.window_start,
                               "window_end": moved[req.id].window_end or req.window_end})
        if req.id in moved else req
        for req in requests
    ]


def replan(
    plan: Plan, dataset: Dataset, matrices: Matrices, event: Event, *, plan_id: str, reaction: bool = True,
    wake: bool = False,
) -> Plan:
    """Пересчитать план после события, сохранив начатое и обещанное.

    `reaction=False` — без предела реакции на аварию: так её ставят, когда
    в предел не успевает никто. Авария сегодня и с опозданием лучше аварии
    завтра; в событии остаётся пометка `reaction_missed`.

    `wake=True` — эскалация: в пересчёт входят и бригады, которые по утреннему
    плану не работают; в событии остаётся пометка `idle_called`.
    """
    asked = event
    moment = to_min(event.time)
    accident = event.type in NEW_TYPES and event.request is not None and default_policy(event.request) == "direct"
    horizon = int(settings.option("accident_lock_horizon_min" if accident else "lock_horizon_min") or 0)
    max_shift = int(settings.option("max_shift_min") or 0)
    max_advance = int(settings.option("max_advance_min") or 0)

    base_requests = restore_windows(plan, known_requests(plan, dataset))
    event = with_reaction(event) if reaction else event
    if event.type in NEW_TYPES and event.request is not None:
        # Точки заявки дня в утренней матрице нет: тот же адрес, что у известной
        # заявки, — её узел; иначе запасная оценка по координатам.
        req = event.request
        twin = next((r.id for r in base_requests if r.id != req.id and r.lat == req.lat and r.lon == req.lon), None)
        matrices.register(req.id, req.lat, req.lon, alias_of=twin)
    requests, engineers = apply_event(dataset, event, base_requests)
    on_duty = {r.engineer_id for r in plan.routes if r.stops}
    call = settings.option("idle_call") or "accident"
    keep_idle = bool(on_duty) and not wake and call != "always"
    if keep_idle:
        engineers = [eng for eng in engineers if eng.id in on_duty]
    by_id = {req.id: req for req in requests}
    deferred_ids = {d.request_id for d in plan.deferred}
    states, frozen = freeze(
        plan, engineers, moment, by_id, horizon=horizon,
        no_show=event if event.type == "no_show" else None,
        own=event.engineer_id if event.type in ("engineer_off", "delay") else None,
    )
    if event.type == "delay" and event.engineer_id in states:
        late = states[event.engineer_id]
        late.clock = max(late.clock, moment) + int(event.delay_min or 0)
    rest = [req for req in requests if req.id not in frozen and req.id not in deferred_ids]
    rest = tighten(rest, plan, max_shift, max_advance,
                   skip={event.request_id} if event.type == "reschedule" and event.request_id else None)
    mode = settings.option("replan_mode") or "local"
    new_request_ids = [event.request.id] if event.type in NEW_TYPES and event.request is not None else []
    direct = bool(new_request_ids) and (
        (event.policy or default_policy(event.request)) == "direct"
    )
    from . import stock

    # Запас устройств — утренний: считается с первого плана дня и едет дальше.
    day_stock = stock.of(plan, dataset, by_id)
    with stock.use(day_stock, by_id):
        built = _rebuild(plan, dataset, matrices, event, plan_id, mode, requests, rest, states, engineers,
                         frozen, new_request_ids, direct)
    built.stock = day_stock
    if event is not asked:
        if not any(s.request_id == event.request.id for r in built.routes for s in r.stops):
            late = asked.model_copy(update={"note": "reaction_missed"})
            return replan(plan, dataset, matrices, late, plan_id=plan_id, reaction=False, wake=wake)
        # Предел реакции — правило первой постановки. В истории плана авария живёт
        # с окном от минуты появления до конца заявленного: иначе следующий пересчёт
        # дня, сдвинув её на минуту за предел, выбросил бы аварию из плана.
        opened = asked.request.model_copy(update={
            "window_start": to_clock(min(to_min(asked.time), to_min(asked.request.window_start)))})
        built.history = [*built.history[:-1], asked.model_copy(update={"request": opened})]
    if keep_idle:
        # Бригады с выходного остаются в плане пустыми, как были утром.
        present = {r.engineer_id for r in built.routes}
        built.routes += [r.model_copy(deep=True) for r in plan.routes if r.engineer_id not in present]
        if accident and call == "accident" and not _placed(built, event.request.id):
            woken = replan(plan, dataset, matrices, asked, plan_id=plan_id, reaction=reaction, wake=True)
            if _placed(woken, event.request.id):
                woken.history = [*woken.history[:-1], woken.history[-1].model_copy(update={"note": "idle_called"})]
                return woken
    return built


def _placed(plan: Plan, request_id: str) -> bool:
    return any(s.request_id == request_id for r in plan.routes for s in r.stops)


def with_reaction(event: Event) -> Event:
    """Авария дня: окно — от минуты появления до предела реакции из настроек.

    Билайн, 19.09.2026: на сетевую аварию отводится 1—2 часа. Предел —
    настройка `emergency_reaction_min`; ноль оставляет окно заявки как есть.
    """
    request = event.request
    limit = int(settings.option("emergency_reaction_min") or 0)
    if event.type not in NEW_TYPES or request is None or not limit or default_policy(request) != "direct":
        return event
    # Сетевая авария клиента не ждёт: окно открывается в минуту появления,
    # даже если заявка пришла с окном «через час».
    appear = to_min(event.time)
    start, end = appear, appear + limit
    tight = request.model_copy(update={"window_start": to_clock(start), "window_end": to_clock(end)})
    return event.model_copy(update={"request": tight})


def _rebuild(plan, dataset, matrices, event, plan_id, mode, requests, rest, states, engineers,
             frozen, new_request_ids, direct) -> Plan:
    """Собрать новый план в выбранном режиме; аварию, не вставшую локально, добить полным пересчётом."""
    import copy

    saved = copy.deepcopy(states) if mode != "full" and direct else None
    if mode == "full":
        if plan.algorithm == "solver":
            from .solver import solve

            new_plan, _ = solve(
                dataset, matrices, requests=rest, states=states, engineers=engineers, plan_id=plan_id,
                start=plan.start,
            )
        else:
            new_plan, _ = build_baseline(
                dataset, matrices, requests=rest, states=states, engineers=engineers,
                plan_id=plan_id, algorithm=plan.algorithm, start=plan.start,
            )
    else:
        from .repair import local_repair

        new_plan, _ = local_repair(
            dataset, matrices, requests=rest, states=states, engineers=engineers, plan_id=plan_id,
            algorithm=plan.algorithm, start=plan.start,
            keep_unassigned=[u.request_id for u in plan.unassigned],
            insert_new=new_request_ids if direct else [],
            order={r.engineer_id: [s.request_id for s in r.stops] for r in plan.routes},
        )
    from .economy import summarize

    new_plan.economy = summarize(new_plan, dataset, requests)
    hot = direct and new_request_ids and default_policy(event.request) == "direct"
    placed = any(s.request_id == new_request_ids[0] for r in new_plan.routes for s in r.stops) if new_request_ids else True
    if hot and not placed and saved is not None:
        # Локальная вставка аварии не нашла места — правило эскалации:
        # полный пересчёт хвоста дня решателем. Клиентам это стоит сдвигов,
        # но авария ждать не может.
        return _rebuild(plan, dataset, matrices, event, plan_id, "full", requests, rest, saved, engineers,
                        frozen, new_request_ids, direct)
    new_plan.settings = plan.settings
    new_plan.history = [*plan.history, event]
    new_plan.deferred = list(plan.deferred)
    new_plan.diff = diff_of(plan, new_plan, event, frozen)
    new_plan.metrics.changed_requests = len(new_plan.diff.changed_requests)

    if event.type == "no_show" and event.request_id:
        new_plan.deferred.append(Deferred(
            request_id=event.request_id, since=event.time,
            reason=NO_SHOW_REASONS.get(event.note or "absent", NO_SHOW_REASONS["absent"]),
        ))
    if event.type in NEW_TYPES and event.request is not None:
        return settle_new_request(plan, new_plan, dataset, matrices, event)
    return new_plan


def default_policy(request: Request) -> str:
    """Авария и срочная — директивно, остальное — предложением."""
    return "direct" if settings.is_urgent(request) or request.skill.value == "emergency" else "offer"


def settle_new_request(old: Plan, plan: Plan, dataset: Dataset, matrices: Matrices, event: Event) -> Plan:
    """Новая заявка дня: встала — хорошо; нет — предложить, отдать или перенести на завтра."""
    rid = event.request.id
    if any(s.request_id == rid for r in plan.routes for s in r.stops):
        return plan
    offer = next((o for o in plan.offers if o.request_id == rid), None)
    candidates = offer.candidates if offer else []
    if not candidates:
        why = next((u.reason for u in plan.unassigned if u.request_id == rid), "никому не подходит")
        plan.unassigned = [u for u in plan.unassigned if u.request_id != rid]
        plan.offers = [o for o in plan.offers if o.request_id != rid]
        plan.metrics.unassigned = len(plan.unassigned)
        plan.deferred.append(Deferred(
            request_id=rid, since=event.time,
            reason=f"Сегодня взять некому: {why[0].lower() + why[1:]}. Заявка переносится на следующий день",
        ))
        return plan
    policy = event.policy or default_policy(event.request)
    if policy != "direct":
        # Предложения уже в плане: бригады ответят через своё приложение.
        # В списке заявка стоит не «никто не берёт», а «предложена, ждём ответа».
        names = ", ".join(c.engineer_id for c in candidates)
        timeout = int(settings.option("offer_timeout_min") or 5)
        for item in plan.unassigned:
            if item.request_id == rid:
                item.reason_code = "offered"
                item.reason = f"Предложена бригадам {names}; ответ ждём {timeout} мин, потом заявка уходит следующей"
        return plan
    from .insertion import assign

    best = candidates[0]
    built, _ = assign(plan, dataset, matrices, rid, best.engineer_id, best.insert_after, plan_id=plan.id)
    if built is None:
        return plan
    built.history, built.deferred, built.settings = plan.history, plan.deferred, plan.settings
    built.diff = diff_of(old, built, event, plan.diff.frozen_requests if plan.diff else [])
    built.metrics.changed_requests = len(built.diff.changed_requests)
    return built
