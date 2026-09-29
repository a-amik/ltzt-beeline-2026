"""Общие правила дня задаёт руководитель; диспетчер присылает только оперативное."""

from fastapi.testclient import TestClient

from bee_routing import settings
from bee_routing.api import app

from .conftest import needs_data

client = TestClient(app)
MANAGER = {"x-bee-role": "manager"}
DISPATCHER = {"x-bee-role": "dispatcher"}


def test_only_manager_changes_rules(monkeypatch):
    monkeypatch.delenv("BEE_MANAGER_KEY", raising=False)
    rules = {"economy": {"request_value_rub": {"connect": 12000}}}
    assert client.put("/rules", json={"rules": rules}).status_code == 403
    denied = client.put("/rules", json={"rules": rules}, headers=DISPATCHER)
    assert denied.status_code == 403 and "руководитель" in denied.json()["detail"]
    assert client.get("/rules").json()["version"] == 0
    ok = client.put("/rules", json={"rules": {**rules, "requests": {"1": {"priority": "urgent"}}, "junk": 1}},
                    headers=MANAGER).json()
    assert ok["rules"] == rules and ok["version"] == 1 and ok["updated_at"], "оперативное и лишнее отброшены"
    assert client.get("/rules").json()["rules"] == rules
    # Ключ стенда: задан — без него роль не помогает.
    monkeypatch.setenv("BEE_MANAGER_KEY", "k-42")
    assert client.put("/rules", json={"rules": {}}, headers=MANAGER).status_code == 403
    assert client.put("/rules", json={"rules": {}}, headers={**MANAGER, "x-bee-key": "k-42"}).status_code == 200


def test_for_role_keeps_dispatcher_to_operative():
    settings.set_rules({"economy": {"engineer_day_rub": 9000}, "options": {"time_limit_s": 6}})
    sent = {"economy": {"engineer_day_rub": 1}, "options": {"time_limit_s": 2, "priority_order": "money"},
            "requests": {"77": {"priority": "high"}}, "crews": {"x": {"extra_load": False}}}
    mine = settings.for_role(sent, "dispatcher")
    assert mine["economy"]["engineer_day_rub"] == 9000 and "priority_order" not in mine["options"]
    assert mine["options"]["time_limit_s"] == 2 and mine["requests"] == sent["requests"] and "crews" not in mine
    # Без роли (тесты, замер) и у руководителя — присланное поверх правил.
    assert settings.for_role(sent, None)["economy"]["engineer_day_rub"] == 1
    assert settings.for_role({}, None)["economy"]["engineer_day_rub"] == 9000


@needs_data
def test_dispatcher_plan_uses_rules_not_own_numbers():
    client.put("/rules", json={"rules": {"economy": {"request_value_rub": {"connect": 12000}}}}, headers=MANAGER)
    body = {"dataset_id": "yugocentr", "algorithm": "baseline",
            "settings": {"economy": {"request_value_rub": {"connect": 100}},
                         "requests": {"x1": {"priority": "urgent"}}}}
    plan = client.post("/plan", json=body, headers=DISPATCHER).json()
    assert plan["settings"]["economy"]["request_value_rub"]["connect"] == 12000
    assert plan["settings"]["requests"] == {"x1": {"priority": "urgent"}}, "ручной приоритет — дело диспетчера"
    lab = client.post("/plan", json=body).json()
    assert lab["settings"]["economy"]["request_value_rub"]["connect"] == 100, "без роли — как до разделения"
