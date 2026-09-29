"""Базовый вариант распределения — ровно то, что описано в ТЗ, без оптимизации.

Заявки берутся в порядке входного файла (срочные — впереди всех
остальных) и отдаются первой по порядку бригаде, у которой заявка
проходит все проверки при постановке в конец маршрута. Порядок визитов
в маршруте равен порядку назначения: ни перестановок, ни поиска
лучшего места здесь нет — этим займётся решатель.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from . import settings
from .checks import check_visit, feasible, to_clock, to_min, visit_times
from .explain import explain_assignments, unassigned_reason
from .matrices import Matrices
from .metrics import compute_metrics
from .models import Dataset, Engineer, Plan, Request, Route, Stop, Transport, Unassigned
from .travel import leg

OFFICE = "office"


@dataclass
class RouteState:
    """Маршрут бригады по ходу построения: где она и когда освободится."""

    engineer: Engineer
    position: str = OFFICE
    clock: int = 0
    start_position: str = OFFICE
    start_clock: int = 0
    frozen: int = 0
    break_start: int | None = None
    break_end: int | None = None
    stops: list[Stop] = field(default_factory=list)
    distance_km: float = 0.0
    travel_min: int = 0
    work_min: int = 0

    def to_route(self) -> Route:
        """Свернуть состояние в маршрут по контракту."""
        return Route(
            engineer_id=self.engineer.id,
            distance_km=round(self.distance_km, 1),
            travel_min=self.travel_min,
            work_min=self.work_min,
            stops=self.stops,
            break_start=to_clock(self.break_start) if self.break_start is not None else None,
            break_end=to_clock(self.break_end) if self.break_end is not None else None,
        )


def start_point(engineer: Engineer, start: str = "office") -> str:
    """Откуда бригада начинает день: офис по регламенту, дом по практике.

    Гибрид — часть из дома, часть из офиса: из дома выходит бригада, чей
    участок дальше `hybrid_home_km` от офиса, остальные — из офиса.

    Удалённый подучасток — отдельный случай: бригада, чьи визиты в контроле
    в медиане дальше порога от офиса (Кашира и Ступино — 85—95 км), при опции
    `zone_start` начинает день из своей зоны и при регламентном старте.
    Точка та же, что дом, — центр её визитов контрольного дня.
    """
    office = office_of(engineer)
    if engineer.home is None:
        return office
    if start == "home":
        return f"home:{engineer.id}"
    if start == "hybrid" and engineer.remote_km >= float(settings.option("hybrid_home_km") or 0):
        return f"home:{engineer.id}"
    if settings.option("zone_start") and engineer.remote_km >= float(settings.zone_start_km()):
        return f"home:{engineer.id}"
    return office


def office_of(engineer: Engineer) -> str:
    """Офис бригады: в наборе из нескольких участков у каждого участка свой (`office:<участок>`)."""
    return f"{OFFICE}:{engineer.sector}" if engineer.sector else OFFICE


def new_states(engineers: list[Engineer], start: str = "office") -> dict[str, RouteState]:
    """Пустые маршруты: бригады стоят в точке старта к началу смены."""
    return {
        eng.id: RouteState(
            engineer=eng, position=start_point(eng, start), clock=to_min(eng.shift_start),
            start_position=start_point(eng, start), start_clock=to_min(eng.shift_start),
        )
        for eng in engineers
    }


def probe(
    state: RouteState, request: Request, matrices: Matrices
) -> tuple[list, dict, int, float, Transport]:
    """Примерить заявку в конец маршрута: проверки, времена, дорога и чем ехать.

    Вид транспорта отдаётся вместе с минутами: без него остановка получала
    первый вид из набора бригады, и переезд в 105 км на транспорте за 289 минут
    стоял в плане «пешком».
    """
    road = leg(state.engineer, state.position, request.id, matrices, state.clock)
    arrive = state.clock + road.minutes
    checks = check_visit(
        state.engineer, request, arrive, matrices, prev_id=state.position, depart_min=state.clock
    )
    return checks, visit_times(request, arrive), road.minutes, road.km, road.mode


def append(
    state: RouteState, request: Request, times: dict, travel_min: int, travel_km: float,
    mode: Transport | None = None,
):
    """Поставить заявку в конец маршрута и подвинуть часы бригады."""
    if mode is None:
        mode = leg(state.engineer, state.position, request.id, matrices=None).mode
    state.stops.append(
        Stop(
            request_id=request.id,
            seq=len(state.stops) + 1,
            depart_prev=to_clock(state.clock),
            arrive=to_clock(times["arrive"]),
            start=to_clock(times["start"]),
            end=to_clock(times["end"]),
            travel_min=travel_min,
            travel_km=round(travel_km, 1),
            wait_min=times["wait"],
            late_min=times["late"],
            mode=mode,
            geometry=[],
        )
    )
    state.clock = times["end"]
    state.position = request.id
    state.distance_km += travel_km
    state.travel_min += travel_min
    state.work_min += request.duration_min


def order_requests(requests: list[Request]) -> list[Request]:
    """Срочные впереди, остальные — в порядке входного файла."""
    return sorted(requests, key=lambda r: 0 if settings.is_urgent(r) else 1)


def assign(
    requests: list[Request], engineers: list[Engineer], states: dict[str, RouteState],
    matrices: Matrices,
) -> tuple[list[Unassigned], dict[str, str]]:
    """Раздать заявки по ТЗ; вернуть невлезшие и карту «заявка → бригада»."""
    unassigned: list[Unassigned] = []
    owner: dict[str, str] = {}
    for request in order_requests(requests):
        placed = False
        for engineer in engineers:
            state = states[engineer.id]
            checks, times, travel_min, travel_km, mode = probe(state, request, matrices)
            if feasible(checks):
                append(state, request, times, travel_min, travel_km, mode)
                owner[request.id] = engineer.id
                placed = True
                break
        if not placed:
            code, text = unassigned_reason(request, engineers, states, matrices)
            unassigned.append(Unassigned(request_id=request.id, reason=text, reason_code=code))
    return unassigned, owner


def build_baseline(
    dataset: Dataset,
    matrices: Matrices,
    *,
    requests: list[Request] | None = None,
    states: dict[str, RouteState] | None = None,
    engineers: list[Engineer] | None = None,
    plan_id: str = "p1",
    algorithm: str = "baseline",
    changed: int = 0,
    start: str | None = None,
) -> tuple[Plan, dict[str, RouteState]]:
    """Построить базовый план региона; вернуть его и состояния маршрутов."""
    from . import settings

    start = start or str(settings.option("start") or "office")

    engineers = settings.effective_engineers(engineers if engineers is not None else dataset.engineers)
    matrices.adopt(engineers)
    requests = requests if requests is not None else dataset.requests
    states = states if states is not None else new_states(engineers, start)
    by_eng = {eng.id: eng for eng in engineers}
    for eng_id, st in states.items():
        if eng_id in by_eng:
            st.engineer = by_eng[eng_id]

    unassigned, owner = assign(requests, engineers, states, matrices)
    routes = [states[eng.id].to_route() for eng in engineers]
    explanations = explain_assignments(requests, engineers, states, owner, matrices)
    plan = Plan(
        id=plan_id,
        dataset_id=dataset.id,
        algorithm=algorithm,
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        start=start,
        settings=settings.current(),
        routes=routes,
        unassigned=unassigned,
        metrics=compute_metrics(routes, unassigned, changed=changed),
        explanations=explanations,
    )
    from .travel import resolve_day_type

    plan.day_type = resolve_day_type(matrices)
    return plan, states
