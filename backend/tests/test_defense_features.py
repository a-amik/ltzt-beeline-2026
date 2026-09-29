"""Доделки к защите 19.09.2026: порядок целей, опорная точка, точка ожидания, волна заявок,
версии дня, сигнал «задерживаюсь», экран руководителя. Каждое правило крутится настройкой."""

import pytest
from fastapi.testclient import TestClient

from bee_routing import api, objective, settings, standby, wave
from bee_routing.baseline import build_baseline, start_point
from bee_routing.economy import tariffs
from bee_routing.loader import load_dataset, load_matrices
from bee_routing.models import Event, ScenarioSpec
from bee_routing.simulate import make_events
from bee_routing.solver import solve

from .conftest import REGIONS

pytestmark = pytest.mark.skipif("yugo-vostok" not in REGIONS, reason="нужен Юго-восток")
client = TestClient(api.app)
REGION = "yugo-vostok"


@pytest.fixture(autouse=True)
def _clean():
    api.QUEUES.clear()
    api.CHATS.clear()
    yield
    api.QUEUES.clear()
    api.CHATS.clear()


def _plan(extra=None, algorithm="baseline"):
    body = {"dataset_id": REGION, "algorithm": algorithm, "settings": extra or {}}
    response = client.post("/plan", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_every_feature_has_settings():
    paths = {f["path"] for g in settings.SCHEMA for f in g["fields"]}
    assert {"options.objective_order", "options.zone_start_point", "options.batch_window_min", "options.standby",
            "options.standby_min_gap_min", "options.standby_radius_km", "options.standby_min_gain_pct",
            "options.delay_auto_replan", "options.delay_auto_min", "options.delay_step_min",
            "options.state_persist", "options.state_keep_plans", "options.manager_on_time_target_pct",
            "options.manager_utilization_target_pct"} <= paths


# ── Порядок целей ─────────────────────────────────────────────────────────


def test_objective_order_is_a_setting():
    conf = tariffs()
    with settings.use({"options": {"objective_order": "sum"}}):
        assert objective.weights(conf) == (0, 0)
    with settings.use({"options": {"objective_order": "on_time_rub_crews"}}):
        skip, crew = objective.weights(conf)
        assert skip > 0 and crew == 0
    with settings.use({}):
        skip, crew = objective.weights(conf)
        assert objective.order() == "on_time_crews_rub"
        assert crew > 0 and skip > int(conf["engineer_day_rub"]) + crew, "заявка старше бригады, бригада старше дороги"


def test_lexicographic_order_saves_crews_without_losing_visits():
    data, matrices = load_dataset("yugocentr"), load_matrices("yugocentr")
    got = {}
    for mode in ("sum", "on_time_crews_rub"):
        with settings.use({"options": {"objective_order": mode, "time_limit_s": 3, "portfolio": False, "lns_s": 0}}):
            plan, _ = solve(data, matrices, plan_id=f"o-{mode}")
            got[mode] = objective.summary(plan)
    assert got["on_time_crews_rub"]["on_time"] >= got["sum"]["on_time"]
    assert got["on_time_crews_rub"]["crews"] <= got["sum"]["crews"]


def test_plan_key_follows_order():
    data, matrices = load_dataset(REGION), load_matrices(REGION)
    plan, _ = build_baseline(data, matrices, plan_id="k1")
    with settings.use({}):
        key = objective.key(plan)
        assert key[1] == -objective.on_time(plan) and key[2] == objective.crews(plan)
    with settings.use({"options": {"objective_order": "on_time_rub_crews"}}):
        assert objective.key(plan)[3] == objective.crews(plan)


# ── Опорная точка района ──────────────────────────────────────────────────


def test_remote_crew_starts_from_town_anchor():
    data, matrices = load_dataset(REGION), load_matrices(REGION)
    crew = next(e for e in data.engineers if e.anchor_name == "Кашира")
    with settings.use({"options": {"start": "office"}}):
        eff = {e.id: e for e in settings.effective_engineers(data.engineers)}
        matrices.adopt(eff.values())
        assert (eff[crew.id].home.lat, eff[crew.id].home.lon) == (crew.anchor.lat, crew.anchor.lon)
        assert start_point(eff[crew.id], "office") == f"home:{crew.id}", "дальняя бригада стартует из своей зоны"
        assert matrices.aliases[f"home:{crew.id}"].startswith("anchor:"), "дорога от опорной точки — по матрице"
    with settings.use({"options": {"zone_start_point": "home"}}):
        eff = {e.id: e for e in settings.effective_engineers(data.engineers)}
        matrices.adopt(eff.values())
        assert (eff[crew.id].home.lat, eff[crew.id].home.lon) == (crew.home.lat, crew.home.lon)
        assert f"home:{crew.id}" not in matrices.aliases
    mine = {"crews": {crew.id: {"home": {"lat": 54.9, "lon": 38.1}}}}
    with settings.use(mine):
        eff = {e.id: e for e in settings.effective_engineers(data.engineers)}
        assert eff[crew.id].home.lat == 54.9, "дом, заданный диспетчером, главнее опорной точки"
    assert all(e.anchor is None for e in data.engineers if e.remote_km < settings.zone_start_km())


# ── Точка ожидания ────────────────────────────────────────────────────────


def test_standby_names_a_place_for_free_windows():
    data, matrices = load_dataset("yugocentr"), load_matrices("yugocentr")
    plan, _ = build_baseline(data, matrices, plan_id="w1")
    with settings.use({}):
        standby.annotate(plan, data)
        assert plan.standby and all(s.text for s in plan.standby)
        gap = int(settings.option("standby_min_gap_min"))
        from bee_routing.checks import to_min

        assert all(to_min(s.end) - to_min(s.start) >= gap for s in plan.standby)
        assert all(s.km <= float(settings.option("standby_radius_km")) for s in plan.standby)
        near_here = near_point = 0.0
        for seed in range(1, 9):
            events = make_events(data, plan, ScenarioSpec(dataset_id=data.id, seed=seed), matrices)
            got = standby.gain(plan, data, events)
            near_here += got["km_from_last_visit"] * got["events"]
            near_point += got["km_from_standby"] * got["events"]
        assert near_point <= near_here, "в точке ожидания свободная бригада не дальше от заявок дня"
    with settings.use({"options": {"standby": False}}):
        assert standby.annotate(plan, data).standby == []
    with settings.use({"options": {"standby_min_gain_pct": 50}}):
        assert all(s.km == 0 for s in standby.annotate(plan, data).standby), "порог выигрыша оставляет ждать на месте"


# ── Волна заявок ──────────────────────────────────────────────────────────


def _event(data, rid, time, skill="connect"):
    base = next(r for r in data.requests if r.skill.value == skill)
    fresh = base.model_copy(update={"id": rid, "window_start": "16:00", "window_end": "20:00", "equipment": []})
    return Event(id=f"e-{rid}", type="new_request", time=time, request=fresh).model_dump(mode="json")


def test_wave_queues_ordinary_and_passes_urgent():
    data = load_dataset(REGION)
    with settings.use({}):
        assert wave.due("12:07") == "12:15" and wave.due("12:15") == "12:15"
    with settings.use({"options": {"batch_window_min": 30}}):
        assert wave.due("12:07") == "12:30"
    plan = _plan()
    first = client.post("/events", json={"plan_id": plan["id"], "event": _event(data, "w-1", "12:03")}).json()
    second = client.post("/events", json={"plan_id": plan["id"], "event": _event(data, "w-2", "12:09")}).json()
    assert not first["applied"] and not second["applied"]
    assert len(second["queue"]) == 2 and second["due"] == "12:15" and second["window_min"] == 15
    hot = client.post("/events", json={"plan_id": plan["id"], "event": _event(data, "w-hot", "12:10", "emergency")}).json()
    assert hot["applied"] and len(hot["queue"]) == 2, "авария — вне очереди, волна ждёт"
    assert any(s["request_id"] == "w-hot" for r in hot["plan"]["routes"] for s in r["stops"])
    done = client.post("/events/flush", json={"dataset_id": REGION}).json()
    assert done["applied"] and done["queue"] == []
    history = done["plan"]["history"]
    assert [e["time"] for e in history if e["id"] in ("e-w-1", "e-w-2")] == ["12:15", "12:15"], "минута пересчёта"
    assert done["plan"]["parent_id"] == hot["plan"]["id"], "волна ложится на план после аварии"

    now = _plan({"options": {"batch_window_min": 0}})
    direct = client.post("/events", json={"plan_id": now["id"], "event": _event(data, "w-3", "12:03")}).json()
    assert direct["applied"], "нулевой отрезок выключает очередь"


# ── Версии дня и перезапуск ───────────────────────────────────────────────


def test_versions_survive_restart(tmp_path, monkeypatch):
    monkeypatch.setenv("BEE_KEEP_STATE", "test")
    monkeypatch.setattr(api, "STATE_PATH", tmp_path / "state.json")
    data = load_dataset(REGION)
    morning = _plan()
    event = next(e for e in data.events if e.type == "cancel").model_dump(mode="json")
    after = client.post("/replan", json={"plan_id": morning["id"], "event": event}).json()
    rows = {r["id"]: r for r in client.get(f"/day/{REGION}/versions").json()}
    assert rows[after["id"]]["parent_id"] == morning["id"] and rows[after["id"]]["current"]
    assert rows[morning["id"]]["on_line"] and rows[after["id"]]["what"] == "Отмена"
    side = client.post("/plan", json={"dataset_id": REGION, "algorithm": "baseline", "remember_latest": False}).json()
    assert side["id"] not in {r["id"] for r in client.get(f"/day/{REGION}/versions").json()}, "план для сравнения — не версия"
    client.post(f"/plan/{morning['id']}/marks", json={"mark": {
        "engineer_id": morning["routes"][0]["engineer_id"], "request_id": morning["routes"][0]["stops"][0]["request_id"],
        "kind": "depart", "time": "10:00"}})

    api.PLANS.clear(), api.LATEST.clear(), api.MARKS.clear(), api.MAINLINE.clear()
    api._load_state()
    assert set(api.PLANS) >= {morning["id"], after["id"]} and api.LATEST[REGION] == after["id"]
    assert api.MARKS[morning["id"]], "отметки бригад пережили перезапуск"
    assert int(api._next_id()[1:]) > int(after["id"][1:]), "номера версий продолжаются"

    back = client.post(f"/plan/{morning['id']}/restore").json()
    rows = {r["id"]: r for r in client.get(f"/day/{REGION}/versions").json()}
    assert back["id"] == morning["id"] and rows[morning["id"]]["current"] and not rows[after["id"]]["on_line"]


# ── Сигнал «задерживаюсь» ─────────────────────────────────────────────────


def test_delay_signal_replans_tail_by_settings():
    plan = _plan()
    route = next(r for r in plan["routes"] if len(r["stops"]) >= 3)
    eng = route["engineer_id"]
    got = client.post(f"/plan/{plan['id']}/crew/{eng}/delay", json={"minutes": 40, "time": "11:00"}).json()
    assert got["replanned"] and got["plan_id"] != plan["id"]
    latest = client.get("/plan/latest", params={"dataset_id": REGION}).json()
    assert latest["id"] == got["plan_id"] and latest["history"][-1]["type"] == "delay"
    assert latest["history"][-1]["delay_min"] == 40 and latest["parent_id"] == plan["id"]
    kinds = [m["kind"] for m in client.get(f"/crew/{REGION}/{eng}/messages").json()]
    assert kinds == ["delay", "text"], "сигнал и ответ о пересчёте — в переписке"

    small = client.post(f"/plan/{got['plan_id']}/crew/{eng}/delay", json={"minutes": 5, "time": "11:30"}).json()
    assert not small["replanned"], "короче порога — только запись"

    manual = _plan({"options": {"delay_auto_replan": False}})
    off = client.post(f"/plan/{manual['id']}/crew/{eng}/delay", json={"minutes": 40, "time": "11:00"}).json()
    assert not off["replanned"]


# ── Экран руководителя ────────────────────────────────────────────────────


def test_manager_overview_uses_targets_from_settings():
    _plan({"options": {"manager_on_time_target_pct": 100, "manager_utilization_target_pct": 30}})
    region = next(r for r in client.get("/manager/overview").json()["regions"] if r["dataset_id"] == REGION)
    assert region["targets"] == {"on_time_pct": 100.0, "utilization_pct": 30.0}
    assert region["crews_total"] == 12 and len(region["crews"]) == region["crews_total"]
    assert region["ok"]["utilization"] is True and isinstance(region["ok"]["on_time"], bool)
    assert {"visits", "done", "late", "flags", "sos", "delays"} <= set(region["crews"][0])


def test_feed_collects_crew_signals():
    plan = _plan()
    eng = plan["routes"][0]["engineer_id"]
    client.post(f"/crew/{REGION}/{eng}/messages", json={"text": "Не пускает охрана", "kind": "problem"})
    client.post(f"/plan/{plan['id']}/crew/{eng}/delay", json={"minutes": 5, "time": "11:00"})
    feed = client.get(f"/crew/{REGION}/feed").json()
    kinds = [x["kind"] for x in feed["items"] if x["engineer_id"] == eng]
    assert "problem" in kinds and "delay" in kinds
    assert feed["unread"] >= 2 and feed["urgent"] >= 2
    client.post(f"/crew/{REGION}/{eng}/messages/read", params={"reader": "dispatcher"})
    assert client.get(f"/crew/{REGION}/feed").json()["unread"] == 0
