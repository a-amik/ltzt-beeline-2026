"""Решатель: заявки по бригадам и порядок визитов — OR-Tools, задача VRPTW, цель в рублях.

Цели по старшинству, как их назвали эксперты 16.09.2026: сначала больше
выполненных заявок, затем меньше исполнителей, затем меньше дороги.
В модели это одна сумма в рублях из тарифной таблицы (`economy.py`):
пропуск заявки стоит её ценность для компании (тысячи), вывод бригады —
день бригады, дорога — минуты инженера и километры автомобиля, работа
сверх нормы дня — бонус по повышенной ставке. Веса не подобраны,
а взяты из допущений, и объяснение плана читается деньгами.

Ограничения решатель не переписывает: навык, транспорт, окно и смена
записаны в `checks.check_visit`, и готовый план обязан проходить те же
проверки, что и базовый вариант (тест `test_solver.py`).

Девять вещей, которые нельзя ломать:

1. **Начало работы — строго внутри окна.** Приехать раньше и ждать можно,
   начать раньше нельзя, начать после конца окна тоже нельзя: такая заявка
   уходит в неназначенные с причиной. Ожидание — переменная `slack`
   измерения времени.
2. **Авария — как можно раньше.** Окно у неё на всю смену, но каждая минута
   после начала смены стоит рублей (мягкая верхняя граница на время начала).
   Так авария встаёт первой, не отменяя жёстких окон у прочих заявок.
3. **Транспорт выбирается на переезд**, а не на день: дуга оценивается
   лучшим видом из набора бригады (`travel.leg`), и вид записывается
   в остановку.
4. **Норма дня — измерение, а не правило.** Нормо-минуты копятся
   по маршруту; сверх нормы каждая минута стоит бонус, а у бригады без
   `extra_load` сверх нормы не бывает вовсе. Предел сверх нормы —
   `extra_limit_min`.
5. **Обед стоит в плане.** Перерыв из допущений (`breaks`) — интервал,
   который решатель ставит между визитами внутри окна обеда; визит
   перерыв не прерывает. Бригаде, у которой день начался позже окна обеда
   (пересчёт вечером), перерыв не ставится.
6. **Замороженное не трогается.** При пересчёте после события бригада
   стартует не из офиса, а из точки, где стоит, и не раньше, чем
   освободится (`states` из `replan.freeze`). Бригада, у которой смена
   уже кончилась, новых заявок не получает.
7. **Один прогон — один ответ.** Время поиска ограничено (`time_limit_s`),
   решение детерминировано при тех же данных: у OR-Tools нет случайности
   в этих стратегиях, а порядок узлов задан входом.
8. **Поиск останавливается, когда перестал улучшать.** Бюджет времени —
   потолок, а не норма: на Востоке лучший план находится за первую секунду,
   и ещё три секунды поиск тратил впустую, потому что признака «дальше
   не будет» у него не было. Теперь он есть: `stall_s` секунд без нового
   лучшего решения — и поиск заканчивается (`FinishCurrentSearch`).
   Ноль выключает остановку. Первое решение и последнее улучшение
   записываются в `plan.timing` — по ним видно, где бюджет лишний.
9. **Дуги считаются матрицей на набор транспорта, а не обратным вызовом
   на бригаду.** Дуга между двумя заявками у бригад с одинаковым набором
   видов одна и та же, и считается она один раз, numpy, из таблиц профилей
   (`arcs.py`); OR-Tools получает готовую матрицу и ходит по ней в C++.
   Обратный вызов Python на каждой дуге давал первое решение на 2 000
   заявок к двенадцатой секунде — позже, чем весь бюджет поиска.

10. **Надёжность окон — второе измерение времени.** Рядом с `Time` (план
   минута в минуту, по нему стоят часы визитов и обед) при включённой
   надёжности идёт `TimeP90`: те же дуги плюс запас на разброс дороги
   и работы (`risk.Buffer`). Окно клиента ограничивает оба: плановое
   начало и приезд с запасом. Ожидание начала окна запас съедает само —
   у измерения есть `slack`, и нижняя граница окна возвращает его к началу
   окна. Свободные окна ограничение не задевает; тесные теряют последнее
   место в цепочке. После поиска маршрут проверяется тем же правилом, что
   у вставки (`insertion.rebuild`): обед решатель в двух измерениях ставит
   порознь, и без проверки визит после обеда мог бы пройти с запасом
   на полчаса меньше настоящего.

Запуск руками: `uv run python -m bee_routing.solver yugo-vostok [секунды] [office|home]`.
"""

from __future__ import annotations

import sys
import time

import numpy as np
from datetime import UTC, datetime

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from . import settings
from .arcs import group_matrices
from .baseline import RouteState, append, new_states
from .checks import check_visit, feasible, to_min
from .economy import late_rate, late_sla, norm_minutes, request_value, skip_penalty, summarize, tariffs
from .explain import explain_assignments, unassigned_reason
from .matrices import Matrices
from .metrics import compute_metrics
from .models import Dataset, Engineer, Plan, Request, Unassigned
from .travel import leg

