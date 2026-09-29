"""Приложение бригады для показа: адреса, способы поездки, связь, смена, линия пути."""

import pytest
from fastapi.testclient import TestClient

from bee_routing import api, crew_app

from .conftest import REGIONS

pytestmark = pytest.mark.skipif("yugo-vostok" not in REGIONS, reason="нужен Юго-восток")
client = TestClient(api.app)
REGION = "yugo-vostok"


def _crew(n: int) -> str:
    """Бригада набора по порядку: тест не завязан на имена из файла."""
    return client.get(f"/datasets/{REGION}").json()["engineers"][n]["id"]


@pytest.fixture(autouse=True)
def _own_profiles(tmp_path, monkeypatch):
    """Профили — во временном файле: тест не трогает адреса разработчика."""
    monkeypatch.setattr(crew_app, "PROFILE_PATH", tmp_path / "profiles.json")
    crew_app.PROFILES.clear()
    monkeypatch.setattr(crew_app, "_loaded", True)
    api.CHATS.clear()
    api.SHIFTS.clear()
    api.REPORTS.clear()
    yield
    crew_app.PROFILES.clear()


def _plan(settings=None):
    body = {"dataset_id": REGION, "algorithm": "baseline", "start": "home", "settings": settings or {}}
    response = client.post("/plan", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_start_address_goes_to_next_plan_only():
    today = _plan()
    engineer = today["routes"][0]["engineer_id"]
    profile = client.get(f"/crew/{REGION}/{engineer}/profile").json()
    assert profile["addresses"][0]["label"] == "Дом" and profile["since"] is None
    assert "crews" not in (_plan()["settings"] or {}), "открытый, но не сохранённый профиль в план не входит"

    dacha = {"id": "dacha", "label": "Дача", "address": "Видное, Садовая, 3", "lat": 55.55, "lon": 37.71}
    profile["addresses"].append(dacha)
    profile["start_id"] = "dacha"
    saved = client.put(f"/crew/{REGION}/{engineer}/profile", json=profile).json()
    assert saved["start_id"] == "dacha" and saved["since_plan"] == api.LATEST[REGION]

    # Сегодняшний план не трогается: ни сам, ни его пересчёт по событию.
    assert "crews" not in (api.PLANS[today["id"]].settings or {})
    tomorrow = _plan()
    home = tomorrow["settings"]["crews"][engineer]["home"]
    assert (home["lat"], home["lon"]) == (55.55, 37.71) and home["address"].startswith("Дача")


def test_dispatcher_home_wins_over_profile():
    _plan()
    engineer = _crew(1)
    profile = client.get(f"/crew/{REGION}/{engineer}/profile").json()
    profile["addresses"].append({"id": "g", "label": "В гостях", "address": "x", "lat": 55.7, "lon": 37.6})
    profile["start_id"] = "g"
    client.put(f"/crew/{REGION}/{engineer}/profile", json=profile)
    mine = {"crews": {engineer: {"home": {"lat": 55.61, "lon": 37.66}}}}
    plan = _plan(mine)
    assert plan["settings"]["crews"][engineer]["home"]["lat"] == 55.61


def test_ways_list_every_way_with_price_and_nearest_vehicle():
    plan = _plan()
    route = next(r for r in plan["routes"] if len(r["stops"]) >= 2)
    stop = route["stops"][1]
    got = client.get(f"/plan/{plan['id']}/crew/{route['engineer_id']}/ways",
                     params={"request_id": stop["request_id"]}).json()
    kinds = {w["kind"] for w in got["ways"]}
    assert {"transit", "carsharing", "scooter", "ebike", "foot"} <= kinds
    carsharing = next(w for w in got["ways"] if w["kind"] == "carsharing")
    assert carsharing["price_rub"] > 0 and carsharing["vehicle"] and carsharing["walk_min"] >= 1
    assert "демо" in carsharing["note"]
    assert got["vehicles"] and got["plan_arrive"] == stop["arrive"]
    # То же место — те же машины.
    again = client.get("/crew/vehicles", params={"lat": got["origin"][0], "lon": got["origin"][1]}).json()
    assert again == got["vehicles"]


def test_proxy_call_hides_client_and_logs_fact():
    plan = _plan()
    route = next(r for r in plan["routes"] if r["stops"])
    engineer, request_id = route["engineer_id"], route["stops"][0]["request_id"]
    first = client.post(f"/plan/{plan['id']}/crew/{engineer}/call", json={"request_id": request_id}).json()
    second = client.post(f"/plan/{plan['id']}/crew/{engineer}/call", json={"request_id": request_id}).json()
    assert first["proxy"] == second["proxy"] and first["proxy"].startswith("+7 495 ")
    assert "•" in first["client_masked"]
    log = client.get(f"/crew/{REGION}/{engineer}/messages").json()
    assert [m["kind"] for m in log] == ["call", "call"]
    assert all(first["proxy"] not in m["text"] for m in log), "номер в журнал не пишется"


def test_chat_problem_and_sos_reach_dispatcher_inbox():
    engineer = _crew(2)
    client.post(f"/crew/{REGION}/{engineer}/messages", json={"text": "Не пускает охрана", "kind": "problem"})
    client.post(f"/crew/{REGION}/{engineer}/messages", json={"text": "SOS", "kind": "sos"})
    inbox = client.get(f"/crew/{REGION}/inbox").json()
    assert inbox[engineer]["unread"] == 2 and inbox[engineer]["sos"] and inbox[engineer]["problem"]
    client.post(f"/crew/{REGION}/{engineer}/messages", json={"text": "Звоню охране", "author": "dispatcher"})
    client.post(f"/crew/{REGION}/{engineer}/messages/read", params={"reader": "dispatcher"})
    assert engineer not in client.get(f"/crew/{REGION}/inbox").json()
    assert client.post(f"/crew/{REGION}/{engineer}/messages", json={"text": "  "}).status_code == 422


def test_shift_goes_in_order():
    engineer = _crew(2)
    url = f"/crew/{REGION}/{engineer}/shift"
    assert client.post(url, json={"kind": "pause", "time": "10:00"}).status_code == 409
    for kind in ("start", "pause", "resume", "end"):
        assert client.post(url, json={"kind": kind, "time": "10:00"}).status_code == 200, kind
    assert client.post(url, json={"kind": "pause", "time": "22:00"}).status_code == 409
    assert [e["kind"] for e in client.post(url, json={"kind": "start", "time": "10:00"}).json()] == ["start"]


def test_history_is_stable_and_route_line_falls_back(monkeypatch):
    engineer = _crew(2)
    first = client.get(f"/crew/{REGION}/{engineer}/history").json()
    assert first == client.get(f"/crew/{REGION}/{engineer}/history").json()
    assert 1 <= first["rating"] <= 5 and first["days"] and first["reviews"]

    import httpx

    def down(*args, **kwargs):
        raise httpx.ConnectError("нет OSRM")

    monkeypatch.setattr(httpx, "get", down)
    line = client.get("/route", params={"profile": "foot", "coords": "37.6,55.6;37.65,55.62"}).json()
    assert line == {"coordinates": [[37.6, 55.6], [37.65, 55.62]], "source": "straight"}
