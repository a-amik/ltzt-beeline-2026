"""Сегмент клиента аварии: KA, A, B, C, D — цена аварии, срок SLA, какую аварию брать первой."""

from fastapi.testclient import TestClient

from bee_routing import settings
from bee_routing.api import app
from bee_routing.economy import late_rate, late_sla, request_value, skip_penalty, tariffs, weight_text
from bee_routing.loader import load_dataset, load_matrices
from bee_routing.models import Request
from bee_routing.segments import estimate
from bee_routing.solver import solve

from .conftest import needs_data

client = TestClient(app)


def _emergencies(region: str = "yugo-vostok") -> list[Request]:
    return [r for r in load_dataset(region).requests if r.skill.value == "emergency"]


@needs_data
def test_segment_is_deterministic_and_only_for_emergencies():
    data = load_dataset("yugo-vostok")
    for req in data.requests:
        if req.skill.value == "emergency":
            assert req.segment in ("KA", "A", "B", "C", "D")
            assert req.segment == estimate(req.id)
            assert Request(**req.model_dump(exclude={"segment"})).segment == req.segment, "тот же номер — тот же сегмент"
        else:
            assert req.segment is None
    # Сегмент из своего набора главнее синтетики.
    assert Request(**{**_emergencies()[0].model_dump(), "segment": "KA"}).segment == "KA"
    # Доли: микро-клиентов больше всех, ключевых — единицы.
    picks = [estimate(str(i)) for i in range(5000)]
    assert picks.count("D") > picks.count("C") > picks.count("B") > picks.count("KA")


@needs_data
def test_value_by_segment_and_follows_settings():
    base = _emergencies()[0]
    with settings.use({}):
        conf = tariffs()
        at = lambda s: request_value(base.model_copy(update={"segment": s}), conf)
        assert [at(s) for s in ("KA", "A", "B", "C", "D")] == [1490000, 620000, 77200, 12000, 2800]
        assert "клиента A" in weight_text(base.model_copy(update={"segment": "A"}), conf)
        a = base.model_copy(update={"segment": "A"})
        assert late_rate(a, conf) == round(620000 * 0.1 / 60)
        assert late_sla(a, conf) == (120, late_rate(a, conf)), "A: 2 часа, после — вдвое дороже"
        assert late_sla(base.model_copy(update={"segment": "D"}), conf) == (0, 0), "D: до конца дня"
    with settings.use({"economy": {"emergency_segments": {"A": {"bill_rub": 100000}}}}):
        assert request_value(a, tariffs()) == round(100000 * 48 * 0.5 * 0.1 + 20000)
    # Диспетчер знает клиента лучше синтетики.
    with settings.use({"requests": {base.id: {"segment": "KA"}}}):
        assert request_value(base.model_copy(update={"segment": "D"}), tariffs()) == 1490000


@needs_data
def test_tier_order_by_setting():
    data = load_dataset("yugo-vostok")
    connects = [r for r in data.requests if r.skill.value == "connect"]
    micro = _emergencies()[0].model_copy(update={"segment": "D"})
    key = _emergencies()[1].model_copy(update={"segment": "KA"})
    for mode in ("organizers", "strict"):
        with settings.use({"options": {"priority_order": mode}}):
            conf = tariffs()
            assert skip_penalty(micro, conf) > max(skip_penalty(r, conf) for r in connects), mode
            assert skip_penalty(key, conf) > skip_penalty(micro, conf)
    with settings.use({"options": {"priority_order": "money"}}):
        conf = tariffs()
        assert skip_penalty(micro, conf) < max(skip_penalty(r, conf) for r in connects), "по деньгам микро уступает"
    with settings.use({"requests": {micro.id: {"priority": "urgent"}}}):
        conf = tariffs()
        assert skip_penalty(micro, conf) > skip_penalty(key, conf), "«срочно» диспетчера поверх сегмента"


@needs_data
def test_big_client_goes_first_when_crews_are_short():
    data, matrices = load_dataset("yugo-vostok"), load_matrices("yugo-vostok")
    crew = next(e for e in data.engineers if any(s.value == "emergency" for s in e.skills))
    flat = [r.model_copy(update={"segment": "D"}) for r in _emergencies()]
    base = {"options": {"time_limit_s": 2, "portfolio": False, "lns_s": 0}}
    one = data.model_copy(update={"engineers": [crew], "requests": flat, "events": []})
    with settings.use(base):
        plan, _ = solve(one, matrices, plan_id="s0")
    skipped = [u.request_id for u in plan.unassigned]
    assert skipped, "одной бригаде все аварии не успеть"
    target = skipped[0]
    raised = [r.model_copy(update={"segment": "A"}) if r.id == target else r for r in flat]
    with settings.use(base):
        again, _ = solve(one.model_copy(update={"requests": raised}), matrices, plan_id="s1")
    assert any(s.request_id == target for r in again.routes for s in r.stops), "аварию крупного клиента взяли"


@needs_data
def test_plan_carries_segment_in_words():
    plan = client.post("/plan", json={"dataset_id": "yugo-vostok", "algorithm": "baseline"}).json()
    ids = {r.id for r in _emergencies()}
    assert ids <= set(plan["weights"])
    assert all(text.startswith("Авария у клиента ") and "₽" in text for text in plan["weights"].values())


@needs_data
def test_waiting_for_big_client_never_outranks_requests_by_default():
    from bee_routing.objective import late_bound, weights

    ka = [r.model_copy(update={"segment": "KA"}) for r in _emergencies()]
    with settings.use({}):
        conf = tariffs()
        late = late_bound(ka, conf)
        skip, crew = weights(conf, 720, ka)
        assert late > 0 and crew > late and skip > late, "строго по ТЗ: ни заявка, ни бригада не уступают ожиданию"
    with settings.use({"options": {"emergency_tradeoff": "crews"}}):
        skip, crew = weights(tariffs(), 720, ka)
        assert skip > late > crew, "бригаду вывести можно, заявку бросить нельзя"
    with settings.use({"options": {"emergency_tradeoff": "money"}}):
        skip, crew = weights(tariffs(), 720, ka)
        assert skip < late, "по деньгам ожидание наравне со всем"
