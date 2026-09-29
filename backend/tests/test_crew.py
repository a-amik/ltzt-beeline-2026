"""Приложение бригады и контроль: заработок, ответ на предложение, флаги по отметкам."""

from bee_routing import settings
from bee_routing.checks import to_clock, to_min
from bee_routing.crew import crew_day, respond
from bee_routing.fraud import audit
from bee_routing.models import Event, Mark, OfferResponse
from bee_routing.replan import replan
from bee_routing.solver import solve

from .conftest import needs_data

FAST = {"options": {"time_limit_s": 2}}


def _plan_with_offer(data, matrices):
    """План, в котором у новой заявки есть предложения бригадам."""
    plan, _ = solve(data, matrices, plan_id="p1")
    for base in data.requests[:12]:
        fresh = base.model_copy(update={"id": f"o-{base.id}", "window_start": "15:00", "window_end": "20:00"})
        matrices.register(fresh.id, fresh.lat, fresh.lon, alias_of=base.id)
        event = Event(id=f"e-{base.id}", type="new_request", time="12:00", request=fresh, policy="offer")
        after = replan(plan, data, matrices, event, plan_id="p2")
        offer = next((o for o in after.offers if o.request_id == fresh.id and o.candidates), None)
        if offer:
            return after, offer
    return None, None


@needs_data
def test_crew_day_earnings_confirmed_by_marks(region):
    """Бонус по плану виден сразу, бонус по факту — только за визиты с отметкой «закончил»."""
    data, matrices = region
    with settings.use(FAST):
        plan, _ = solve(data, matrices, plan_id="p1")
        route = next(r for r in plan.routes if r.stops)
        day = crew_day(plan, data, route.engineer_id, [])
        assert day.earnings.day_rub > 0
        assert day.earnings.norm_confirmed_min == 0
        assert day.earnings.norm_planned_min == route.norm_min
        assert day.next_request_id == route.stops[0].request_id
        marks = [
            Mark(engineer_id=route.engineer_id, request_id=s.request_id, kind="done", time=s.end)
            for s in route.stops
        ]
        full = crew_day(plan, data, route.engineer_id, marks)
        assert full.earnings.norm_confirmed_min == route.norm_min
        assert full.earnings.bonus_confirmed_rub == full.earnings.bonus_planned_rub
        assert full.next_request_id is None


@needs_data
def test_offer_accept_and_decline(region):
    """Принятое предложение ставит заявку в маршрут; отказ уводит его дальше или на завтра."""
    data, matrices = region
    with settings.use(FAST):
        plan, offer = _plan_with_offer(data, matrices)
        if plan is None:
            return  # в этом регионе предложений не вышло — нечего проверять
        first = offer.candidates[0]
        accepted, text = respond(
            plan, data, matrices,
            OfferResponse(request_id=offer.request_id, engineer_id=first.engineer_id, accepted=True, time="12:05"),
            plan_id="p3",
        )
        assert any(s.request_id == offer.request_id for r in accepted.routes for s in r.stops
                   if r.engineer_id == first.engineer_id), text
        assert not any(o.request_id == offer.request_id for o in accepted.offers)

        current = plan
        for candidate in offer.candidates:
            current, text = respond(
                current, data, matrices,
                OfferResponse(request_id=offer.request_id, engineer_id=candidate.engineer_id, accepted=False,
                              reason="далеко", time="12:06"),
                plan_id=f"d-{candidate.engineer_id}",
            )
        assert any(d.request_id == offer.request_id for d in current.deferred), text
        assert not any(o.request_id == offer.request_id for o in current.offers)


@needs_data
def test_fraud_flags(region):
    """Слишком быстрая работа, отметка не с адреса и наложение визитов дают флаги с действием."""
    data, matrices = region
    with settings.use(FAST):
        plan, _ = solve(data, matrices, plan_id="p1")
        route = next(r for r in plan.routes if len(r.stops) >= 2)
        a, b = route.stops[0], route.stops[1]
        req_a = next(r for r in data.requests if r.id == a.request_id)
        eng = route.engineer_id
        t0 = to_min(a.start)
        marks = [
            Mark(engineer_id=eng, request_id=a.request_id, kind="arrive", time=a.arrive, lat=req_a.lat + 0.02, lon=req_a.lon),
            Mark(engineer_id=eng, request_id=a.request_id, kind="start", time=a.start),
            Mark(engineer_id=eng, request_id=b.request_id, kind="start", time=to_clock(t0 + 1)),
            Mark(engineer_id=eng, request_id=a.request_id, kind="done", time=to_clock(t0 + 5)),
        ]
        flags = audit(plan, data, marks, [])
    codes = {f.code for f in flags if f.engineer_id == eng}
    assert {"too_fast", "far_from_address", "overlap"} <= codes
    assert all(f.action for f in flags)

    declines = [OfferResponse(request_id="x", engineer_id=eng, accepted=False) for _ in range(3)]
    with settings.use(FAST):
        codes = {f.code for f in audit(plan, data, [], declines)}
    assert "declines" in codes
