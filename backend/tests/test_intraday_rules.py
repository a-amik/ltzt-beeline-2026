"""Ответы Билайна 19.09.2026: запас оборудования, реакция на аварию, резерв, доля заявок дня, новые дни.

Правило проекта: ни одно из этих чисел не зашито в код — каждое лежит
в настройках (`settings.SCHEMA`) или допущениях (`assumptions.json`),
и тесты меняют поведение именно настройкой.
"""

import shutil
from collections import Counter

import pytest

from bee_routing import settings, stock
from bee_routing.baseline import build_baseline
from bee_routing.checks import to_min
from bee_routing.economy import morning_conf, norm_limit, norm_minutes, tariffs
from bee_routing.geocode import Geocoder, load_assumptions
from bee_routing.loader import load_dataset, load_matrices
from bee_routing.models import Event, ScenarioSpec
from bee_routing.replan import replan
from bee_routing.simulate import intraday_count
from bee_routing.solver import solve

from .conftest import REGIONS, needs_raw

pytestmark = pytest.mark.skipif("yugo-vostok" not in REGIONS, reason="нужен Юго-восток")


def test_every_number_is_a_setting():
    paths = {f["path"] for g in settings.SCHEMA for f in g["fields"]}
    assert {"options.reserve_pct", "options.emergency_reaction_min", "options.intraday_share_pct",
            "options.equipment_stock", "options.spare_units_foot", "options.spare_units_car"} <= paths
    conf = load_assumptions()
    assert conf["engineers"]["remote_transports"] and "by_type_bk" in conf["equipment"]


def test_morning_stock_is_route_plus_spare_from_settings():
    data, matrices = load_dataset("yugo-vostok"), load_matrices("yugo-vostok")
    plan, _ = build_baseline(data, matrices, plan_id="s1")
    by_id = {r.id: r for r in data.requests}
    foot = next(e for e in data.engineers if "car" not in [t.value for t in e.transports])
    car = next(e for e in data.engineers if "car" in [t.value for t in e.transports])
    with settings.use({}):
        have = stock.morning(plan, data)
        for eng, spare in ((foot, 2), (car, 6)):
            route = next((r for r in plan.routes if r.engineer_id == eng.id), None)
            need = sum(len(by_id[s.request_id].equipment) for s in (route.stops if route else []))
            assert sum(have[eng.id].values()) == need + spare
        rest = stock.left(foot.id, next((r.stops for r in plan.routes if r.engineer_id == foot.id), []), by_id, have)
        assert rest == {"router": 1, "tv_box": 1, "speaker": 0}, "два устройства пешего — роутер и приставка"
    with settings.use({"options": {"spare_units_foot": 0}}):
        assert sum(stock.morning(plan, data)[foot.id].values()) == sum(have[foot.id].values()) - 2


def _new_request(data, device):
    base = next(r for r in data.requests if r.skill.value == "connect")
    fresh = base.model_copy(update={"id": "n-stock", "equipment": [device], "window_start": "15:00",
                                    "window_end": "19:00"})
    return Event(id="e-stock", type="new_request", time="12:00", request=fresh, policy="direct")


def test_request_goes_only_to_crew_with_device_left():
    data, matrices = load_dataset("yugo-vostok"), load_matrices("yugo-vostok")
    event = _new_request(data, "speaker")
    with settings.use({}):
        plan, _ = build_baseline(data, matrices, plan_id="s2")
        after = replan(plan, data, matrices, event, plan_id="s3")
    owner = next((r.engineer_id for r in after.routes for s in r.stops if s.request_id == "n-stock"), None)
    assert owner is not None, "колонка есть в запасе у бригад на машине"
    assert "car" in [t.value for e in data.engineers if e.id == owner for t in e.transports], \
        "у пешего инженера в рюкзаке роутер и приставка, колонки нет"
    assert after.stock == stock.morning(plan, data), "запас утренний и едет через пересчёты"

    none = {"options": {"spare_units_foot": 0, "spare_units_car": 0}}
    with settings.use(none):
        from bee_routing.explain import unassigned_reason
        from bee_routing.insertion import best_insertion, requests_of, restore_states

        plan, _ = build_baseline(data, matrices, plan_id="s4")
        by_id = {**requests_of(data, plan), "n-stock": event.request}
        states = restore_states(plan, data, matrices)
        with stock.use(stock.morning(plan, data), by_id):
            assert all(best_insertion(st, event.request, matrices, by_id) is None for st in states.values())
            code, text = unassigned_reason(event.request, data.engineers, states, matrices)
        assert code == "no_stock" and "колонка" in text
        # Весь пересчёт: ни у одной бригады остаток не уходит в минус.
        after = replan(plan, data, matrices, event, plan_id="s5")
        known = {**by_id, **requests_of(data, after)}
        for route in after.routes:
            rest = stock.left(route.engineer_id, route.stops, known, after.stock)
            assert min(rest.values()) >= 0, (route.engineer_id, rest)

    with settings.use({"options": {**none["options"], "equipment_stock": False}}):
        plan, _ = build_baseline(data, matrices, plan_id="s6")
        states = restore_states(plan, data, matrices)
        with stock.use(stock.morning(plan, data), by_id):
            assert any(best_insertion(st, event.request, matrices, by_id) is not None for st in states.values()), \
                "учёт выключен — запас не мешает"


