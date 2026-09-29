"""Зоны участка: город и дальние подучастки — для цены переезда между ними.

Эксперт Билайна, 22.09.2026: выезд в удалённый город допустим, а маршрут
«Москва → Домодедово → Москва → Домодедово» неэффективен. Цена минуты
и километра такой маршрут не останавливает: заявка вовремя стоит тысячи
рублей, лишние 30 км — три с половиной сотни, и решатель гонял московские
бригады в область и обратно ради любого окна.

Зона точки — опорная точка района из допущений (`engineers.anchors`), если
до неё не дальше `zone_radius_km`; иначе город. Соседние города, между
которыми ездят как внутри одного подучастка (Кашира и Ступино), делят зону
полем `zone` опорной точки. Каждый переезд между разными зонами, считая
выезд из точки старта, стоит `economy.zone_cross_rub` — только в цели
поиска, в деньги дня не входит.

Три вещи, которые нельзя ломать:

1. **Цена одна у всех, кто сравнивает планы:** матрица дуг решателя и PyVRP
   (`arcs.group_matrices`), доводка большим соседством (`lns._cost`)
   и выбор среди готовых планов (`objective.key`). Иначе доводка вернёт
   маршрут, от которого решатель ушёл.
2. **Точка без координат зоны не имеет** и переезд к ней не штрафуется:
   штраф за незнание хуже его отсутствия.
3. **Конец маршрута — пустышка:** последний переезд в зону не считается,
   бригада может закончить день там, куда приехала.

Дорогу к аварии и от неё можно освободить от цены (`options.zone_free_emergency`),
но по умолчанию это выключено: замер 28.09.2026 на Юго-востоке показал, что
с освобождением аварии начинаются позже (301 минута от начала смены против 252).
"""

from __future__ import annotations

import math

from .geocode import load_assumptions
from .matrices import Matrices

CITY = "city"


def _anchors() -> tuple[list[dict], float]:
    try:
        conf = load_assumptions().get("engineers", {})
    except FileNotFoundError:
        return [], 0.0
    return list(conf.get("anchors") or []), float(conf.get("zone_radius_km", 12))


def _km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat = math.radians((a[0] + b[0]) / 2)
    dy = (a[0] - b[0]) * 111.32
    dx = (a[1] - b[1]) * 111.32 * math.cos(lat)
    return math.hypot(dx, dy)


def zone_of(lat: float, lon: float, anchors: list[dict] | None = None, radius_km: float | None = None) -> str:
    """Зона точки: ближайшая опорная точка в радиусе или город."""
    if anchors is None or radius_km is None:
        anchors, radius_km = _anchors()
    best, best_km = CITY, radius_km
    for anchor in anchors:
        km = _km((lat, lon), (float(anchor["lat"]), float(anchor["lon"])))
        if km <= best_km:
            best, best_km = str(anchor.get("zone") or anchor["id"]), km
    return best


def _coords(point: str, matrices: Matrices) -> tuple[float, float] | None:
    if point in matrices.coords:
        return matrices.coords[point]
    alias = matrices.aliases.get(point, point)
    if alias in matrices.coords:
        return matrices.coords[alias]
    if alias.startswith("anchor:"):
        lat, lon = alias.removeprefix("anchor:").split(",")
        return float(lat), float(lon)
    return None


def point_zones(points: list[str | None], matrices: Matrices, free: set[str] | None = None) -> list[str | None]:
    """Зоны узлов по их идентификаторам; `None` — у пустышки, у точки без координат и у точки из `free`.

    В наборе из нескольких участков зона несёт и участок: `<участок>|<зона>`.
    Переезд в другой участок — всегда и переезд между зонами, а сверху стоит
    ещё `economy.sector_cross_rub` (`sector_of`, `arcs.group_matrices`).
    """
    anchors, radius = _anchors()
    sectors = getattr(matrices, "sectors", {}) or {}
    out: list[str | None] = []
    for point in points:
        where = _coords(point, matrices) if point is not None and point not in (free or ()) else None
        if not where:
            out.append(None)
            continue
        zone = zone_of(where[0], where[1], anchors, radius)
        sector = sectors.get(point) or sectors.get(matrices.aliases.get(point, point))
        out.append(f"{sector}|{zone}" if sector else zone)
    return out


def sector_of(zone: str | None) -> str | None:
    """Участок из зоны узла; `None` — у набора одного участка и у пустышки."""
    if zone is None or "|" not in zone:
        return None
    return zone.split("|", 1)[0]


def sector_crossings(sectors: list[str | None]) -> int:
    """Сколько раз маршрут (участок старта, затем участки визитов) въезжает в другой участок."""
    return sum(1 for a, b in zip(sectors, sectors[1:]) if a is not None and b is not None and a != b)


def crossings(points: list[str], zones: dict[str, str | None]) -> int:
    """Сколько раз маршрут по точкам (старт, затем визиты) меняет зону."""
    seq = [zones.get(p) for p in points]
    return sum(1 for a, b in zip(seq, seq[1:]) if a is not None and b is not None and a != b)


def free_points(requests) -> set[str]:
    """Заявки, дорога к которым и от которых зон не считает: аварии и «срочно», если так настроено."""
    from . import settings
    from .objective import urgent

    if not settings.option("zone_free_emergency"):
        return set()
    return {r.id for r in requests if urgent(r)}
