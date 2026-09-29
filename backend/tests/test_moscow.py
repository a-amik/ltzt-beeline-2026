"""«Вся Москва»: три участка одним набором, свой офис у бригады, цена въезда в чужой участок."""

from bee_routing import settings
from bee_routing.baseline import new_states, start_point
from bee_routing.economy import sector_entries, tariffs
from bee_routing.loader import load_dataset, load_matrices, sector_part
from bee_routing.moscow import MOSCOW_ID
from bee_routing.repair import cheapest_insertion


def test_moscow_joins_sectors():
    """Набор складывается из участков как есть; совпадающие идентификаторы разведены."""
    data = load_dataset(MOSCOW_ID)
    assert {s.id for s in data.sectors} == {"vostok", "yugo-vostok", "yugocentr"}
    parts = [load_dataset(s.id) for s in data.sectors]
    assert len(data.requests) == sum(len(p.requests) for p in parts)
    assert len({e.id for e in data.engineers}) == len(data.engineers) == sum(len(p.engineers) for p in parts)
    assert all(r.sector for r in data.requests) and all(e.sector for e in data.engineers)
    assert len({e.id for e in data.events}) == len(data.events)


def test_crew_starts_from_own_office():
    """Старт «из офиса» — из офиса своего участка, и точка есть в матрице."""
    data = load_dataset(MOSCOW_ID)
    matrices = load_matrices(MOSCOW_ID)
    for eng in data.engineers:
        point = start_point(eng, "office")
        if point.startswith("office"):
            assert point == f"office:{eng.sector}"
            assert point in matrices.index["car"]


def test_sector_part_is_one_sector():
    """Часть набора — один участок; по идентификатору `moskva@…` её грузит и процесс портфеля."""
    part = load_dataset(f"{MOSCOW_ID}@vostok")
    assert part.id == sector_part(load_dataset(MOSCOW_ID), "vostok").id
    assert {r.sector for r in part.requests} == {"vostok"} and {e.sector for e in part.engineers} == {"vostok"}
    assert not part.sectors


def test_entries_count_every_change_of_sector():
    """Въезд считается на каждой смене участка: «свой → чужой → свой → чужой» — три."""
    data = load_dataset(MOSCOW_ID)
    eng = next(e for e in data.engineers if e.sector == "vostok")
    own = next(r for r in data.requests if r.sector == "vostok")
    other = [r for r in data.requests if r.sector == "yugocentr"][:2]
    by_id = {r.id: r for r in data.requests}
    assert sector_entries(eng, [own.id], by_id) == 0
    assert sector_entries(eng, [other[0].id, own.id, other[1].id], by_id) == 3


def test_price_of_foreign_sector_steers_insertion():
    """Настройка цены меняет выбор: без цены заявку берёт ближняя чужая бригада, с ценой — своя."""
    data = load_dataset(MOSCOW_ID)
    matrices = load_matrices(MOSCOW_ID)
    by_id = {r.id: r for r in data.requests}

    def pick(req, crews, rub: int) -> str | None:
        with settings.use({"economy": {"sector_cross_rub": rub}}):
            chosen = cheapest_insertion(new_states(crews, "office"), req, matrices, by_id, tariffs())
        return chosen[0] if chosen else None

    # Заявка и пара бригад одного транспорта — своя и чужая, — где без цены берёт чужая.
    for req in data.requests:
        if req.skill.value == "emergency":
            continue  # аварию берёт тот, кто начнёт раньше, а не тот, кому дешевле
        own = [e for e in data.engineers if e.sector == req.sector and req.skill in e.skills]
        other = [e for e in data.engineers if e.sector != req.sector and req.skill in e.skills]
        for a in own:
            for b in other:
                if a.transports != b.transports:
                    continue
                if pick(req, [a, b], 0) == b.id:
                    assert pick(req, [a, b], 20000) == a.id
                    return
    raise AssertionError("нет заявки, которую без цены берёт чужая бригада")


def test_economy_counts_foreign_sector():
    """Затраты дня складываются вместе со строкой «чужой участок»: въезды × цена."""
    from bee_routing.baseline import build_baseline
    from bee_routing.economy import summarize

    data = load_dataset(MOSCOW_ID)
    matrices = load_matrices(MOSCOW_ID)
    with settings.use({"economy": {"sector_cross_rub": 2000}}):
        plan, _ = build_baseline(data, matrices)
        e = summarize(plan, data)
    assert e.total_cost_rub == e.payroll_rub + e.bonus_rub + e.travel_rub + e.wait_rub + e.sector_rub
    assert e.sector_rub == e.sector_entries * 2000
