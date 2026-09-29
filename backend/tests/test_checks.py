"""Проверки ограничений на игрушечных данных: каждая падает по своей причине."""

import pytest

from bee_routing.checks import check_visit, feasible, first_failure, to_min, visit_times
from bee_routing.matrices import Matrices
from bee_routing.models import Engineer, Point, Request

IDS = ["office", "r1"]


def toy_matrices(minutes: int = 20, km: float = 8.0) -> Matrices:
    """Две точки и одна дорога между ними — для всех профилей одна и та же."""
    table = {
        "ids": IDS,
        "source": "toy",
        "duration_min": [[0, minutes], [minutes, 0]],
        "distance_km": [[0.0, km], [km, 0.0]],
    }
    return Matrices({profile: dict(table) for profile in ("car", "bike", "foot", "transit")})


def engineer(**kwargs) -> Engineer:
    """Бригада по умолчанию: все навыки, машина, смена 10:00–22:00."""
    base = {
        "id": "e1", "name": "Иванов", "start": Point(lat=55.7, lon=37.6),
        "shift_start": "10:00", "shift_end": "22:00",
        "skills": ["local", "connect", "emergency"], "transport": "car",
    }
    return Engineer(**{**base, **kwargs})


def request(**kwargs) -> Request:
    """Заявка по умолчанию: подключение на 90 минут в окне 12:00–14:00."""
    base = {
        "id": "r1", "type_bk": "Подключение", "type_hd": "Конвергенция абонента",
        "address": "Москва, Окская улица, 5", "district": "Кузьминки",
        "lat": 55.71, "lon": 37.75, "geo_quality": "house", "duration_min": 90,
        "window_start": "12:00", "window_end": "14:00", "priority": "normal",
        "skill": "connect", "transport": None,
    }
    return Request(**{**base, **kwargs})


def test_all_ok():
    """Всё сходится — пять проверок, все зелёные."""
    checks = check_visit(engineer(), request(), to_min("12:10"), toy_matrices())
    assert [c.kind for c in checks] == ["skill", "transport", "window", "shift", "distance"]
    assert feasible(checks) and first_failure(checks) is None
    assert "8,0 км" in checks[-1].text


def test_no_skill():
    """Нет навыка — отказ с кодом no_skill и внятным текстом."""
    checks = check_visit(engineer(skills=["local"]), request(), to_min("12:10"), toy_matrices())
    assert not feasible(checks)
    assert first_failure(checks) == "no_skill"
    assert "подключение и дозаказы" in checks[0].text


def test_no_transport():
    """Заявке нужна машина, а бригада пешая."""
    checks = check_visit(
        engineer(transport="foot"), request(transport="car"), to_min("12:10"), toy_matrices()
    )
    assert first_failure(checks) == "no_transport"


def test_window_closed():
    """Приезд после конца окна — опоздание, назначать нельзя."""
    checks = check_visit(engineer(), request(), to_min("14:30"), toy_matrices())
    assert first_failure(checks) == "no_fit_window"
    assert "30 мин" in checks[2].text


def test_shift_overflow():
    """Работа кончилась бы после смены."""
    late = request(window_start="20:00", window_end="21:30", duration_min=120)
    checks = check_visit(engineer(), late, to_min("21:00"), toy_matrices())
    assert first_failure(checks) == "no_fit_shift"


def test_wait_before_window():
    """Приехал раньше окна — ждёт, а не работает."""
    times = visit_times(request(), to_min("11:30"))
    assert times["wait"] == 30
    assert times["start"] == to_min("12:00")
    assert times["end"] == to_min("13:30")
    assert times["late"] == 0


@pytest.mark.parametrize("clock", ["00:00", "10:00", "23:59"])
def test_clock_roundtrip(clock):
    """Минуты и «HH:MM» переводятся друг в друга без потерь."""
    from bee_routing.checks import to_clock

    assert to_clock(to_min(clock)) == clock