DAY = 24 * 60
DEFAULT_TIME_LIMIT_S = 4
DEFAULT_STALL_S = 1.5
HOME_ARC_MAX_NODES = 600  # дальше дорога домой — только в доводке: матрица на бригаду не влезает в память
DEFAULT_BREAK = {"duration_min": 30, "earliest": "13:00", "latest": "16:00"}


def break_conf() -> dict:
    """Окно и длина обеда текущего запроса; обед выключен — длина ноль."""
    conf = {**DEFAULT_BREAK, **settings.section("breaks")}
    if not settings.option("breaks"):
        conf["duration_min"] = 0
    return conf


def allowed_vehicles(request: Request, engineers: list[Engineer]) -> list[int]:
    """Кому заявку вообще можно отдать: по навыку и требуемому транспорту."""
    out = []
    for v, eng in enumerate(engineers):
        if request.skill not in eng.skills:
            continue
        if request.transport is not None and request.transport not in eng.transports:
            continue
        out.append(v)
    return out


def solve(
    dataset: Dataset,
    matrices: Matrices,
    *,
    requests: list[Request] | None = None,
    states: dict[str, RouteState] | None = None,
    engineers: list[Engineer] | None = None,
    plan_id: str = "p1",
    algorithm: str = "solver",
    changed: int = 0,
    start: str | None = None,
    time_limit_s: int | None = None,
    strategy: str | None = None,
) -> tuple[Plan, dict[str, RouteState]]:
    """Построить оптимизированный план; вернуть его и состояния маршрутов.

    Утренний план (без готовых состояний) по умолчанию считается портфелем:
    несколько стартовых стратегий параллельно за те же секунды, берётся
    лучший по числу выполненных, потом по итогу дня. Пересчёт хвоста дня
    идёт одной стратегией.
    """
    start = start or str(settings.option("start") or "office")
    morning = states is None  # запас надёжности держит утренний план; днём его держит вставка
    whole = strategy is None  # зовут не из портфеля: доводка большим соседством — здесь, а не в каждом его процессе
    fresh_day = requests is None and states is None and engineers is None
    if fresh_day and strategy is None and dataset.sectors and settings.option("sector_split"):
        return _solve_sectors(dataset, matrices, plan_id=plan_id, start=start, time_limit_s=time_limit_s)
    if fresh_day and strategy is None and settings.option("portfolio"):
        from .portfolio import solve_portfolio

        best = solve_portfolio(dataset, matrices, plan_id=plan_id, start=start, time_limit_s=time_limit_s)
        if best is not None:
            from .insertion import restore_states

            best = _lns(best, dataset, matrices)
            return best, restore_states(best, dataset, matrices)
    if strategy == "PYVRP":
        # Второй решатель портфеля: только утренний план; не по размеру или нет пакета — обычный путь.
        from .pyvrp_plan import solve_pyvrp

        limit = time_limit_s or int(settings.option("time_limit_s") or DEFAULT_TIME_LIMIT_S)
        built = solve_pyvrp(dataset, matrices, plan_id=plan_id, start=start, time_limit_s=limit) if fresh_day else None
        if built is not None:
            return built
        strategy = None
    t0 = time.perf_counter()
    conf = tariffs()
    if morning:
        from .economy import morning_conf

        conf = morning_conf(conf)  # резерв ёмкости под заявки дня держит только утренний план
    brk = break_conf()
    time_limit_s = time_limit_s or int(settings.option("time_limit_s") or DEFAULT_TIME_LIMIT_S)
    stall_raw = settings.option("stall_s")
    stall_s = DEFAULT_STALL_S if stall_raw is None else float(stall_raw)
    engineers = settings.effective_engineers(engineers if engineers is not None else dataset.engineers)
    matrices.adopt(engineers)
    requests = requests if requests is not None else dataset.requests
    states = states if states is not None else new_states(engineers, start)
    by_eng = {eng.id: eng for eng in engineers}
    for eng_id, st in states.items():
        if eng_id in by_eng:
            st.engineer = by_eng[eng_id]
    vehicles = [states[eng.id] for eng in engineers]

    # Узлы: старт каждой бригады (её текущая точка), заявки, общий конец-пустышка.
    n_veh, n_req = len(vehicles), len(requests)
    end_node = n_veh + n_req
    node_point = [st.position for st in vehicles] + [r.id for r in requests] + [None]
    service = [0] * n_veh + [r.duration_min for r in requests] + [0]
    norm = [0] * n_veh + [norm_minutes(r, conf) for r in requests] + [0]

    manager = pywrapcp.RoutingIndexManager(
        end_node + 1, n_veh, list(range(n_veh)), [end_node] * n_veh
    )
    routing = pywrapcp.RoutingModel(manager)
    rub_min, rub_km = int(conf["travel_rub_per_min"]), float(conf["car_rub_per_km"])

    # Дуги — матрицами на набор транспорта: у бригад с одним набором видов
    # переезд между заявками один и тот же, и считается он один раз (`arcs.py`).
    # Матрица регистрируется и тут же отпускается: на 2 000 заявок это
    # пять миллионов чисел, и держать их по числу наборов незачем.
    from .risk import Buffer, buffer

    buf = buffer() if morning else Buffer(0.0, 0.0)
    from .zones import free_points, point_zones

    cross_rub = int(conf.get("zone_cross_rub", 0))
    sector_rub = int(conf.get("sector_cross_rub", 0)) if matrices.sectors else 0
    node_zones = point_zones(node_point, matrices, free_points(requests)) if cross_rub or sector_rub else None
    from .objective import long_leg

    transit_rub = int(conf.get("transit_rub_per_leg", 0))
    leg_cost = long_leg(conf)
    # Дорога домой — дуга в конец маршрута, своя у каждой точки старта. На больших наборах
    # матрица на каждую бригаду не помещается в память, и возврат считают доводка
    # и выбор плана (`objective.extra_rub`).
    home_share = float(conf.get("return_home_share", 0) or 0) if len(node_point) <= HOME_ARC_MAX_NODES else 0.0
    groups: dict[tuple, tuple[int, int, int | None]] = {}
    time_callbacks, p90_callbacks = [], []
    for v, eng in enumerate(engineers):
        home = vehicles[v].start_position if home_share > 0 else None
        key = (tuple(t.value for t in eng.transports), home)
        if key not in groups:
            time_matrix, cost_matrix = group_matrices(eng, node_point, service, matrices, rub_min, rub_km,
                                                      zones=node_zones, cross_rub=cross_rub, sector_rub=sector_rub,
                                                      transit_rub=transit_rub, long_leg=leg_cost,
                                                      home=home, home_share=home_share,
                                                      km_rub=float(conf.get("km_metric_rub", 0) or 0))
            p90_idx = None
            if buf.on:
                # Те же дуги с запасом: доля дороги и доля работы в узле отправления.
                base = np.asarray(time_matrix, dtype=np.int64)
                work = np.asarray(service, dtype=np.int64)[:, None]
                padded = base + np.rint(buf.travel * (base - work) + buf.work * work).astype(np.int64)
                p90_idx = routing.RegisterTransitMatrix(padded.tolist())
                del base, padded
            groups[key] = (routing.RegisterTransitMatrix(cost_matrix), routing.RegisterTransitMatrix(time_matrix), p90_idx)
            del time_matrix, cost_matrix
        cost_idx, time_idx, p90_idx = groups[key]
        routing.SetArcCostEvaluatorOfVehicle(cost_idx, v)
        time_callbacks.append(time_idx)
        p90_callbacks.append(p90_idx)
    routing.AddDimensionWithVehicleTransits(time_callbacks, DAY, 2 * DAY, False, "Time")
    time_dim = routing.GetDimensionOrDie("Time")
    p90_dim = None
    if buf.on:
        routing.AddDimensionWithVehicleTransits(p90_callbacks, DAY, 3 * DAY, False, "TimeP90")
        p90_dim = routing.GetDimensionOrDie("TimeP90")
    from .objective import shift_minutes, weights

    # Порядок целей: добавки старшинства к цене пропуска и к цене бригады (`objective.py`).
    from .objective import skip_extra as skip_extra_of

    skip_base, crew_extra = weights(conf, shift_minutes(engineers), requests)
    routing.SetFixedCostOfAllVehicles(int(conf["engineer_day_rub"]) + crew_extra)
    # Ожидание у двери — `slack` измерения времени. Цена у него — рычаг
    # из тарифов, по умолчанию ноль: простой решатель меняет на езду,
    # и замер этого обмена записан в `economy.py`, п. 3.
    wait_rub = int(round(float(conf.get("wait_rub_per_min", 0))))
    if wait_rub > 0:
        time_dim.SetSlackCostCoefficientForAllVehicles(wait_rub)

    norm_cb = routing.RegisterTransitCallback(lambda i, j: norm[manager.IndexToNode(i)])
    routing.AddDimension(norm_cb, 0, 10 * DAY, True, "Norm")
    norm_dim = routing.GetDimensionOrDie("Norm")
    norm_day = int(conf["norm_day_min"])
    bonus_rate = round(conf["norm_rate_rub_per_min"] * float(conf["bonus_multiplier"]))
    # Выравнивание: разница между самой загруженной и самой свободной бригадой
    # стоит денег, иначе бонусы уходят одной бригаде, а соседи едут домой в обед.
    if settings.option("balance") and int(conf.get("balance_rub_per_min", 0)) > 0:
        norm_dim.SetGlobalSpanCostCoefficient(int(conf["balance_rub_per_min"]))

    # Запас устройств: при пересчёте хвоста дня бригада берёт заявку с устройством,
    # только если оно у неё осталось (`stock.py`). Утром запаса ещё нет — его задаёт сам план.
    from . import stock

    if stock.current() is not None:
        by_req_all = {r.id: r for r in requests}
        for device in stock.ORDER:
            need = [0] * n_veh + [1 if device in r.equipment else 0 for r in requests] + [0]
            if not any(need):
                continue
            caps = []
            for st in vehicles:
                rest = stock.left(st.engineer.id, st.stops, by_req_all) or {}
                caps.append(max(0, rest.get(device, 0)))
            cb = routing.RegisterUnaryTransitCallback(lambda i, need=need: need[manager.IndexToNode(i)])
            routing.AddDimensionWithVehicleCapacity(cb, 0, caps, True, f"Stock-{device}")

    # Обед: интервал внутри окна из допущений; визит его не прерывает.
    visit_transits = [0] * routing.Size()
    for i in range(n_req):
        visit_transits[manager.NodeToIndex(n_veh + i)] = service[n_veh + i]
    brk_len, brk_lo, brk_hi = int(brk["duration_min"]), to_min(brk["earliest"]), to_min(brk["latest"])
    breaks: dict[int, object] = {}

    for v, st in enumerate(vehicles):
        eng = engineers[v]
        start_idx, end_idx = routing.Start(v), routing.End(v)
        time_dim.CumulVar(start_idx).SetRange(st.clock, st.clock)
        time_dim.CumulVar(end_idx).SetRange(0, to_min(eng.shift_end))
        done = sum(norm_minutes(r, conf) for r in _frozen_requests(st, requests))
        norm_dim.CumulVar(start_idx).SetRange(done, done)
        from .economy import norm_limit

        cap = norm_limit(eng, conf)
        if eng.extra_load:
            norm_dim.CumulVar(end_idx).SetRange(0, max(cap, done))
            if cap > norm_day:
                norm_dim.SetCumulVarSoftUpperBound(end_idx, norm_day, bonus_rate)
        else:
            norm_dim.CumulVar(end_idx).SetRange(0, max(cap, done))
        if brk_len and st.clock <= brk_hi and to_min(eng.shift_end) > brk_hi:
            interval = routing.solver().FixedDurationIntervalVar(
                max(brk_lo, st.clock), brk_hi, brk_len, False, f"break-{eng.id}"
            )
            time_dim.SetBreakIntervalsOfVehicle([interval], v, visit_transits)
            breaks[v] = interval
            if p90_dim is not None:
                # Обед в измерении с запасом — свой интервал: шкала там сдвинута
                # на накопленный запас, и стоять он может только позже планового.
                padded_brk = routing.solver().FixedDurationIntervalVar(
                    max(brk_lo, st.clock), brk_hi + 120, brk_len, False, f"break-p90-{eng.id}"
                )
                p90_dim.SetBreakIntervalsOfVehicle([padded_brk], v, visit_transits)
                routing.solver().Add(padded_brk.StartExpr() >= interval.StartExpr())
        if p90_dim is not None:
            p90_dim.CumulVar(start_idx).SetRange(st.clock, st.clock)

    day_start = min((to_min(e.shift_start) for e in engineers), default=0)
    sla_nodes: list[tuple[int, int, int]] = []
    for i, req in enumerate(requests):
        idx = manager.NodeToIndex(n_veh + i)
        ws, we = to_min(req.window_start), to_min(req.window_end)
        time_dim.CumulVar(idx).SetRange(ws, we)
        if p90_dim is not None:
            p90_dim.CumulVar(idx).SetRange(ws, max(we, ws))
        routing.AddDisjunction([idx], skip_penalty(req, conf) + skip_extra_of(req, conf, skip_base))
        # Список бригад ставится прямо в переменную узла: −1 значит «не назначать».
        # Пустой список у SetAllowedVehiclesForIndex значил бы «все», а нужно «никто».
        routing.VehicleVar(idx).SetValues([-1, *allowed_vehicles(req, engineers)])
        if settings.option("emergency_first") and (
            req.skill.value == "emergency" or settings.is_urgent(req)
        ):
            # Ждать аварию начинают не раньше начала смены: окно 0:01—23:59 иначе «опаздывало» бы с полуночи.
            since = max(ws, day_start)
            time_dim.SetCumulVarSoftUpperBound(idx, since, late_rate(req, conf))
            deadline, extra = late_sla(req, conf)
            if extra:
                sla_nodes.append((idx, since + deadline, extra))
    if sla_nodes:
        # Второй излом цены ожидания — после срока SLA сегмента. Мягкая граница у переменной
        # одна, поэтому второй кладётся на копию измерения времени, привязанную к нему
        # равенством в узлах аварий: матрицы те же, новых нет.
        routing.AddDimensionWithVehicleTransits(time_callbacks, DAY, 2 * DAY, False, "TimeSLA")
        sla_dim = routing.GetDimensionOrDie("TimeSLA")
        for idx, bound, extra in sla_nodes:
            routing.solver().Add(sla_dim.CumulVar(idx) == time_dim.CumulVar(idx))
            sla_dim.SetCumulVarSoftUpperBound(idx, bound, extra)
    for v in range(n_veh):
        routing.AddVariableMinimizedByFinalizer(time_dim.CumulVar(routing.Start(v)))
        routing.AddVariableMinimizedByFinalizer(time_dim.CumulVar(routing.End(v)))

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = getattr(
        routing_enums_pb2.FirstSolutionStrategy, strategy or "PATH_CHEAPEST_ARC"
    )
    params.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    params.time_limit.FromSeconds(time_limit_s)
    by_steps = settings.option("search_stop") == "steps"
    if by_steps:
        # Воспроизводимый поиск: стоп по числу решений, а не по часам. Секунды остаются
        # только страховкой от зависания, застой по времени выключен — он тоже зависит от машины.
        params.solution_limit = int(settings.option("solver_solutions") or 300)
        params.time_limit.FromSeconds(max(300, time_limit_s * 30))
        stall_s = 0

    # Остановка по застою: поиск кончается, когда `stall_s` секунд подряд
    # не приносят решения лучше. Время первого решения и последнего
    # улучшения уходят в план — по ним видно, сколько бюджета было лишним.
    t_search = time.perf_counter()
    progress = {"best": None, "first": 0.0, "last": 0.0, "solutions": 0}

    def on_solution() -> None:
        now = time.perf_counter() - t_search
        cost = routing.CostVar().Value()
        progress["solutions"] += 1
        if progress["best"] is None:
            progress["first"] = now
        if progress["best"] is None or cost < progress["best"]:
            progress["best"], progress["last"] = cost, now
        elif stall_s > 0 and now - progress["last"] >= stall_s:
            routing.solver().FinishCurrentSearch()

    routing.AddAtSolutionCallback(on_solution)
    solution = routing.SolveWithParameters(params)
    if progress["solutions"] == 0 and n_req > 0 and whole and not by_steps:
        # Бюджета не хватило даже на первое решение (2 000 заявок — около
        # пяти секунд): OR-Tools отдаёт пустой план, где все заявки сброшены,
        # и обратный вызов решения не видит ни разу. Один повтор с утроенным
        # бюджетом, иначе весь план достался бы полировке вставкой, а она
        # слабее решателя на сотню заявок. В процессе портфеля повтора нет: там
        # стратегия без первого решения просто проигрывает соседям, а ждать её
        # утроенный бюджет значило держать весь портфель — на дне в 1 000
        # заявок SAVINGS так стоила 16 лишних секунд и всё равно ничего не находила.
        params.time_limit.FromSeconds(time_limit_s * 3)
        timing_note = {"retry_budget_s": time_limit_s * 3}
        solution = routing.SolveWithParameters(params)
    else:
        timing_note = {}
    timing = {
        "setup_s": round(t_search - t0, 3),
        "first_solution_s": round(progress["first"], 3),
        "last_improvement_s": round(progress["last"], 3),
        "search_s": round(time.perf_counter() - t_search, 3),
        "solutions": progress["solutions"],
        "budget_s": time_limit_s,
        **timing_note,
    }

    # Порядок визитов и минута обеда — от решателя, часы визитов — свои.
    # Решатель минимизирует часы только у начала и конца маршрута; внутри он
    # волен поставить начало визита в любую минуту допустимого, и ставит:
    # визит с окном 12–14 при приезде в 11:27 выходил на 14:00, а потерянные
    # минуты доставались последнему визиту цепочки — восемь самых рискованных
    # визитов Юго-востока начинались в последние минуты окна. Поэтому маршрут
    # поджимается (`_compact`): приехал — начал, как только окно открыто.
    # Тем же проходом держится запас надёжности: визит, у которого приезд
    # с запасом выходит за окно, покидает маршрут и идёт в полировку наравне
    # с теми, кого решатель не поставил.
    owner: dict[str, str] = {}
    if solution is not None:
        for v, st in enumerate(vehicles):
            brk_at = None
            if v in breaks and solution.PerformedValue(breaks[v]):
                bs = solution.StartValue(breaks[v])
                brk_at = (bs, bs + brk_len)
            order: list[Request] = []
            lunch_before = None
            idx = solution.Value(routing.NextVar(routing.Start(v)))
            while not routing.IsEnd(idx):
                req = requests[manager.IndexToNode(idx) - n_veh]
                if brk_at and lunch_before is None and solution.Value(time_dim.CumulVar(idx)) >= brk_at[1]:
                    lunch_before = req.id
                order.append(req)
                idx = solution.Value(routing.NextVar(idx))
            while True:
                follow = lunch_before if any(r.id == lunch_before for r in order) else None
                visits, lunch = _compact(st, order, follow, (brk_len, brk_lo, brk_hi), matrices)
                late = _buffer_victim(visits, buf, conf) if buf.on else None
                if late is None:
                    break
                order = [r for r in order if r.id != late]
            if brk_at is not None:
                # Обед после последнего визита (или визит перед ним выбыл) — на минуте решателя,
                # но не раньше конца работы.
                end = visits[-1][1]["end"] if visits else st.clock
                st.break_start, st.break_end = lunch or (max(brk_at[0], end), max(brk_at[0], end) + brk_len)
            for req, times, road in visits:
                append(st, req, times, road.minutes, road.km, road.mode)
                owner[req.id] = st.engineer.id

    # Полировка вставкой: решатель за отведённые секунды оставляет заявки,
    # которые дешёвой вставкой ещё встают в чьё-то свободное время в пределах
    # нормы. На Юго-востоке при 2 с поиска это 6 из 15 неназначенных.
    if settings.option("polish") is not False:
        from .repair import cheapest_insertion

        by_req = {r.id: r for r in requests}
        left = sorted((r for r in requests if r.id not in owner),
                      key=lambda r: -skip_penalty(r, conf))
        for req in left:
            found = cheapest_insertion(states, req, matrices, by_req, conf)
            if found is not None:
                eng_id, fresh = found
                states[eng_id] = fresh
                owner[req.id] = eng_id
        vehicles = [states[eng.id] for eng in engineers]

    plan = finish(dataset, matrices, requests, engineers, states, owner, start=start, plan_id=plan_id,
                  algorithm=algorithm, changed=changed, timing=timing, buffered=buf.on, conf=conf)
    plan.timing["total_s"] = round(time.perf_counter() - t0, 3)
    if fresh_day and whole:
        refined = _lns(plan, dataset, matrices)
        if refined is not plan:
            from .insertion import restore_states

            return refined, restore_states(refined, dataset, matrices)
    return plan, states


