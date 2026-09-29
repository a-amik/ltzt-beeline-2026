"""Матрицы «точка → точка» для четырёх профилей движения.

Считает их локальный OSRM (`/table/v1/...?annotations=duration,distance`);
если роутер не поднялся за отведённое время, берётся запасная оценка —
прямая × 1.3 и средняя скорость профиля из допущений. Общественный
транспорт своего роутера не имеет вовсе: расстояния у него пешие,
а время считается по скорости 18 км/ч плюс восемь минут ожидания.

Запуск: `uv run python -m bee_routing.matrices`.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import httpx
import numpy as np

from .distance import road_distance_km
from .geocode import DATA_DIR, load_assumptions

MATRICES_DIR = DATA_DIR / "matrices"
DATASETS_DIR = DATA_DIR / "datasets"
PROFILES = ("car", "bike", "foot", "transit")


class Matrices:
    """Готовые матрицы одного региона: спрашивают дорогу между двумя точками."""

    # Скорости запасной оценки для точек, которых в матрице нет: заявка,
    # пришедшая по ходу дня, в утреннюю матрицу не попала.
    FALLBACK_KMH = {"car": 28.0, "bike": 15.0, "foot": 4.5, "transit": 18.0}
    TRANSIT_WAIT_MIN = 8

    def __init__(self, tables: dict[str, dict]) -> None:
        self.tables = tables
        self.index = {
            profile: {name: i for i, name in enumerate(table["ids"])}
            for profile, table in tables.items()
        }
        self.aliases: dict[str, str] = {}
        self.coords: dict[str, tuple[float, float]] = {}
        # Участок точки в наборе из нескольких участков: заявка — свой, офис, дом
        # и опорная точка бригады — участок бригады. Пусто у набора одного участка.
        self.sectors: dict[str, str] = {}
        self.day_type = "workday"

    def bind(self, dataset) -> None:
        """Запомнить координаты точек региона и тип дня набора (будни, пятница, выходной)."""
        from .day_profile import day_type_of

        self.day_type = day_type_of(getattr(dataset, "date", None))
        self.coords["office"] = (dataset.office.lat, dataset.office.lon)
        for req in dataset.requests:
            self.coords[req.id] = (req.lat, req.lon)
        for event in dataset.events:
            if event.request is not None:
                self.coords[event.request.id] = (event.request.lat, event.request.lon)
        for eng in dataset.engineers:
            if eng.home is not None:
                self.coords[f"home:{eng.id}"] = (eng.home.lat, eng.home.lon)
        for sector in getattr(dataset, "sectors", []) or []:
            self.coords[f"office:{sector.id}"] = (sector.office.lat, sector.office.lon)
            self.sectors[f"office:{sector.id}"] = sector.id
        for req in dataset.requests:
            if req.sector:
                self.sectors[req.id] = req.sector
        for event in dataset.events:
            if event.request is not None and event.request.sector:
                self.sectors[event.request.id] = event.request.sector
        for eng in dataset.engineers:
            if eng.sector:
                self.sectors[f"home:{eng.id}"] = eng.sector
                if eng.anchor is not None:
                    self.sectors[f"anchor:{eng.anchor.lat:.5f},{eng.anchor.lon:.5f}"] = eng.sector

    def register(self, point_id: str, lat: float, lon: float, alias_of: str | None = None) -> None:
        """Новая точка дня: тот же адрес, что у известной (`alias_of`), или своя координата."""
        self.coords[point_id] = (lat, lon)
        if alias_of is not None:
            self.aliases[point_id] = alias_of

    def adopt(self, engineers) -> None:
        """Дома бригад из настроек: адрес, которого нет в матрице, считается запасной оценкой.

        Дом, совпадающий с матричным, остаётся узлом матрицы; чужой адрес
        уводится на синтетическую точку с его координатами, чтобы поиск
        по матрице его не нашёл и взял оценку по прямой.
        """
        for eng in engineers:
            if eng.home is None:
                continue
            key = f"home:{eng.id}"
            known = self.coords.get(key)
            here = (float(eng.home.lat), float(eng.home.lon))
            if known is not None and abs(known[0] - here[0]) < 1e-6 and abs(known[1] - here[1]) < 1e-6:
                self.aliases.pop(key, None)  # дом снова матричный: прежняя подмена снимается
                continue
            if known is None:
                self.coords[key] = here
                continue
            anchor = f"anchor:{here[0]:.5f},{here[1]:.5f}"
            if any(anchor in index for index in self.index.values()):
                # Старт из опорной точки района: она узел матрицы, дорога от неё — по улицам.
                self.aliases[key] = anchor
                continue
            custom = f"{key}@{here[0]:.5f},{here[1]:.5f}"
            self.coords[custom] = here
            self.aliases[key] = custom

    @classmethod
    def load(cls, dataset_id: str, directory: Path | None = None) -> Matrices:
        """Прочитать матрицы региона с диска."""
        directory = directory or MATRICES_DIR
        tables = {}
        for profile in PROFILES:
            path = directory / f"{dataset_id}-{profile}.json"
            if path.exists():
                tables[profile] = json.loads(path.read_text(encoding="utf-8"))
        if not tables:
            raise FileNotFoundError(f"Нет матриц для региона {dataset_id}")
        return cls(tables)

    def arrays(self, profile: str) -> tuple[np.ndarray, np.ndarray]:
        """Таблицы профиля массивами numpy (минуты, километры) — для матриц дуг решателя.

        Считаются при первом обращении и живут с матрицами; профиль, которого
        нет, замещается первым — так же, как в `travel`.
        """
        cache = self.__dict__.setdefault("_arrays", {})
        if profile not in cache:
            table = self.tables.get(profile) or next(iter(self.tables.values()))
            cache[profile] = (
                np.asarray(table["duration_min"], dtype=np.int64),
                np.asarray(table["distance_km"], dtype=np.float64),
            )
        return cache[profile]

    def travel(self, profile: str, origin: str, target: str) -> tuple[int, float]:
        """Дорога между точками: минуты и километры."""
        table = self.tables.get(profile) or next(iter(self.tables.values()))
        idx = self.index.get(profile) or next(iter(self.index.values()))
        origin, target = self.aliases.get(origin, origin), self.aliases.get(target, target)
        if origin == target:
            return 0, 0.0
        if origin not in idx or target not in idx:
            return self._estimate(profile, origin, target)
        i, j = idx[origin], idx[target]
        return int(table["duration_min"][i][j]), float(table["distance_km"][i][j])

    def _estimate(self, profile: str, origin: str, target: str) -> tuple[int, float]:
        """Точки нет в матрице — прямая × 1,3 и средняя скорость профиля."""
        a, b = self.coords.get(origin), self.coords.get(target)
        if a is None or b is None:
            return 0, 0.0
        km = road_distance_km(a[0], a[1], b[0], b[1])
        speed = self.FALLBACK_KMH.get(profile, self.FALLBACK_KMH["car"])
        minutes = km / speed * 60 + (self.TRANSIT_WAIT_MIN if profile == "transit" else 0)
        return max(1, round(minutes)), round(km, 1)

    def source(self) -> str:
        """Откуда взялись числа: osrm или запасная оценка."""
        return next(iter(self.tables.values())).get("source", "unknown")


def points_of(dataset: dict) -> tuple[list[str], list[tuple[float, float]]]:
    """Точки региона: офис, заявки, заявка срочного события и дома бригад."""
    ids = ["office"]
    coords = [(dataset["office"]["lat"], dataset["office"]["lon"])]
    for sector in dataset.get("sectors", []):
        ids.append(f"office:{sector['id']}")
        coords.append((sector["office"]["lat"], sector["office"]["lon"]))
    for req in dataset["requests"]:
        ids.append(req["id"])
        coords.append((req["lat"], req["lon"]))
    for event in dataset.get("events", []):
        extra = event.get("request")
        if extra and extra["id"] not in ids:
            ids.append(extra["id"])
            coords.append((extra["lat"], extra["lon"]))
    for eng in dataset.get("engineers", []):
        home = eng.get("home")
        if home:
            ids.append(f"home:{eng['id']}")
            coords.append((home["lat"], home["lon"]))
    for eng in dataset.get("engineers", []):
        anchor = eng.get("anchor")
        key = f"anchor:{anchor['lat']:.5f},{anchor['lon']:.5f}" if anchor else None
        if key and key not in ids:
            ids.append(key)
            coords.append((anchor["lat"], anchor["lon"]))
    return ids, coords


def wait_for_osrm(base: str, path: str, seconds: int) -> bool:
    """Подождать роутер: он может перезапускаться, поэтому пробуем до упора."""
    deadline = time.monotonic() + seconds
    probe = f"{base}/table/v1/{path}/37.60,55.70;37.70,55.75?annotations=duration"
    while time.monotonic() < deadline:
        try:
            if httpx.get(probe, timeout=10.0).json().get("code") == "Ok":
                return True
        except (httpx.HTTPError, ValueError):
            pass
        time.sleep(5)
    return False


def osrm_table(base: str, path: str, coords: list[tuple[float, float]], chunk: int) -> dict:
    """Спросить у OSRM полную матрицу, при нужде — блоками sources/destinations."""
    size = len(coords)
    joined = ";".join(f"{lon:.6f},{lat:.6f}" for lat, lon in coords)
    durations = [[0.0] * size for _ in range(size)]
    distances = [[0.0] * size for _ in range(size)]
    for start in range(0, size, chunk):
        rows = list(range(start, min(start + chunk, size)))
        resp = httpx.get(
            f"{base}/table/v1/{path}/{joined}",
            params={
                "annotations": "duration,distance",
                "sources": ";".join(str(i) for i in rows),
            },
            timeout=180.0,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != "Ok":
            raise RuntimeError(f"OSRM ответил {data.get('code')}")
        for local, row in enumerate(rows):
            durations[row] = list(data["durations"][local])
            distances[row] = list(data["distances"][local])
    return {"durations": durations, "distances": distances}


def fallback_table(coords: list[tuple[float, float]], speed_kmh: float) -> dict:
    """Запасная матрица: прямая × коэффициент извилистости и средняя скорость."""
    size = len(coords)
    durations = [[0.0] * size for _ in range(size)]
    distances = [[0.0] * size for _ in range(size)]
    for i, (lat1, lon1) in enumerate(coords):
        for j, (lat2, lon2) in enumerate(coords):
            if i == j:
                continue
            km = road_distance_km(lat1, lon1, lat2, lon2)
            distances[i][j] = km * 1000.0
            durations[i][j] = km / speed_kmh * 3600.0
    return {"durations": durations, "distances": distances}


def to_table(ids: list[str], raw: dict, source: str) -> dict:
    """Секунды и метры OSRM → минуты и километры контракта."""
    return {
        "ids": ids,
        "source": source,
        "duration_min": [[round((v or 0) / 60) for v in row] for row in raw["durations"]],
        "distance_km": [[round((v or 0) / 1000, 1) for v in row] for row in raw["distances"]],
    }


def transit_from_foot(foot: dict, conf: dict) -> dict:
    """Общественный транспорт: пешие расстояния, своя скорость и ожидание."""
    speed, wait = conf["transit"]["speed_kmh"], conf["transit"]["wait_min"]
    duration = [
        [0 if i == j else round(km / speed * 60 + wait) for j, km in enumerate(row)]
        for i, row in enumerate(foot["distance_km"])
    ]
    return {
        "ids": foot["ids"],
        "source": foot["source"],
        "duration_min": duration,
        "distance_km": [list(row) for row in foot["distance_km"]],
    }


def build_for(dataset: dict, conf: dict) -> tuple[dict[str, dict], list[str]]:
    """Собрать четыре матрицы региона; вернуть их и заметки о запасных."""
    ids, coords = points_of(dataset)
    osrm, notes, tables = conf["osrm"], [], {}
    for profile in ("car", "bike", "foot"):
        base, path = osrm[profile], osrm["profile_path"][profile]
        if wait_for_osrm(base, path, osrm["wait_seconds"]):
            tables[profile] = to_table(ids, osrm_table(base, path, coords, osrm["chunk"]), "osrm")
        else:
            speed = conf["fallback_matrix"]["speed_kmh"][profile]
            tables[profile] = to_table(ids, fallback_table(coords, speed), "fallback")
            notes.append(f"{dataset['id']}/{profile}: OSRM не ответил, взята запасная матрица")
    tables["transit"] = transit_from_foot(tables["foot"], conf)
    return tables, notes


def main() -> int:
    """Посчитать матрицы всех собранных датасетов."""
    conf = load_assumptions()
    MATRICES_DIR.mkdir(parents=True, exist_ok=True)
    notes: list[str] = []
    for path in sorted(DATASETS_DIR.glob("*.json")):
        dataset = json.loads(path.read_text(encoding="utf-8"))
        tables, region_notes = build_for(dataset, conf)
        notes.extend(region_notes)
        for profile, table in tables.items():
            out = MATRICES_DIR / f"{dataset['id']}-{profile}.json"
            out.write_text(json.dumps(table, ensure_ascii=False) + "\n", encoding="utf-8")
        sources = {profile: table["source"] for profile, table in tables.items()}
        print(f"{dataset['id']}: точек {len(table['ids'])}, источник {sources}")
    print("\n".join(notes) if notes else "Все матрицы посчитаны OSRM.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
