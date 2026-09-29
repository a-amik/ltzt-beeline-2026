"""Генератор нагрузки: регион любого размера, выращенный из настоящего.

У заказчика 205 заявок и 35 бригад на три региона; вопрос жюри — что
станет с решателем при тысяче заявок и сотне бригад. Ответ надо мерить,
а не обещать, и мерить на данных, похожих на настоящие: с теми же окнами,
навыками, длительностями и той же географией, только больше.

Как растёт регион:

1. **Заявка — копия настоящей, поставленная рядом с настоящей точкой.**
   Образец берётся из заявок региона, и от него остаются окно, навык,
   длительность, приоритет, тип; координаты — случайная точка региона
   плюс разброс в `spread_km` (нормальный, по умолчанию 1,5 км). Так
   плотность остаётся плотностью жилых районов, а не равномерным посевом
   по прямоугольнику с заявками посреди леса.
2. **Бригада — копия настоящей по кругу**, с домом рядом с домом образца
   и набором транспорта по тем же долям, что в допущениях
   (`prepare.transport_mix_for`). Три бригады с полным набором навыков
   у региона есть, и круг их сохраняет.
3. **Матрицы — запасная оценка, а не OSRM.** Прямая × 1,3 и средняя
   скорость из допущений, теми же числами, что берёт `matrices.py`, когда
   OSRM не поднят; считаются numpy за секунды даже на трёх тысячах точек.
   Для замера скорости решателя источник дороги не важен; для замера
   качества сравнивают между собой прогоны с одной и той же матрицей.
   Флаг `osrm=True` берёт настоящие таблицы, если OSRM отвечает.
4. **Доли типов — по слову Билайна, а не по образцу.** Письменный ответ
   (п. 11): синтезируя данные, можно брать 40 % локальных, 40 % подключений,
   10 % аварий и 10 % дозаказов. Тип выбирается по этим долям, образец —
   среди заявок этого типа в регионе; нет в регионе такого типа (аварий
   у Югоцентра) — среди заявок всех трёх регионов. `mix="region"` оставляет
   доли настоящего дня.
5. **Случайность посеяна.** Тот же `seed` — тот же регион: прогоны
   сравнимы между собой и повторяемы на другой машине.

Файлы ложатся в `data/scale/` (в git не входят), идентификатор —
`scale-<регион>-r<заявок>-e<бригад>-s<семя>`, и загрузчик находит их
по нему, как настоящие регионы. В списке `/datasets` их нет.

Запуск руками: `uv run python -m bee_routing.loadgen yugo-vostok 1000 100`.
"""

from __future__ import annotations

import json
import math
import random
import sys

import numpy as np

from .distance import EARTH_RADIUS_KM, ROAD_WINDING_FACTOR
from .geocode import load_assumptions
from .loader import SCALE_DATASETS_DIR, SCALE_MATRICES_DIR, load_dataset
from .matrices import osrm_table, points_of, to_table, transit_from_foot, wait_for_osrm
from .prepare import transport_mix_for

KM_PER_DEG_LAT = 111.0


def scale_id(base_id: str, n_requests: int, n_engineers: int, seed: int) -> str:
    """Идентификатор синтетического региона."""
    return f"scale-{base_id}-r{n_requests}-e{n_engineers}-s{seed}"


def _jitter(rng: random.Random, lat: float, lon: float, spread_km: float) -> tuple[float, float]:
    km_per_deg_lon = KM_PER_DEG_LAT * math.cos(math.radians(lat))
    return (
        round(lat + rng.gauss(0, spread_km) / KM_PER_DEG_LAT, 6),
        round(lon + rng.gauss(0, spread_km) / km_per_deg_lon, 6),
    )


# Письменный ответ Билайна, п. 11: доли типов для синтезированных данных.
EXPERT_MIX = {"local": 0.4, "connect": 0.4, "accident": 0.1, "upsell": 0.1}