def _solve_sectors(dataset: Dataset, matrices: Matrices, *, plan_id: str, start: str,
                   time_limit_s: int | None) -> tuple[Plan, dict[str, RouteState]]:
    """Утро «Всей Москвы»: каждый участок — своим решателем, затем общая доводка через границы.

    Одна задача на 205 заявок за те же секунды решается хуже трёх маленьких:
    замер 28.09.2026 — 32 бригады и 1 517 км против 27 бригад и 1 133 км
    у участков порознь. Поэтому участки считаются как раньше, а через границу
    заявку переносит только доводка большим соседством (`options.sector_help_s`),
    и только когда перенос окупает цену въезда в чужой участок
    (`economy.sector_cross_rub`): чужой участок — исключение, а не правило.
    """
    from .insertion import restore_states
    from .loader import sector_part

    all_states: dict[str, RouteState] = {}
    owner: dict[str, str] = {}
    timing: dict[str, float] = {}
    for sector in dataset.sectors:
        part = sector_part(dataset, sector.id)
        plan, part_states = solve(part, matrices, plan_id=plan_id, start=start, time_limit_s=time_limit_s)
        all_states.update(part_states)
        for route in plan.routes:
            for stop in route.stops:
                owner[stop.request_id] = route.engineer_id
        # Участки считаются один за другим: время складывается, бюджет — один на участок.
        for key, value in plan.timing.items():
            if not isinstance(value, (int, float)) or key == "objective_extra_rub":
                continue
            timing[key] = max(timing.get(key, 0), value) if key == "budget_s" else round(timing.get(key, 0) + value, 3)
    engineers = settings.effective_engineers(dataset.engineers)
    plan = finish(dataset, matrices, list(dataset.requests), engineers, all_states, owner,
                  start=start, plan_id=plan_id, timing=timing)
    help_s = float(settings.option("sector_help_s") or 0)
    if help_s > 0:
        from .lns import refine

        plan = refine(plan, dataset, matrices, budget_s=help_s, plan_id=plan_id)
    return plan, restore_states(plan, dataset, matrices)


