"""Дуги решателя матрицами: время и цена переезда для набора транспорта, разом.

Решатель спрашивает дугу между двумя узлами сотни тысяч раз за поиск.
Пока дугу считал обратный вызов Python, первое решение на 2 000 заявок
появлялось на двенадцатой секунде — при бюджете в четыре: узлов 2 200,
дуг пять миллионов, и каждую первый обход просит через Python. Теперь
дуги для набора транспорта считаются один раз, numpy, из тех же таблиц
профилей, что читает `travel.leg`, и отдаются OR-Tools готовой матрицей
(`RegisterTransitMatrix`): поиск ходит по ней в C++.

Три условия, при которых матрица равна обратному вызову:

1. **Та же арифметика, что в `travel.adjusted`:** минуты OSRM × множитель
   вида × уровень дня + надбавка, не меньше минуты, ноль только там, где
   ноль и в OSRM; час выезда решатель не знает и считает по среднему дню
   (`hour_factor` без часа). Уровень дня есть и у общественного транспорта:
   пропусти его — и решатель, недооценив дорогу, строит опоздания.
2. **Тот же выбор вида:** самый быстрый из набора, при равенстве — первый
   в наборе (`argmin` возвращает первое совпадение, `leg` — первое
   строгое улучшение).
3. **Та же цена:** минуты × ставка минуты инженера, километры × ставка
   километра только у автомобиля, поездка на общественном транспорте —
   по тарифу (`transit_rub_per_leg`). Сверх денег — надбавка за минуты
   переезда дольше порога (усталость, `long_leg_min`) и половина дороги
   домой на дуге в концевой узел (`return_home_share`); обе — только
   в цели поиска, их же считает `objective.extra_rub`.

Узел, которого в таблицах нет (дом бригады с чужим адресом, заявка,
пришедшая по ходу дня), считается через `leg` строкой и столбцом:
таких узлов единицы, и запасная оценка для них та же, что у обратного
вызова. Концевой узел-пустышка стоит нулём по времени; по цене дуга в него —
дорога домой, если дом передан (`home`), иначе ноль.
"""

from __future__ import annotations

import numpy as np

from .matrices import Matrices
from .models import Engineer
from .travel import hour_factor, leg, resolve_day_type, travel_conf


