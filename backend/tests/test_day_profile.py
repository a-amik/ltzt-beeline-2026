"""Профиль часа по типу дня: тип дня по дате, правило дня запроса, уровень дня в решателе."""

from datetime import date

from bee_routing import settings
from bee_routing.day_profile import asked_on_matching_day, day_level, day_type_of, profile
from bee_routing.solver import solve
from bee_routing.travel import hour_factor, leg, resolve_day_type

from .conftest import needs_data


def test_day_type_of():
    assert day_type_of("2026-08-17") == "workday"  # понедельник, день набора заказчика
    assert day_type_of(date(2026, 9, 25)) == "friday"
    assert day_type_of("2026-09-26") == "saturday"
    assert day_type_of("2026-09-27") == "sunday"
    assert day_type_of("2026-11-04") == "holiday"
    assert day_type_of(None) == "workday"


def test_asking_day_rule():
    """Будни — из снятий в будни, выходные — из снятий в выходные."""
    assert asked_on_matching_day({"day_type": "workday", "asked_at": "2026-09-16T12:00:00+03:00"})
    assert not asked_on_matching_day({"day_type": "friday", "asked_at": "2026-09-19T12:00:00+03:00"})
    assert asked_on_matching_day({"day_type": "saturday", "asked_at": "2026-09-19T12:00:00+03:00"})
    assert not asked_on_matching_day({"day_type": "sunday", "asked_at": "2026-09-16T12:00:00+03:00"})


def test_profile_shape():
    """Выходные легче будней, праздник как воскресенье, пятница днём не легче будней."""
    assert day_level("workday") == 1.0
    assert day_level("saturday") < 0.95 and day_level("sunday") < 0.95
    assert all(profile("holiday")[h] == profile("sunday")[h] for h in range(7, 23))
    assert day_level("friday") >= 0.98
    assert set(range(8, 23)) <= set(profile("friday"))


def test_hour_factor_uses_day_type():
    with settings.use({"options": {"hourly_traffic": True}}):
        assert hour_factor("car", 13 * 60, "saturday") < hour_factor("car", 13 * 60, "workday")
        assert hour_factor("car", None, "sunday") == day_level("sunday")
        assert hour_factor("car", None, "workday") == 1.0
        assert hour_factor("foot", 13 * 60, "saturday") == 1.0


@needs_data
def test_day_type_from_dataset_and_override(region):
    """Тип дня берётся из даты набора; настройка его перебивает и доходит до плана."""
    data, matrices = region
    assert resolve_day_type(matrices) == day_type_of(data.date)
    eng = data.engineers[0].model_copy(update={"transports": [], "transport": data.engineers[0].transport})
    car = eng.model_copy(update={"transports": [eng.transport.__class__("car")]})
    a, b = data.requests[0].id, data.requests[-1].id
    with settings.use({"options": {"day_type": "sunday", "hourly_traffic": True, "traffic": True}}):
        assert resolve_day_type(matrices) == "sunday"
        sunday = leg(car, a, b, matrices, 13 * 60).minutes
        plan, _ = solve(data, matrices, plan_id="p", time_limit_s=1, strategy="PATH_CHEAPEST_ARC")
    with settings.use({"options": {"day_type": "workday", "hourly_traffic": True, "traffic": True}}):
        weekday = leg(car, a, b, matrices, 13 * 60).minutes
    assert plan.day_type == "sunday"
    assert sunday <= weekday


def test_transit_follows_timetable_by_hour(monkeypatch):
    """Общественный транспорт получает свой множитель часа, пешком — нет."""
    from bee_routing import day_profile, travel

    monkeypatch.setattr(day_profile, "_dgis_transit", lambda: {"workday": {10: 1.2, 13: 0.9}, "sunday": {10: 0.7}})
    for fn in (day_profile.transit_profile, day_profile.transit_level):
        fn.cache_clear()
    monkeypatch.setattr(travel.settings, "option", lambda name: True)
    try:
        assert travel.hour_factor("transit", 10 * 60, "workday") == 1.2
        assert travel.hour_factor("transit", 13 * 60 + 30, "workday") == 0.9
        assert travel.hour_factor("transit", 10 * 60, "friday") == 1.2, "пятница — будничное расписание"
        assert travel.hour_factor("transit", 10 * 60, "holiday") == 0.7, "праздник — воскресное"
        assert travel.hour_factor("transit", None, "workday") == 1.05
        assert travel.hour_factor("foot", 10 * 60, "workday") == 1.0
    finally:
        for fn in (day_profile.transit_profile, day_profile.transit_level):
            fn.cache_clear()