def _lns(plan: Plan, dataset: Dataset, matrices: Matrices) -> Plan:
    """Доводка утреннего плана большим соседством, если ей отведены секунды (`options.lns_s`)."""
    if settings.option("search_stop") == "steps":
        # Воспроизводимо: число шагов с зерном, в этом же процессе; секунды — страховка.
        steps = int(settings.option("lns_steps") or 0)
        if steps <= 0:
            return plan
        from .lns import refine

        return refine(plan, dataset, matrices, budget_s=3600, max_steps=steps,
                      seed=int(settings.option("search_seed") or 1))
    budget = float(settings.option("lns_s") or 0)
    if budget <= 0:
        return plan
    from .portfolio import BACKGROUND, refine_in_process

    if BACKGROUND.get():
        # Фоновая доводка — в процессе своего пула: сервер в это время отвечает.
        better = refine_in_process(plan, dataset, budget)
        if better is not None:
            return better
    from .lns import refine

    return refine(plan, dataset, matrices, budget_s=budget)


def finish(
    dataset: Dataset, matrices: Matrices, requests: list[Request], engineers: list[Engineer],
    states: dict[str, RouteState], owner: dict[str, str], *, start: str, plan_id: str,
    algorithm: str = "solver", changed: int = 0, timing: dict | None = None, buffered: bool = False,
    conf: dict | None = None,
) -> Plan:
    """Собрать план из готовых маршрутов: причины отказов, показатели, объяснения, экономика, предложения.

    Хвост у решателя, у поиска с большим соседством (`lns.py`) и у PyVRP
    (`hgs.py`) один: маршруты приходят из разных мест, а план обязан
    читаться одинаково — те же причины словами, те же деньги.
    """
    conf = conf or tariffs()
    timing = dict(timing or {})
    # Причина отказа: сперва «мог ли взять хоть кто-то с пустым маршрутом» —
    # навык, транспорт, дорога в окно. Мог — значит дело в загрузке: все,
    # кто умеет, заняты или упёрлись в норму дня, и заявка уходит в предложения.
    unassigned: list[Unassigned] = []
    fresh = new_states(engineers, start)
    for req in requests:
        if req.id in owner:
            continue
        anyone = any(
            feasible(check_visit(eng, req, fresh[eng.id].clock + leg(eng, fresh[eng.id].position, req.id, matrices).minutes,
                                 matrices, prev_id=fresh[eng.id].position))
            for eng in engineers
        )
        if anyone:
            code = "all_busy"
            text = (f"Бригады с навыком заняты в окне {req.window_start}–{req.window_end}; "
                    "можно предложить сверх нормы за бонус")
        else:
            code, text = unassigned_reason(req, engineers, fresh, matrices)
        if buffered and code == "all_busy":
            from .insertion import best_insertion

            by_all = {r.id: r for r in requests}
            tight = any(
                best_insertion(st, req, matrices, by_all, buffered=False) is not None
                for st in states.values()
                if req.skill in st.engineer.skills
            )
            if tight:
                code = "buffer"
                text = (f"Место в маршруте есть только впритык: окно {req.window_start}–{req.window_end} "
                        "не удержать при разбросе дороги и работы. Варианты — другое окно, "
                        "предложение бригаде или надёжность «впритык»")
        unassigned.append(Unassigned(request_id=req.id, reason=text, reason_code=code))

    # Надбавки ступеней у неназначенных — первая строка ранга плана (`portfolio.rank`).
    by_all_req = {r.id: r for r in requests}
    timing["priority_lost_rub"] = sum(
        skip_penalty(by_all_req[u.request_id], conf) - request_value(by_all_req[u.request_id], conf)
        for u in unassigned if u.request_id in by_all_req
    )
    from .objective import extra_rub
    from .zones import free_points, point_zones

    points = sorted({st.start_position for st in states.values()} | set(by_all_req))
    zones = point_zones(points, matrices, free_points(requests))
    timing["objective_extra_rub"] = extra_rub(states, by_all_req, dict(zip(points, zones, strict=True)), conf,
                                              matrices)
    routes = [states[eng.id].to_route() for eng in engineers]
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
        explanations=explain_assignments(requests, engineers, states, owner, matrices),
        timing=timing,
    )
    plan.economy = summarize(plan, dataset, requests, conf)
    from .travel import resolve_day_type

    plan.day_type = resolve_day_type(matrices)
    from .insertion import build_offers

    left = {u.request_id for u in unassigned}
    plan.offers = build_offers(states, [r for r in requests if r.id in left], engineers,
                               matrices, dataset, requests)
    # «Можно предложить сверх нормы» — только если предложить есть кому.
    with_offer = {o.request_id for o in plan.offers if o.candidates}
    for item in plan.unassigned:
        if item.reason_code == "all_busy" and item.request_id not in with_offer:
            req = next(r for r in requests if r.id == item.request_id)
            item.reason = (f"Все бригады с навыком заняты: до конца окна {req.window_start}–{req.window_end} "
                           "никто не освобождается; варианты — другое окно или следующий день")
    return plan