@pytest.mark.parametrize("limit", [60, 120])
def test_intraday_accident_meets_reaction_limit(limit):
    data, matrices = load_dataset("yugo-vostok"), load_matrices("yugo-vostok")
    event = next(e for e in data.events if e.type == "urgent")
    with settings.use({"options": {"emergency_reaction_min": limit}}):
        plan, _ = build_baseline(data, matrices, plan_id="r1")
        after = replan(plan, data, matrices, event, plan_id="r2")
    start = next(to_min(s.start) for r in after.routes for s in r.stops if s.request_id == event.request.id)
    wait = start - to_min(event.time)
    assert wait <= limit or after.history[-1].note == "reaction_missed", "опоздание к пределу помечено"
    if limit == 120:
        assert wait <= 120, "на Юго-востоке в два часа успевают"


def test_reserve_keeps_share_of_norm_free_in_morning():
    data, matrices = load_dataset("yugo-vostok"), load_matrices("yugo-vostok")
    by_id = {r.id: r for r in data.requests}
    served = {}
    for pct in (0, 30):
        with settings.use({"options": {"reserve_pct": pct, "time_limit_s": 2, "portfolio": False, "lns_s": 0}}):
            plan, _ = solve(data, matrices, plan_id=f"v{pct}")
            conf = morning_conf()
            engineers = {e.id: e for e in settings.effective_engineers(data.engineers)}
            for route in plan.routes:
                # Аварии берутся и сверх предела (`repair.cheapest_insertion`): резерв держат обычные заявки.
                norm = sum(norm_minutes(by_id[s.request_id], conf) for s in route.stops
                           if by_id[s.request_id].skill.value != "emergency")
                assert norm <= norm_limit(engineers[route.engineer_id], conf), (pct, route.engineer_id, norm)
            served[pct] = sum(len(r.stops) for r in plan.routes)
            # Днём резерв и расходуется: предел пересчёта — полный.
            assert norm_limit(engineers[plan.routes[0].engineer_id], tariffs()) > norm_limit(
                engineers[plan.routes[0].engineer_id], conf) or pct == 0
    assert served[30] <= served[0]


def test_intraday_share_comes_from_settings():
    data = load_dataset("yugo-vostok")
    spec = ScenarioSpec(dataset_id=data.id)
    with settings.use({}):
        assert intraday_count(spec, data) == 10, "12 % от 83"
    with settings.use({"options": {"intraday_share_pct": 15}}):
        assert intraday_count(spec, data) == 12
    assert intraday_count(ScenarioSpec(dataset_id=data.id, new_requests=3), data) == 3


def test_remote_crews_drive_and_two_thirds_need_devices():
    total = with_device = 0
    for region in ("vostok", "yugo-vostok", "yugocentr"):
        data = load_dataset(region)
        total += len(data.requests)
        with_device += sum(1 for r in data.requests if r.equipment)
        for eng in data.engineers:
            if eng.remote_km >= settings.zone_start_km():
                assert [t.value for t in eng.transports] == load_assumptions()["engineers"]["remote_transports"]
    assert 0.62 <= with_device / total <= 0.72, with_device / total


@needs_raw
def test_extra_day_is_found_and_built(tmp_path):
    from bee_routing import prepare

    conf = load_assumptions()
    for kind in ("zayavki", "kontrol"):
        shutil.copy(prepare.RAW_DIR / f"yugocentr-{kind}.csv", tmp_path / f"yugocentr-2026-08-18-{kind}.csv")
    shutil.copy(prepare.RAW_DIR / "yugocentr-zayavki.csv", tmp_path / "yugocentr-2026-08-19-zayavki.csv")
    assert prepare.extra_days(conf, tmp_path) == [("yugocentr", "2026-08-18"), ("yugocentr", "2026-08-19")]
    geo = Geocoder(conf, offline=True)
    day = prepare.build_dataset("yugocentr", conf, geo, "2026-08-18", tmp_path)
    assert (day["id"], day["date"], day["name"]) == ("yugocentr-2026-08-18", "2026-08-18", "Югоцентр, 18 августа")
    assert Counter(r["type_bk"] for r in day["requests"]) == Counter(
        r.type_bk for r in load_dataset("yugocentr").requests)
    bare = prepare.build_dataset("yugocentr", conf, geo, "2026-08-19", tmp_path)
    assert len(bare["engineers"]) == 11 and bare["control"] == []
    # События дня без контроля — из его строк: авария по типу HD; отмены нет — в файле нет
    # статуса BK; выбывает та же бригада, что в первый день.
    first_off = [e.engineer_id for e in load_dataset("yugocentr").events if e.type == "engineer_off"]
    assert [e["type"] for e in bare["events"]] == ["urgent", "engineer_off"]
    assert [e["engineer_id"] for e in bare["events"] if e["type"] == "engineer_off"] == first_off