def kind_of(request: dict) -> str:
    """Тип заявки в долях Билайна: локальная, подключение, авария, дозаказ."""
    if request["type_bk"] == "Дозаказ":
        return "upsell"
    if request["type_bk"] == "Глобальная проблема":
        return "accident" if request["type_hd"] == "Авария" else "local"
    return "connect" if request["type_bk"] == "Подключение" else "local"


def _pools(base_id: str, templates: list[dict]) -> dict[str, list[dict]]:
    """Образцы по типу: из региона, а недостающий тип — из всех настоящих регионов."""
    from .loader import dataset_ids

    pools: dict[str, list[dict]] = {k: [] for k in EXPERT_MIX}
    for tpl in templates:
        pools[kind_of(tpl)].append(tpl)
    for kind, pool in pools.items():
        if pool:
            continue
        for other in dataset_ids():
            if other == base_id or other.startswith("scale-"):
                continue
            pool.extend(r.model_dump(mode="json") for r in load_dataset(other).requests
                        if kind_of(r.model_dump(mode="json")) == kind)
    return pools


def synthesize(base_id: str, n_requests: int, n_engineers: int, *, seed: int = 1,
               spread_km: float = 1.5, mix: str = "expert") -> dict:
    """Регион из `n_requests` заявок и `n_engineers` бригад по образцу настоящего.

    `mix="expert"` — доли типов по письменному ответу Билайна (40/40/10/10),
    `mix="region"` — доли настоящего дня.
    """
    base = load_dataset(base_id)
    rng = random.Random(seed)
    conf = load_assumptions()
    anchors = [(r.lat, r.lon) for r in base.requests] + [(base.office.lat, base.office.lon)]
    templates = [r.model_dump(mode="json") for r in base.requests]
    pools = _pools(base_id, templates) if mix == "expert" else {}
    kinds, weights = list(EXPERT_MIX), list(EXPERT_MIX.values())

    requests = []
    for i in range(n_requests):
        if pools:
            kind = rng.choices(kinds, weights)[0]
            tpl = dict(rng.choice(pools[kind] or templates))
        else:
            tpl = dict(rng.choice(templates))
        lat, lon = _jitter(rng, *rng.choice(anchors), spread_km)
        tpl.update(
            id=f"s{i + 1:05d}",
            address=f"Синтетический адрес {i + 1}, {tpl['district']}",
            lat=lat,
            lon=lon,
            geo_quality="house",
        )
        requests.append(tpl)

    engineers = []
    mix = conf["engineers"]["transport_mix"]
    for i in range(n_engineers):
        tpl = base.engineers[i % len(base.engineers)]
        home = tpl.home or base.office
        transports = transport_mix_for(i, n_engineers, mix)
        h_lat, h_lon = _jitter(rng, home.lat, home.lon, 2.0)
        engineers.append(
            {
                "id": f"e{i + 1:03d}",
                "name": f"Бригада {i + 1}",
                "start": {"lat": base.office.lat, "lon": base.office.lon},
                "shift_start": tpl.shift_start,
                "shift_end": tpl.shift_end,
                "skills": [s.value for s in tpl.skills],
                "home": {"lat": h_lat, "lon": h_lon},
                "extra_load": tpl.extra_load,
                "extra_limit_min": tpl.extra_limit_min,
                "transport": transports[0],
                "transports": transports,
            }
        )

    return {
        "id": scale_id(base_id, n_requests, n_engineers, seed),
        "name": f"{base.name}, нагрузка {n_requests}×{n_engineers}",
        "date": base.date,
        "office": base.office.model_dump(mode="json"),
        "requests": requests,
        "engineers": engineers,
        "events": [],
        "control": [],
    }