def _compact(state: RouteState, order: list[Request], lunch_before: str | None, brk: tuple[int, int, int],
             matrices: Matrices):
    """Часы визитов в порядке решателя: начало — как только приехали и окно открыто.

    От решателя берётся порядок визитов и **место** обеда — перед каким
    визитом он стоит (`lunch_before`; `None` — после последнего или обеда
    нет). Минута обеда считается заново: началось окно обеда — обед сразу,
    до выезда; не началось — бригада едет, и обедает на месте, в ожидании.
    Оба хода не позже того, что нашёл решатель: его обед стоял между теми же
    визитами, в том же окне и тоже не пересекал работу. Поджатие двигает
    визиты только раньше, поэтому окна и конец смены выдержаны и здесь.

    Возвращает визиты с часами и обед `(начало, конец)` либо `None`.
    """
    brk_len, brk_lo, _ = brk
    out = []
    lunch = None
    clock, position = state.clock, state.position
    for req in order:
        road = leg(state.engineer, position, req.id, matrices)
        ws = to_min(req.window_start)
        if req.id == lunch_before and clock >= brk_lo:
            lunch = (clock, clock + brk_len)
            clock += brk_len
        arrive = clock + road.minutes
        begin = max(arrive, ws)
        if req.id == lunch_before and lunch is None:
            start = max(arrive, brk_lo)
            lunch = (start, start + brk_len)
            begin = max(begin, lunch[1])
        out.append((req, {"arrive": arrive, "start": begin, "end": begin + req.duration_min,
                          "wait": begin - arrive, "late": max(0, begin - to_min(req.window_end))}, road))
        clock, position = begin + req.duration_min, req.id
    return out, lunch


