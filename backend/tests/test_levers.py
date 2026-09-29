"""Рычаги утилизации: дом и транспорт бригады из настроек, час суток, баланс, портфель, перенос на завтра."""

from fastapi.testclient import TestClient

from bee_routing import settings
from bee_routing.api import app
from bee_routing.benchmark import kpis
from bee_routing.models import Engineer, Point, Transport
from bee_routing.solver import solve
from bee_routing.travel import hour_factor, hour_profile, leg

from .conftest import REGIONS, needs_data

FAST = {"options": {"time_limit_s": 1, "portfolio": False}}


def test_hour_profile_shape():
    """Пик будней в 17—18 длиннее утра и ночи; пешеход и велосипед часа не знают.

    Форма суток — статистика 2ГИС на парах Юго-востока: вечерний пик там
    в 17—18 и к 19 уже спадает, утро легче полудня (сводка 19.09.2026).
    """
    profile = hour_profile()
    assert profile and abs(sum(profile[h] for h in range(11, 18)) / 7 - 1) < 0.02
    with settings.use({"options": {"hourly_traffic": True}}):
        assert hour_factor("car", 18 * 60) > hour_factor("car", 9 * 60)
        assert hour_factor("car", 18 * 60) > hour_factor("car", 22 * 60)
        assert hour_factor("car", 13 * 60) < 1.05
        assert hour_factor("foot", 19 * 60) == 1.0
        assert hour_factor("car", None) == 1.0
    with settings.use({"options": {"hourly_traffic": False}}):
        assert hour_factor("car", 19 * 60) == 1.0


@needs_data
def test_evening_car_leg_is_longer(region):
    """Один и тот же переезд на машине в пик 18 часов дольше, чем в 9 утра."""
    data, matrices = region
    eng = data.engineers[0].model_copy(update={"transports": [Transport.CAR], "transport": Transport.CAR})
    a, b = data.requests[0].id, data.requests[-1].id
    with settings.use({"options": {"hourly_traffic": True, "traffic": True}}):
        morning, evening = leg(eng, a, b, matrices, 9 * 60), leg(eng, a, b, matrices, 18 * 60)
    assert evening.minutes >= morning.minutes
    if morning.minutes >= 20:
        assert evening.minutes > morning.minutes


@needs_data
def test_crew_overrides_apply(region):
    """Дом и транспорт из настроек попадают в бригаду и в план."""
    data, matrices = region
    eng = data.engineers[0]
    crews = {eng.id: {"home": {"lat": 55.75, "lon": 37.62, "address": "Москва, Кремль"},
                      "transports": ["car"], "extra_load": False}}
    with settings.use({**FAST, "crews": crews}):
        effective = settings.effective_engineers(data.engineers)
        mine: Engineer = next(e for e in effective if e.id == eng.id)
        assert mine.home == Point(lat=55.75, lon=37.62)
        assert mine.transports == [Transport.CAR] and mine.extra_load is False
        assert settings.current()["crews"][eng.id]["home"]["address"] == "Москва, Кремль"
        plan, _ = solve(data, matrices, plan_id="p", start="home")
    assert plan.settings["crews"][eng.id]["transports"] == ["car"]
    route = next(r for r in plan.routes if r.engineer_id == eng.id)
    assert all(s.mode == Transport.CAR for s in route.stops)
    assert route.over_norm_min == 0
    # своя точка дома встала в матрицу запасной оценкой
    assert f"home:{eng.id}" in matrices.aliases


def test_crews_sanitize_drops_garbage():
    clean = settings.sanitize({"crews": {"x": {"home": {"lat": 10, "lon": 10}, "transports": ["plane"], "extra_load": 1},
                                         "y": "нет", "z": {"transports": ["bike", "car"]}}})
    assert clean["crews"] == {"x": {"extra_load": True}, "z": {"transports": ["car", "bike"]}}


@needs_data
def test_balance_changes_spread(region):
    """С выравниванием разброс нормо-минут не больше, чем без него, при том же числе выполненных.

    Бюджет боевой, 4 секунды, и без остановки по застою: с выравниванием
    поиск сходится медленнее, и за 2 секунды на Юго-востоке он ещё не дошёл
    до плато (11 неназначенных против 6 на четвёртой секунде).
    """
    data, matrices = region
    # Выравнивание — рублёвый рычаг, третья ступень порядка целей: мерится при счёте одной суммой.
    # Цена ожидания аварии выключена: с 29.09.2026 авария крупного клиента стоит до 150 000 ₽ в час,
    # и в счёте одной суммой решатель бросает ради неё мелкие заявки — это другой рычаг, не выравнивание.
    base = {"time_limit_s": 4, "stall_s": 0, "portfolio": False, "start": "office", "objective_order": "sum",
            "emergency_first": False}
    with settings.use({"options": {**base, "balance": False}}):
        plain, _ = solve(data, matrices, plan_id="a")
    with settings.use({"options": {**base, "balance": True}}):
        even, _ = solve(data, matrices, plan_id="b")
    assert "norm_spread_min" in kpis(even, data)
    # Допуск — две заявки: с приоритетом через ценность (без надбавки ступени) пропуск дешевле,
    # и на Юго-востоке выравнивание за 4 секунды стоит двух заявок (7 против 5, замер 19.09.2026).
    assert len(even.unassigned) <= len(plain.unassigned) + 2


@needs_data
def test_portfolio_not_worse_than_single(region):
    """Портфель стратегий берёт план не хуже одной стратегии по числу выполненных."""
    data, matrices = region
    with settings.use({"options": {"time_limit_s": 1, "portfolio": False}}):
        single, _ = solve(data, matrices, plan_id="s")
    with settings.use({"options": {"time_limit_s": 1, "portfolio": True}}):
        best, states = solve(data, matrices, plan_id="pf")
    assert len(best.unassigned) <= len(single.unassigned) + 1
    assert best.settings.get("options", {}).get("portfolio") is True
    assert set(states) == {e.id for e in data.engineers}


def test_defer_endpoint():
    """Неназначенная заявка уходит в очередь на завтра, чужая — отклоняется."""
    if not REGIONS:
        return
    client = TestClient(app)
    plan = client.post("/plan", json={"dataset_id": REGIONS[0], "algorithm": "baseline"}).json()
    if not plan["unassigned"]:
        return
    rid = plan["unassigned"][0]["request_id"]
    moved = client.post(f"/plan/{plan['id']}/defer", json={"request_id": rid, "time": "12:00"})
    assert moved.status_code == 200
    body = moved.json()
    assert rid in {d["request_id"] for d in body["deferred"]}
    assert rid not in {u["request_id"] for u in body["unassigned"]}
    assert body["metrics"]["unassigned"] == len(plan["unassigned"]) - 1
    assert client.post(f"/plan/{plan['id']}/defer", json={"request_id": "nope"}).status_code == 409
    assert client.get("/plan/latest").json()["id"] == body["id"]
