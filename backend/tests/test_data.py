"""Собранные датасеты обязаны соответствовать контракту знак в знак."""

import re

from bee_routing.loader import dataset_infos
from bee_routing.models import Skill, Transport

from .conftest import REGIONS, needs_data

CLOCK = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


EXTRA_DAY = re.compile(r"^(?P<region>.+)-(?P<day>\d{4}-\d{2}-\d{2})$")


@needs_data
def test_three_regions():
    """Регионов три, и у каждого есть заявки и бригады; дополнительный день — `<регион>-<дата>`."""
    base = {"vostok", "yugo-vostok", "yugocentr"}
    assert base <= set(REGIONS)
    for extra in set(REGIONS) - base:
        match = EXTRA_DAY.match(extra)
        assert match and match["region"] in base, f"{extra}: набор не из трёх регионов"
    for info in dataset_infos():
        assert info.requests_count > 0
        assert info.engineers_count > 0
        match = EXTRA_DAY.match(info.id)
        assert info.date == (match["day"] if match else "2026-08-17")


@needs_data
def test_requests_shape(region):
    """Поля заявки: время «HH:MM», минуты целые, координаты в Москве и области."""
    data, _ = region
    ids = set()
    for req in data.requests:
        assert req.id not in ids, "номера заявок не повторяются"
        ids.add(req.id)
        assert CLOCK.match(req.window_start) and CLOCK.match(req.window_end)
        assert req.window_start < req.window_end
        assert req.duration_min > 0
        assert req.skill in set(Skill)
        assert req.transport is None, "требования транспорта у заявок нет: оборудование везёт любой"
        assert 54.6 <= req.lat <= 56.2 and 36.6 <= req.lon <= 38.6
        assert req.address.startswith(("Москва,", "Московская область,"))


@needs_data
def test_engineers_shape(region):
    """У каждой бригады есть навык, смена и старт в офисе региона."""
    data, _ = region
    assert all(eng.skills for eng in data.engineers)
    full = [eng for eng in data.engineers if len(eng.skills) == 3]
    assert 2 <= len(full) <= 6, "несколько бригад региона умеют всё"
    mixes = set()
    for eng in data.engineers:
        assert eng.transports and eng.transport == eng.transports[0]
        mixes.add(tuple(t.value for t in eng.transports))
        assert eng.shift_start == "10:00" and eng.shift_end == "22:00"
        assert (eng.start.lat, eng.start.lon) == (data.office.lat, data.office.lon)
    assert len(mixes) >= 3, "в регионе встречаются все три набора транспорта"
    # Городские бригады — большей частью без машины (эксперт, 16.09.2026); местные монтажники
    # дальних городов — на машине (Билайн, 19.09.2026), и в долю горожан они не входят.
    from bee_routing import settings

    city = [eng for eng in data.engineers if eng.remote_km < settings.zone_start_km()]
    walkers = [eng for eng in city if Transport.CAR not in eng.transports]
    assert len(walkers) > len(city) / 2, "большинство городских — без машины, как сказал эксперт"
    assert all(Transport.CAR in eng.transports for eng in data.engineers if eng not in city)


@needs_data
def test_events_shape(region):
    """Три сценария: срочная авария, отмена, выбывшая бригада."""
    data, _ = region
    kinds = {event.type: event for event in data.events}
    assert set(kinds) == {"urgent", "cancel", "engineer_off"}
    urgent = kinds["urgent"].request
    assert urgent is not None and urgent.priority.value == "urgent"
    assert urgent.skill is Skill.EMERGENCY and urgent.duration_min == 120
    assert kinds["cancel"].request_id in {req.id for req in data.requests}
    assert kinds["engineer_off"].engineer_id in {eng.id for eng in data.engineers}


@needs_data
def test_matrices_shape(region):
    """Матрицы всех четырёх профилей: квадратные, с нулём на диагонали."""
    data, matrices = region
    points = (1 + len(data.requests) + sum(1 for e in data.events if e.request)
              + sum(1 for e in data.engineers if e.home)
              + len({(e.anchor.lat, e.anchor.lon) for e in data.engineers if e.anchor}))  # опорные точки районов
    for profile in ("car", "bike", "foot", "transit"):
        table = matrices.tables[profile]
        assert len(table["ids"]) == points
        assert table["ids"][0] == "office"
        assert len(table["duration_min"]) == points == len(table["distance_km"])
        for i in range(points):
            assert table["duration_min"][i][i] == 0
            assert len(table["duration_min"][i]) == points