def _buffer_victim(visits, buf, conf) -> str | None:
    """Кого убрать из маршрута ради запаса: наименее важный визит цепочки, а не тот, что вышел за окно.

    Запас накапливается от последнего ожидания окна до визита, у которого
    приезд с запасом вышел за окно; снять напряжение может любой визит этой
    цепочки. Уходит тот, у кого ниже цена пропуска (`economy.skip_penalty`,
    со ступенью приоритета): ремонт раньше подключения, авария — последней.
    При равной цене уходит сам нарушитель.
    """
    late = _first_unbuffered(visits, buf)
    if late is None:
        return None
    chain: list[Request] = []
    for req, times, _ in visits:
        if times["wait"] > 0:
            chain = []  # ожидание окна съело запас: цепочка начинается заново
        chain.append(req)
        if req.id == late:
            break
    return min(chain, key=lambda r: (skip_penalty(r, conf), r.id != late)).id


def _first_unbuffered(visits, buf) -> str | None:
    """Первый визит, у которого приезд с запасом выходит за окно (`risk.Buffer`)."""
    acc = 0.0
    for req, times, road in visits:
        acc += buf.road(road.minutes)
        if times["arrive"] + acc > to_min(req.window_end):
            return req.id
        acc = buf.after_start(acc, times["arrive"], times["start"]) + buf.job(req.duration_min)
    return None