def group_matrices(
    engineer: Engineer, node_point: list[str | None], service: list[int], matrices: Matrices,
    rub_min: int, rub_km: float, *, zones: list[str | None] | None = None, cross_rub: int = 0,
    sector_rub: int = 0, transit_rub: int = 0, long_leg: tuple[int, int] = (0, 0),
    home: str | None = None, home_share: float = 0.0, km_rub: float = 0.0,
) -> tuple[list[list[int]], list[list[int]]]:
    """Матрицы времени (с обслуживанием в узле отправления) и цены для набора транспорта бригады.

    `node_point[i]` — идентификатор точки узла, `None` у концевого узла.
    `zones` — зона каждого узла (`zones.point_zones`): переезд между разными
    зонами дороже на `cross_rub`, только в цене, не во времени. В наборе из
    нескольких участков въезд в другой участок дороже ещё на `sector_rub`
    (`economy.sector_cross_rub`): эта цена входит и в деньги дня.
    """
    size = len(node_point)
    modes = [t.value for t in (engineer.transports or [engineer.transport])]
    conf = travel_conf()
    day_type = resolve_day_type(matrices)
    aliases = matrices.aliases

    # Узлы, которые есть в таблицах всех нужных профилей, считаются блоком.
    known: list[int] = []
    positions: dict[str, list[int]] = {mode: [] for mode in modes}
    for node, point in enumerate(node_point):
        if point is None:
            continue
        name = aliases.get(point, point)
        rows = [matrices.index.get(mode) or next(iter(matrices.index.values())) for mode in modes]
        if all(name in idx for idx in rows):
            known.append(node)
            for mode, idx in zip(modes, rows, strict=True):
                positions[mode].append(idx[name])
    missing = [n for n, p in enumerate(node_point) if p is not None and n not in set(known)]

    minutes = np.zeros((size, size), dtype=np.int64)
    cost = np.zeros((size, size), dtype=np.int64)
    if known:
        block = np.ix_(known, known)
        stacked, kms = [], []
        car_km = None
        for mode in modes:
            dur, dist = matrices.arrays(mode)
            sub = np.ix_(positions[mode], positions[mode])
            raw_min, raw_km = dur[sub], dist[sub]
            factor = conf.get(mode, {}).get("factor", 1.0)
            extra = conf.get(mode, {}).get("extra_min", 0)
            level = hour_factor(mode, None, day_type)
            # Порядок умножений как в `adjusted`: иначе округление расходится на минуту.
            adj = np.maximum(np.rint(raw_min * float(factor) * level + int(extra)).astype(np.int64), 1)
            adj[(raw_min == 0) & (raw_km == 0)] = 0
            stacked.append(adj)
            kms.append(raw_km)
            if mode == "car":
                car_km = raw_km
        best = np.argmin(np.stack(stacked), axis=0)
        best_min = np.min(np.stack(stacked), axis=0)
        block_cost = best_min * rub_min
        if car_km is not None:
            car_idx = modes.index("car")
            block_cost = block_cost + np.where(best == car_idx, np.floor(car_km * rub_km), 0).astype(np.int64)
        if km_rub:
            # Пробег — обязательная метрика ТЗ (п. 2.3) у любого вида транспорта, не только у машины.
            best_km = np.take_along_axis(np.stack(kms), best[None, :, :], axis=0)[0]
            block_cost = block_cost + np.floor(best_km * float(km_rub)).astype(np.int64)
        if transit_rub and "transit" in modes:
            ride = (best == modes.index("transit")) & (best_min > 0)
            block_cost = block_cost + ride.astype(np.int64) * int(transit_rub)
        minutes[block] = best_min
        cost[block] = block_cost

    for a in missing:
        for b in range(size):
            if node_point[b] is None or a == b:
                continue
            for x, y in ((a, b), (b, a)):
                road = leg(engineer, node_point[x], node_point[y], matrices)
                minutes[x, y] = road.minutes
                cost[x, y] = int(road.minutes * rub_min + (road.km * rub_km if road.mode.value == "car" else 0)
                                 + (transit_rub if road.mode.value == "transit" and road.minutes else 0)
                                 + road.km * km_rub)

    leg_min, leg_rate = long_leg
    if leg_rate:
        cost = cost + np.maximum(minutes - int(leg_min), 0) * int(leg_rate)

    if zones is not None and cross_rub:
        known_zone = np.array([z is not None for z in zones])
        names = {z: i for i, z in enumerate(dict.fromkeys(zones))}
        codes = np.array([names[z] for z in zones], dtype=np.int64)
        crossing = (codes[:, None] != codes[None, :]) & known_zone[:, None] & known_zone[None, :]
        cost = cost + crossing.astype(np.int64) * int(cross_rub)

    if zones is not None and sector_rub:
        from .zones import sector_of

        parts = [sector_of(z) for z in zones]
        known_sector = np.array([p is not None for p in parts])
        names = {p: i for i, p in enumerate(dict.fromkeys(parts))}
        codes = np.array([names[p] for p in parts], dtype=np.int64)
        entering = (codes[:, None] != codes[None, :]) & known_sector[:, None] & known_sector[None, :]
        cost = cost + entering.astype(np.int64) * int(sector_rub)

    ends = [n for n, p in enumerate(node_point) if p is None]
    if home is not None and home_share > 0 and ends:
        back = home_column(engineer, node_point, home, matrices, rub_min, rub_km, transit_rub)
        for end in ends:
            cost[:, end] = np.rint(back * float(home_share)).astype(np.int64)

    time = minutes + np.asarray(service, dtype=np.int64)[:, None]
    time[:, [n for n, p in enumerate(node_point) if p is None]] = np.asarray(service, dtype=np.int64)[:, None]
    return time.tolist(), cost.tolist()


def home_column(engineer: Engineer, node_point: list[str | None], home: str, matrices: Matrices,
                rub_min: int, rub_km: float, transit_rub: int = 0) -> np.ndarray:
    """Полная цена дороги из каждого узла домой — в точку, откуда бригада начала день; у пустышек ноль."""
    out = np.zeros(len(node_point), dtype=np.int64)
    for node, point in enumerate(node_point):
        if point is None or point == home:
            continue
        road = leg(engineer, point, home, matrices)
        out[node] = int(road.minutes * rub_min + (road.km * rub_km if road.mode.value == "car" else 0)
                        + (transit_rub if road.mode.value == "transit" and road.minutes else 0))
    return out
