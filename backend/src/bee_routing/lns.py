"""Поиск с большим соседством: доводка готового плана минутами, а не секундами.

Зачем. Решатель OR-Tools с направляемым локальным поиском двигает визиты
по одному, и за шестнадцать секунд доводки уходит недалеко от того, что
нашёл за четыре. У готовых планов (`ready.py`) времени больше: утренний
план лежит посчитанным до того, как его спросили. Это время тратится
здесь — план ломается и чинится кусками.

Один шаг:

1. **Разрушение.** Из маршрутов вынимается 8—25 % визитов одним из четырёх
   способов: случайно; худшие по цене (длинная дорога до визита и ожидание
   перед ним); связанные — соседи одного визита по месту и по часу начала
   (по Шоу): район на пару часов вынимается целиком и перекладывается заново;
   и маршрут целиком — все визиты одной из самых лёгких бригад, которая
   на время починки закрыта. Последний способ нужен там, где заняты не все:
   на Востоке и Югоцентре три первых за 15 000 шагов не нашли ничего —
   вставка возвращала визиты на прежние места, а выигрыш лежал в закрытой
   бригаде (7 000 ₽ в день). К вынутым добавляются неназначенные — у них
   появляется шанс встать.
2. **Починка.** Вынутое возвращается дешёвой вставкой (`repair.cheapest_insertion`):
   теми же проверками навыка, окна, нормы дня и запаса надёжности, что
   у всего остального. Сперва — бригадам, которые уже в работе, и только
   если места нет — свободным: вставка меряет добавку дороги, а день новой
   бригады стоит дороже любого крюка. Порядок возврата — по ценности заявки
   либо случайный.
3. **Принятие.** Мерка — сумма из цели решателя: цена пропуска со ступенью
   приоритета (авария → подключение → ремонт и дозаказ) плюс затраты дня. Лучше рекорда — новый рекорд; чуть хуже
   (в пределах порога, который сжимается к концу бюджета) — принимается как
   текущее состояние, чтобы выйти из ямы; иначе шаг отменяется.

Три вещи, которые нельзя ломать:

1. **Ничего своего в проверках.** Визит встаёт в маршрут только через
   `insertion.rebuild`: LNS не может построить план, который вставка или
   пересчёт дня сочли бы недопустимым.
2. **Случайность посеяна.** Зерно — регион и номер прогона: тот же план,
   тот же бюджет шагов — тот же ответ. Бюджет задаётся секундами, поэтому
   на разных машинах шагов выйдет разное число; воспроизводимость — в тесте,
   по числу шагов.
3. **Замороженное не трогается.** Вынимаются только подвижные визиты
   (`insertion.movable`); обед остаётся на своём месте — перестройка его держит.
"""

from __future__ import annotations

import hashlib
import math
import random
import time

from . import settings
from .baseline import RouteState
from .checks import to_min
from .economy import bonus_for, norm_minutes, sector_entries, skip_penalty, travel_cost
from .insertion import movable, rebuild
from .matrices import Matrices
from .models import Dataset, Engineer, Plan, Request
from .repair import cheapest_insertion

REMOVE_SHARE = (0.08, 0.25)
START_TOLERANCE = 0.004  # доля от цены рекорда, которую разрешено проиграть в начале


_weights_cache: dict = {}


def _weights(conf: dict, by_id: dict[str, Request]) -> tuple[int, int]:
    """Добавки старшинства на прогон доводки: граница ожидания аварий считается один раз."""
    from .objective import weights

    key = (id(conf), id(by_id), len(by_id))
    if key not in _weights_cache:
        _weights_cache.clear()
        _weights_cache[key] = weights(conf, requests=list(by_id.values()))
    return _weights_cache[key]


def _cost(states: dict[str, RouteState], by_id: dict[str, Request], conf: dict,
          zones: dict[str, str | None] | None = None, matrices: Matrices | None = None) -> int:
    """Затраты дня в рублях по маршрутам: оклады, бонусы, дорога — и то, что цель решателя
    считает сверх денег: ожидание аварии и переезды между зонами (`objective.extra_rub`)."""
    from .objective import extra_rub

    total = extra_rub(states, by_id, zones or {}, conf, matrices)
    skip_extra, crew_extra = _weights(conf, by_id)
    sector_rate = int(conf.get("sector_cross_rub", 0))
    day, norm_day = int(conf["engineer_day_rub"]) + crew_extra, int(conf["norm_day_min"])
    for st in states.values():
        if not st.stops:
            continue
        route = st.to_route()
        norm = sum(norm_minutes(by_id[s.request_id], conf) for s in st.stops if s.request_id in by_id)
        total += day + travel_cost(route, conf) + bonus_for(max(0, norm - norm_day), st.engineer, conf)
        # Въезды в чужой участок — в деньгах дня (`economy.summarize`), значит и в затратах доводки.
        total += sector_entries(st.engineer, [s.request_id for s in st.stops], by_id) * sector_rate
    return total