def _frozen_requests(state: RouteState, requests: list[Request]) -> list[Request]:
    """Заявки, уже стоящие в маршруте до решателя (заморожены пересчётом)."""
    ids = {s.request_id for s in state.stops}
    return [r for r in requests if r.id in ids]


def main(argv: list[str] | None = None) -> int:
    """Сравнить решатель с базовым вариантом на регионе из аргумента."""
    from .baseline import build_baseline
    from .control import control_plan
    from .loader import load_dataset, load_matrices

    args = argv if argv is not None else sys.argv[1:]
    dataset_id = args[0] if args else "yugo-vostok"
    limit = int(args[1]) if len(args) > 1 else DEFAULT_TIME_LIMIT_S
    start = args[2] if len(args) > 2 else "office"
    data, matrices = load_dataset(dataset_id), load_matrices(dataset_id)
    base = build_baseline(data, matrices, start=start)[0]
    base.economy = summarize(base, data)
    plans = [
        ("контроль", control_plan(data, matrices)),
        ("базовый", base),
        ("решатель", solve(data, matrices, time_limit_s=limit, start=start)[0]),
    ]
    print(f"{dataset_id}: заявок {len(data.requests)}, бригад {len(data.engineers)}, старт {start}")
    for name, plan in plans:
        m, e = plan.metrics, plan.economy
        breaks = sum(1 for r in plan.routes if r.break_start)
        print(
            f"  {name:9} бригад {m.engineers_used:2}, не назначено {m.unassigned:2}, опозданий {m.late:2}, "
            f"дорога {m.travel_min:4} мин {m.distance_km:6.1f} км, обедов {breaks:2} | "
            f"ценность {e.value_done_rub:6} ₽, упущено {e.value_lost_rub:5} ₽, оклады {e.payroll_rub:6}, "
            f"бонусы {e.bonus_rub:5}, дорога {e.travel_rub:5}, итог {e.net_rub:6} ₽"
        )
    offers = plans[2][1].offers
    for offer in offers[:3]:
        print(f"  предложение {offer.request_id} (дефицит ×{offer.coef}):")
        for c in offer.candidates:
            print(f"    {c.text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
