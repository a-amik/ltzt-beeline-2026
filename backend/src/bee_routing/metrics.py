"""Метрики плана по контракту: бригады, километры, дорога, отказы, опоздания."""

from __future__ import annotations

from .models import Metrics, Route, Unassigned


def compute_metrics(
    routes: list[Route], unassigned: list[Unassigned], *, changed: int = 0
) -> Metrics:
    """Свести маршруты в шесть чисел витрины."""
    used = [route for route in routes if route.stops]
    return Metrics(
        engineers_used=len(used),
        distance_km=round(sum(route.distance_km for route in routes), 1),
        travel_min=sum(route.travel_min for route in routes),
        unassigned=len(unassigned),
        late=sum(1 for route in routes for stop in route.stops if stop.late_min > 0),
        changed_requests=changed,
    )