def _score(states: dict[str, RouteState], pool: dict[str, Request], by_id: dict[str, Request], conf: dict,
           zones: dict[str, str | None] | None = None, matrices: Matrices | None = None):
    """Мерка плана — та же сумма, что в цели решателя: цена пропуска плюс затраты дня.

    Цена пропуска несёт ступень приоритета (`economy.skip_penalty`): авария →
    подключение → ремонт и дозаказ, письменный ответ Билайна, п. 15. Считать
    неназначенные штуками нельзя: при нехватке бригад обмен аварии на ремонт
    число не меняет, а приоритет ломает. Первое число — для статистики.
    """
    from .objective import skip_extra, weights

    base = _weights(conf, by_id)[0]
    lost = sum(skip_penalty(r, conf) + skip_extra(r, conf, base) for r in pool.values())
    return (lost + _cost(states, by_id, conf, zones, matrices), len(pool))


def _pick_random(rng, placed, k, **_):
    return rng.sample(placed, k)


def _pick_worst(rng, placed, k, *, stops, **_):
    """Дорогие визиты: дорога до них и ожидание перед ними; с долей случайности."""
    ranked = sorted(placed, key=lambda rid: -(stops[rid].travel_min + stops[rid].wait_min) * rng.uniform(0.7, 1.3))
    return ranked[:k]


def _pick_related(rng, placed, k, *, by_id, stops, **_):
    """Соседи случайного визита по месту и часу начала."""
    seed = by_id[rng.choice(placed)]
    t0 = to_min(stops[seed.id].start)

    def far(rid: str) -> float:
        r = by_id[rid]
        km = math.hypot((r.lat - seed.lat) * 111.0, (r.lon - seed.lon) * 63.0)
        return km + abs(to_min(stops[rid].start) - t0) / 20.0  # 20 минут разницы стоят километра

    return sorted(placed, key=far)[:k]


