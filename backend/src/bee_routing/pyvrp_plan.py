"""Второй решатель: PyVRP — для сравнения с OR-Tools на тех же данных и в тех же рублях.

Зачем. Обзор решений (лист «Обзор решений и подходов») оставил OR-Tools
за допуск по навыку, обед и тёплый старт прямо в API, а PyVRP назвал
сильнейшим по качеству поиска на стандартных наборах VRPTW. Какой из двух
лучше на наших регионах, решает замер, а не репутация: PyVRP встаёт пятой
стратегией портфеля (`portfolio.py`), получает те же секунды и меряется той
же меркой — меньше неназначенных, больше итог дня.

Как наша задача ложится на PyVRP:

- **Бригада — свой тип машины** (одна штука): свой старт (дом или офис),
  своя смена, свой профиль матриц. Цена дуги — те же рубли, что у OR-Tools
  (`arcs.group_matrices`): минуты инженера и километры автомобиля.
- **Маршрут открытый:** дорога обратно в точку старта стоит ноль.
- **Допуска по навыку у PyVRP нет** — обход через профиль: недопустимая
  пара «бригада — заявка» получает запретительную цену дуги, и раз заявка
  необязательная (приз — её ценность), дешевле её не брать.
- **Норма дня — грузоподъёмность:** заявка «весит» свои нормо-минуты,
  предел — норма дня. Цены сверх нормы у PyVRP нет (бонус по повышенной
  ставке в его цель не записать), поэтому сверх нормы он не ставит вовсе:
  с пределом «норма плюс допустимое» он перегружал бригады, и итог дня
  выходил на 15—20 тыс. ₽ ниже, чем у OR-Tools, при более коротких
  маршрутах. Работу сверх нормы добирает полировка вставкой — она бонус
  считает.
- **Обеда PyVRP не знает.** Он встаёт после: порядок визитов берётся
  у PyVRP, часы считает наше поджатие (`solver._compact`) с обедом перед
  первым визитом после начала окна обеда; визит, который из-за обеда
  выпал из окна, покидает маршрут и идёт в полировку вставкой.

Хвост — общий (`solver.finish`): причины отказов, экономика, предложения.
"""

from __future__ import annotations

import time

import numpy as np

from . import settings
from .arcs import group_matrices
from .baseline import RouteState, append, new_states
from .checks import to_min
from .economy import norm_minutes, skip_penalty, tariffs
from .matrices import Matrices
from .models import Dataset, Plan, Request

FORBIDDEN = 100_000_000  # больше любой цены пропуска вместе с надбавкой ступени
MAX_REQUESTS = 600  # матрица на бригаду: на дне в тысячи заявок это гигабайты