def fallback_tables(ids: list[str], coords: list[tuple[float, float]], conf: dict) -> dict[str, dict]:
    """Четыре матрицы запасной оценкой, векторно: прямая × 1,3 и скорость профиля."""
    lat = np.radians(np.array([c[0] for c in coords], dtype=np.float64))
    lon = np.radians(np.array([c[1] for c in coords], dtype=np.float64))
    dphi = lat[:, None] - lat[None, :]
    dlmb = lon[:, None] - lon[None, :]
    a = np.sin(dphi / 2) ** 2 + np.cos(lat)[:, None] * np.cos(lat)[None, :] * np.sin(dlmb / 2) ** 2
    km = 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(a)) * ROAD_WINDING_FACTOR
    np.fill_diagonal(km, 0.0)
    distance_km = np.round(km, 1).tolist()
    speeds = conf["fallback_matrix"]["speed_kmh"]
    tables = {}
    for profile in ("car", "bike", "foot"):
        minutes = np.round(km / float(speeds[profile]) * 60).astype(int)
        np.fill_diagonal(minutes, 0)
        tables[profile] = {
            "ids": ids,
            "source": "fallback",
            "duration_min": minutes.tolist(),
            "distance_km": distance_km,
        }
    tables["transit"] = transit_from_foot(tables["foot"], conf)
    return tables


def build_matrices(dataset: dict, *, osrm: bool = False) -> dict[str, dict]:
    """Матрицы синтетического региона: OSRM по флагу, иначе запасная оценка."""
    conf = load_assumptions()
    ids, coords = points_of(dataset)
    if osrm:
        cfg = conf["osrm"]
        tables = {}
        for profile in ("car", "bike", "foot"):
            base, path = cfg[profile], cfg["profile_path"][profile]
            if not wait_for_osrm(base, path, 5):
                return fallback_tables(ids, coords, conf)
            tables[profile] = to_table(ids, osrm_table(base, path, coords, cfg["chunk"]), "osrm")
        tables["transit"] = transit_from_foot(tables["foot"], conf)
        return tables
    return fallback_tables(ids, coords, conf)


def ensure(base_id: str, n_requests: int, n_engineers: int, *, seed: int = 1, osrm: bool = False,
           spread_km: float = 1.5, force: bool = False) -> str:
    """Собрать регион и матрицы на диск, если их ещё нет; вернуть идентификатор."""
    dataset_id = scale_id(base_id, n_requests, n_engineers, seed)
    path = SCALE_DATASETS_DIR / f"{dataset_id}.json"
    if path.exists() and not force and all(
        (SCALE_MATRICES_DIR / f"{dataset_id}-{p}.json").exists() for p in ("car", "bike", "foot", "transit")
    ):
        return dataset_id
    SCALE_DATASETS_DIR.mkdir(parents=True, exist_ok=True)
    SCALE_MATRICES_DIR.mkdir(parents=True, exist_ok=True)
    dataset = synthesize(base_id, n_requests, n_engineers, seed=seed, spread_km=spread_km)
    path.write_text(json.dumps(dataset, ensure_ascii=False) + "\n", encoding="utf-8")
    for profile, table in build_matrices(dataset, osrm=osrm).items():
        out = SCALE_MATRICES_DIR / f"{dataset_id}-{profile}.json"
        out.write_text(json.dumps(table) + "\n", encoding="utf-8")
    load_dataset.cache_clear()
    from .loader import load_matrices

    load_matrices.cache_clear()
    return dataset_id


def main(argv: list[str] | None = None) -> int:
    """`python -m bee_routing.loadgen <регион> <заявок> <бригад> [семя] [--osrm]`."""
    args = [a for a in (argv or sys.argv[1:]) if not a.startswith("--")]
    flags = {a for a in (argv or sys.argv[1:]) if a.startswith("--")}
    if len(args) < 3:
        print(main.__doc__)
        return 2
    base_id, n_req, n_eng = args[0], int(args[1]), int(args[2])
    seed = int(args[3]) if len(args) > 3 else 1
    dataset_id = ensure(base_id, n_req, n_eng, seed=seed, osrm="--osrm" in flags, force="--force" in flags)
    print(dataset_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