def _pick_route(rng, placed, k, *, routes, **_):
    """Все визиты одной из самых лёгких бригад; она закрыта на время починки."""
    light = sorted(routes, key=lambda item: len(item[1]))[: max(1, len(routes) // 3)]
    eng_id, visits = rng.choice(light)
    return visits, eng_id


OPERATORS = (_pick_related, _pick_related, _pick_worst, _pick_random, _pick_route)


def improve(
    states: dict[str, RouteState], unassigned: list[Request], requests: list[Request], matrices: Matrices,
    dataset: Dataset, *, budget_s: float, max_steps: int | None = None, seed: int = 1,
) -> tuple[dict[str, RouteState], list[Request], dict]:
    """Довести маршруты; вернуть лучшие маршруты, неназначенные и статистику поиска."""
    from .economy import morning_conf

    conf = morning_conf()  # доводят утренний план: резерв ёмкости держится и здесь
    by_id = {r.id: r for r in requests}
    digest = hashlib.sha1(f"{dataset.id}|{seed}".encode()).hexdigest()
    rng = random.Random(int(digest[:8], 16))

    from .zones import free_points, point_zones

    points = sorted({st.start_position for st in states.values()} | set(by_id))
    zones = dict(zip(points, point_zones(points, matrices, free_points(requests)), strict=True))
    current = dict(states)
    pool = {r.id: r for r in unassigned}
    best, best_pool = dict(current), dict(pool)
    best_score = current_score = _score(current, pool, by_id, conf, zones, matrices)
    start_score = best_score
    best_cost = _cost(best, by_id, conf, zones, matrices)  # порог принятия — доля затрат дня, без надбавок ступеней
    t0 = time.perf_counter()
    steps = accepted = improved = 0
    last_gain = 0.0

    while (time.perf_counter() - t0) < budget_s and (max_steps is None or steps < max_steps):
        steps += 1
        stops = {s.request_id: s for st in current.values() for s in st.stops[st.frozen:]}
        placed = [rid for rid in stops if rid in by_id]
        if not placed:
            break
        share = rng.uniform(*REMOVE_SHARE)
        k = max(2, min(len(placed), round(len(placed) * share)))
        routes = [(eng_id, [s.request_id for s in st.stops[st.frozen:] if s.request_id in by_id])
                  for eng_id, st in current.items() if st.stops and not st.frozen]
        chosen = rng.choice(OPERATORS)
        closed = None
        if chosen is _pick_route:
            if len(routes) < 2:
                continue
            picked, closed = chosen(rng, placed, k, routes=routes)
            picked = dict.fromkeys(picked)
        else:
            # Порядок вынутых — порядок выбора, а не хеша: обход множества строк меняется
            # от процесса к процессу, и с тем же зерном доводка шла бы по-разному.
            picked = dict.fromkeys(chosen(rng, placed, k, by_id=by_id, stops=stops))

        trial = dict(current)
        ok = True
        for eng_id, st in current.items():
            tail = movable(st, by_id)
            if not any(r.id in picked for r in tail):
                continue
            fresh, _ = rebuild(st, [r for r in tail if r.id not in picked], matrices, guard=set())
            if fresh is None:
                ok = False
                break
            trial[eng_id] = fresh
        if not ok:
            continue

        queue = [by_id[rid] for rid in picked] + list(pool.values())
        if rng.random() < 0.5:
            rng.shuffle(queue)
        else:
            queue.sort(key=lambda r: -skip_penalty(r, conf))
        trial_pool: dict[str, Request] = {}
        for req in queue:
            busy = {e: st for e, st in trial.items() if st.stops and e != closed}
            found = cheapest_insertion(busy, req, matrices, by_id, conf) if busy else None
            if found is None:
                found = cheapest_insertion({e: st for e, st in trial.items() if e != closed},
                                           req, matrices, by_id, conf)
            if found is None:
                trial_pool[req.id] = req
            else:
                trial[found[0]] = found[1]

        score = _score(trial, trial_pool, by_id, conf, zones, matrices)
        progress = min(1.0, (time.perf_counter() - t0) / max(budget_s, 1e-6))
        slack = best_cost * START_TOLERANCE * (1.0 - progress)
        if score < best_score:
            best, best_pool, best_score = dict(trial), dict(trial_pool), score
            best_cost = _cost(best, by_id, conf, zones, matrices)
            improved += 1
            last_gain = time.perf_counter() - t0
        if score < current_score or score[0] <= best_score[0] + slack:
            current, pool, current_score = trial, trial_pool, score
            accepted += 1

    stats = {
        "lns_steps": steps, "lns_accepted": accepted, "lns_improved": improved,
        "lns_s": round(time.perf_counter() - t0, 2), "lns_last_gain_s": round(last_gain, 2),
        "lns_cost_before": start_score[0], "lns_cost_after": best_score[0],
        "lns_unassigned_before": start_score[1], "lns_unassigned_after": best_score[1],
    }
    return best, list(best_pool.values()), stats


def refine(plan: Plan, dataset: Dataset, matrices: Matrices, *, budget_s: float, plan_id: str | None = None,
           max_steps: int | None = None, seed: int = 1) -> Plan:
    """Довести готовый план поиском с большим соседством; хуже не станет — вернётся исходный."""
    from .insertion import restore_states
    from .replan import known_requests
    from .risk import buffer
    from .solver import finish

    engineers: list[Engineer] = settings.effective_engineers(dataset.engineers)
    matrices.adopt(engineers)
    requests = known_requests(plan, dataset)
    by_id = {r.id: r for r in requests}
    states = restore_states(plan, dataset, matrices)
    # Бригады — с настройками запроса: запрет работы сверх нормы и набор транспорта
    # живут в них, а не в наборе; без этого доводка ставила бы сверх нормы тем, кому запрещено.
    for eng in engineers:
        if eng.id in states:
            states[eng.id].engineer = eng
    waiting = [by_id[u.request_id] for u in plan.unassigned if u.request_id in by_id]
    best, left, stats = improve(states, waiting, requests, matrices, dataset,
                                budget_s=budget_s, max_steps=max_steps, seed=seed)
    if not stats["lns_improved"]:
        plan.timing = {**plan.timing, **stats}
        return plan
    for eng in engineers:
        best.setdefault(eng.id, states[eng.id])
    owner = {s.request_id: eng_id for eng_id, st in best.items() for s in st.stops}
    skip = {d.request_id for d in plan.deferred}
    built = finish(dataset, matrices, [r for r in requests if r.id not in skip], engineers, best, owner,
                   start=plan.start, plan_id=plan_id or plan.id, algorithm=plan.algorithm,
                   timing={**plan.timing, **stats}, buffered=buffer().on)
    built.settings, built.history, built.deferred = plan.settings, plan.history, plan.deferred
    built.day_type = plan.day_type
    return built
