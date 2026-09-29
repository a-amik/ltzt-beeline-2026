"""Оценка расстояния между двумя точками.

Пока нет поднятого OSRM (или как запасной вариант при его недоступности)
берём расстояние по прямой — формула гаверсинуса — и умножаем
на коэффициент извилистости дорог 1.3.
"""

import math

EARTH_RADIUS_KM = 6371.0
ROAD_WINDING_FACTOR = 1.3


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Расстояние по прямой между двумя точками на сфере, км."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def road_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Запасная оценка расстояния по дороге: гаверсинус × коэффициент 1.3.

    Используется, когда OSRM недоступен или ещё не поднят.
    """
    return haversine_km(lat1, lon1, lat2, lon2) * ROAD_WINDING_FACTOR
