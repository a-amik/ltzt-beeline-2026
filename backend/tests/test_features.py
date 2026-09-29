"""Загрузка своего файла, риск окна, оборудование и старт удалённых бригад из зоны."""

import json

from fastapi.testclient import TestClient

from bee_routing import settings
from bee_routing.api import app
from bee_routing.enrich import remote_km
from bee_routing.equipment import equipment_for, kit_for
from bee_routing.loader import load_dataset, load_matrices
from bee_routing.risk import annotate
from bee_routing.solver import solve
from bee_routing.upload import UploadError, from_text

from .conftest import REGIONS, needs_data, needs_raw

client = TestClient(app)


@needs_data
def test_equipment_is_deterministic_and_by_type():
    """Устройства разыгрываются от номера заявки: тот же датасет — те же устройства."""
    data = load_dataset(REGIONS[0])
    assert any(req.equipment for req in data.requests)
    for req in data.requests:
        assert req.equipment == equipment_for(req.id, req.type_bk)
        if req.type_bk == "Подключение":
            assert "router" in req.equipment  # у подключения роутер всегда
        if req.type_bk == "Глобальная проблема":
            assert req.equipment == []


@needs_data
def test_kit_sums_route_devices():
    """Набор на утро — сумма устройств по маршруту бригады, и он отдаётся приложению."""
    data, matrices = load_dataset(REGIONS[0]), load_matrices(REGIONS[0])
    with settings.use({"options": {"portfolio": False, "time_limit_s": 1}}):
        plan, _ = solve(data, matrices)
    by_id = {r.id: r for r in data.requests}
    route = next(r for r in plan.routes if r.stops)
    kit = kit_for(plan, data, route.engineer_id)
    expected = sum(len(by_id[s.request_id].equipment) for s in route.stops)
    assert sum(kit.values()) == expected


@needs_data
def test_risk_marks_stops_and_plan():
    """Риск у визитов в [0, 1], у плана — их сумма; без опции поля обнулены."""
    data, matrices = load_dataset(REGIONS[0]), load_matrices(REGIONS[0])
    by_id = {r.id: r for r in data.requests}
    with settings.use({"options": {"portfolio": False, "time_limit_s": 1, "risk": True}}):
        plan, _ = solve(data, matrices)
        annotate(plan, by_id)
        stops = [s for r in plan.routes for s in r.stops]
        assert all(0.0 <= s.late_risk <= 1.0 for s in stops)
        assert all(s.arrive_p90 is not None for s in stops)
        assert abs(plan.metrics.risk_late - sum(s.late_risk for s in stops)) < 0.05
        first = [s.late_risk for s in stops]
        annotate(plan, by_id)
        assert [s.late_risk for s in stops] == first  # шум посеян
    with settings.use({"options": {"risk": False}}):
        annotate(plan, by_id)
    assert plan.metrics.risk_late == 0 and all(s.late_risk == 0 for s in stops)


@needs_data
def test_control_is_more_fragile_than_ours():
    """Контроль заказчика с его опозданиями срывает окна при шуме чаще нашего плана."""
    if "yugo-vostok" not in REGIONS:
        return
    ours = client.post("/plan", json={"dataset_id": "yugo-vostok", "algorithm": "solver",
                                       "settings": {"options": {"portfolio": False, "time_limit_s": 2}}}).json()
    control = client.get("/datasets/yugo-vostok/control").json()
    assert ours["metrics"]["risk_late"] < control["metrics"]["risk_late"]


@needs_data
def test_zone_start_uses_home_for_remote_crews_only():
    """Удалённая бригада при старте из офиса стартует из зоны; остальные — из офиса."""
    if "yugo-vostok" not in REGIONS:
        return
    from bee_routing.baseline import start_point

    data = load_dataset("yugo-vostok")
    remote = [e for e in data.engineers if e.remote_km >= settings.zone_start_km()]
    near = [e for e in data.engineers if e.remote_km < settings.zone_start_km()]
    assert remote and near
    assert dict(remote_km(json.loads(data.model_dump_json())))[remote[0].id] == remote[0].remote_km
    with settings.use({"options": {"zone_start": True}}):
        assert start_point(remote[0], "office") == f"home:{remote[0].id}"
        assert start_point(near[0], "office") == "office"
    with settings.use({"options": {"zone_start": False}}):
        assert start_point(remote[0], "office") == "office"


@needs_data
@needs_raw
def test_upload_csv_and_json_roundtrip():
    """CSV заказчика и JSON по контракту разбираются, ошибка — словами."""
    from bee_routing.loader import DATASETS_DIR
    from bee_routing.matrices import DATA_DIR

    raw = (DATA_DIR / "raw" / f"{REGIONS[0]}-zayavki.csv").read_text(encoding="utf-8-sig").splitlines()
    office = [line for line in raw if line.lower().startswith("адрес офиса")]
    csv_text = "\n".join(raw[:9] + office)
    data = from_text("Пробный.csv", csv_text, engineers=2)
    assert len(data["requests"]) == 8 and len(data["engineers"]) == 2
    assert data["id"].startswith("upload-probnyj-")
    assert data["id"] == from_text("Пробный.csv", csv_text, engineers=2)["id"]
    assert all("equipment" in r for r in data["requests"])

    json_text = (DATASETS_DIR / f"{REGIONS[0]}.json").read_text(encoding="utf-8")
    again = from_text("копия.json", json_text, name="Копия")
    assert again["name"] == "Копия" and len(again["requests"]) == len(json.loads(json_text)["requests"])

    for bad in ("a;b\n1;2\n", "\n".join(raw[:3])):
        try:
            from_text("x.csv", bad)
        except UploadError as error:
            assert "«" in str(error)
        else:
            raise AssertionError("плохой файл прошёл")
    response = client.post("/datasets/upload", json={"filename": "x.txt", "content": "ничего"})
    assert response.status_code == 422 and ".csv" in response.json()["detail"]