def solve_pyvrp(dataset: Dataset, matrices: Matrices, *, plan_id: str, start: str,
                time_limit_s: int, seed: int = 1) -> tuple[Plan, dict[str, RouteState]] | None:
    """Утренний план через PyVRP; None — задача ему не по размеру или пакета нет."""
    try:
        from pyvrp import Client, Depot, Location, ProblemData, VehicleType
        from pyvrp import solve as run
        from pyvrp.stop import MaxRuntime
    except ImportError:
        return None
    from .risk import buffer
    from .solver import _buffer_victim, _compact, allowed_vehicles, break_conf, finish

    t0 = time.perf_counter()
    conf, brk = tariffs(), break_conf()
    engineers = settings.effective_engineers(dataset.engineers)
    matrices.adopt(engineers)
    requests = list(dataset.requests)
    if not requests or len(requests) > MAX_REQUESTS:
        return None
    states = new_states(engineers, start)
    vehicles = [states[eng.id] for eng in engineers]
    n_veh, n_req = len(vehicles), len(requests)
    node_point = [st.position for st in vehicles] + [r.id for r in requests]
    rub_min, rub_km = int(conf["travel_rub_per_min"]), float(conf["car_rub_per_km"])
    allowed = [set(allowed_vehicles(req, engineers)) for req in requests]
    from .zones import free_points, point_zones

    cross_rub = int(conf.get("zone_cross_rub", 0))
    sector_rub = int(conf.get("sector_cross_rub", 0)) if matrices.sectors else 0
    node_zones = point_zones(node_point, matrices, free_points(requests)) if cross_rub or sector_rub else None

    from .arcs import home_column
    from .objective import long_leg

    transit_rub = int(conf.get("transit_rub_per_leg", 0))
    home_share = float(conf.get("return_home_share", 0) or 0)
    shared: dict[tuple[str, ...], tuple[np.ndarray, np.ndarray]] = {}
    distances, durations = [], []
    for v, eng in enumerate(engineers):
        key = tuple(t.value for t in eng.transports)
        if key not in shared:
            minutes, cost = group_matrices(eng, node_point, [0] * len(node_point), matrices, rub_min, rub_km,
                                           zones=node_zones, cross_rub=cross_rub, sector_rub=sector_rub,
                                           transit_rub=transit_rub, long_leg=long_leg(conf),
                                           km_rub=float(conf.get("km_metric_rub", 0) or 0))
            shared[key] = (np.asarray(minutes, dtype=np.int64), np.asarray(cost, dtype=np.int64))
        minutes, cost = (m.copy() for m in shared[key])
        minutes[:, :n_veh] = 0  # открытый маршрут: назад в точку старта — даром по времени
        cost[:, :n_veh] = 0
        if home_share > 0:
            # …но не по цене: половина дороги домой (`economy.return_home_share`), как в `solver`.
            back = home_column(eng, node_point, vehicles[v].start_position, matrices, rub_min, rub_km, transit_rub)
            cost[:, v] = np.rint(back * home_share).astype(np.int64)
        for j in range(n_req):
            if v not in allowed[j]:
                cost[:, n_veh + j] = FORBIDDEN
        np.fill_diagonal(minutes, 0)
        np.fill_diagonal(cost, 0)
        durations.append(minutes)
        distances.append(cost)

    norm_day = int(conf["norm_day_min"])
    locations = [Location(0, 0) for _ in node_point]
    depots = [Depot(v) for v in range(n_veh)]
    clients = [
        Client(n_veh + j, delivery=[norm_minutes(req, conf)], service_duration=req.duration_min,
               tw_early=to_min(req.window_start), tw_late=to_min(req.window_end),
               prize=skip_penalty(req, conf), required=False, name=req.id)
        for j, req in enumerate(requests)
    ]
    types = [
        VehicleType(1, capacity=[norm_day],
                    start_depot=v, end_depot=v, fixed_cost=int(conf["engineer_day_rub"]),
                    tw_early=states[eng.id].clock, tw_late=to_min(eng.shift_end), profile=v, name=eng.id)
        for v, eng in enumerate(engineers)
    ]
    data = ProblemData(locations, clients, depots, types, distances, durations)
    result = run(data, stop=MaxRuntime(max(1, time_limit_s)), seed=seed, display=False)
    t_search = time.perf_counter()

    buf = buffer()
    brk_len, brk_lo, brk_hi = int(brk["duration_min"]), to_min(brk["earliest"]), to_min(brk["latest"])
    owner: dict[str, str] = {}
    for route in result.best.routes():
        st = vehicles[route.vehicle_type()]
        # Клиент в расписании маршрута назван своим номером в списке клиентов.
        order = [requests[_index(step)] for step in route.schedule() if _flag(step, "is_client")]
        wants_lunch = bool(brk_len) and st.clock <= brk_hi and to_min(st.engineer.shift_end) > brk_hi
        while True:
            lunch_before = _lunch_place(st, order, brk_lo, matrices) if wants_lunch else None
            visits, lunch = _compact(st, order, lunch_before, (brk_len, brk_lo, brk_hi), matrices)
            out = next((req.id for req, times, _ in visits if times["late"] > 0), None)
            out = out or (_buffer_victim(visits, buf, conf) if buf.on else None)
            if out is None:
                break
            order = [r for r in order if r.id != out]
        if wants_lunch:
            end = visits[-1][1]["end"] if visits else st.clock
            st.break_start, st.break_end = lunch or (max(brk_lo, end), max(brk_lo, end) + brk_len)
        for req, times, road in visits:
            append(st, req, times, road.minutes, road.km, road.mode)
            owner[req.id] = st.engineer.id

    if settings.option("polish") is not False:
        from .repair import cheapest_insertion

        by_req = {r.id: r for r in requests}
        for req in sorted((r for r in requests if r.id not in owner), key=lambda r: -skip_penalty(r, conf)):
            found = cheapest_insertion(states, req, matrices, by_req, conf)
            if found is not None:
                states[found[0]] = found[1]
                owner[req.id] = found[0]

    timing = {"setup_s": 0.0, "search_s": round(t_search - t0, 3), "budget_s": time_limit_s,
              "pyvrp": 1, "pyvrp_feasible": int(result.is_feasible())}
    plan = finish(dataset, matrices, requests, engineers, states, owner, start=start, plan_id=plan_id,
                  algorithm="solver", timing=timing, buffered=buf.on, conf=conf)
    plan.timing["total_s"] = round(time.perf_counter() - t0, 3)
    return plan, states


def _flag(step, name: str) -> bool:
    value = getattr(step, name)
    return bool(value() if callable(value) else value)


def _index(step) -> int:
    value = step.idx
    return int(value() if callable(value) else value)


def _lunch_place(state: RouteState, order: list[Request], brk_lo: int, matrices: Matrices) -> str | None:
    """Перед каким визитом обед: первый, к началу которого окно обеда уже открыто."""
    from .travel import leg

    clock, position = state.clock, state.position
    for req in order:
        arrive = clock + leg(state.engineer, position, req.id, matrices).minutes
        begin = max(arrive, to_min(req.window_start))
        if begin >= brk_lo:
            return req.id
        clock, position = begin + req.duration_min, req.id
    return None
