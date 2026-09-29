"""Ручной приоритет заявки (VIP): уровень — настройка `requests`, сила — тарифы `manual_bonus_rub`."""

from bee_routing import settings
from bee_routing.economy import priority_tier, request_value, skip_penalty, tariffs
from bee_routing.loader import load_dataset, load_matrices
from bee_routing.replan import default_policy
from bee_routing.solver import solve

from .conftest import needs_data


@needs_data
def test_levels_change_price_tier_and_policy():
    data = load_dataset("yugo-vostok")
    local = next(r for r in data.requests if r.skill.value == "local")
    with settings.use({}):
        conf = tariffs()
        base_value, base_skip, base_tier = request_value(local, conf), skip_penalty(local, conf), priority_tier(local)
        assert default_policy(local) == "offer" and not settings.is_urgent(local)
    with settings.use({"requests": {local.id: {"priority": "urgent"}}}):
        assert settings.is_urgent(local) and default_policy(local) == "direct"
        assert priority_tier(local) == "emergency"
        assert request_value(local, tariffs()) == round(base_value * 1.5)
        assert skip_penalty(local, tariffs()) > base_skip + 190000
    with settings.use({"requests": {local.id: {"priority": "high"}}}):
        assert priority_tier(local) == "connect" and base_tier == "rest"
        # надбавка ручного приоритета складывается с надбавкой ступени (с 22.09.2026 она включена)
        assert skip_penalty(local, tariffs()) == base_skip + 20000 + 20000
    with settings.use({"requests": {local.id: {"priority": "low"}}}):
        assert request_value(local, tariffs()) == round(base_value * 0.5)
    with settings.use({"requests": {local.id: {"priority": "vip"}, 5: {"priority": "high"}}}):
        assert settings.current().get("requests") in (None, {}), "незнакомый уровень отбрасывается"


@needs_data
def test_raised_request_is_taken_under_scarcity():
    data, matrices = load_dataset("yugo-vostok"), load_matrices("yugo-vostok")
    few = data.model_copy(update={"engineers": data.engineers[:2]})
    base = {"options": {"time_limit_s": 2, "portfolio": False, "lns_s": 0}}
    with settings.use(base):
        plan, _ = solve(few, matrices, plan_id="m0")
    skipped = [u.request_id for u in plan.unassigned
               if next(r for r in data.requests if r.id == u.request_id).skill.value == "local"]
    assert skipped, "бригад должно не хватать"
    target = skipped[0]
    with settings.use({**base, "requests": {target: {"priority": "urgent"}}}):
        raised, _ = solve(few, matrices, plan_id="m1")
    assert any(s.request_id == target for r in raised.routes for s in r.stops), "поднятую заявку взяли"
