"""Гонка планов: правило п. 2.3 без событий — это утро как есть, события у всех одни."""

from bee_routing import settings
from bee_routing.checks import check_visit, feasible
from bee_routing.control import control_plan
from bee_routing.models import Event
from bee_routing.race import HOURS, RulePlayer, run_one
from bee_routing.travel import leg

from .conftest import needs_data


@needs_data
def test_rule_player_without_events_keeps_the_morning(region):
    """Контроль без событий проживается ровно так, как собран: те же визиты, те же времена."""
    data, matrices = region
    morning = control_plan(data, matrices)
    replayed = RulePlayer.of(morning, data, matrices).plan("same", "control")
    before = {s.request_id: (r.engineer_id, s.start) for r in morning.routes for s in r.stops}
    after = {s.request_id: (r.engineer_id, s.start) for r in replayed.routes for s in r.stops}
    assert after == before


@needs_data
def test_new_request_goes_to_first_engineer_who_can_take_it(region):
    """Правило п. 2.3: новую заявку получает первый по порядку инженер, которому она по силам."""
    data, matrices = region
    player = RulePlayer.of(control_plan(data, matrices), data, matrices)
    fresh = data.requests[0].model_copy(update={"id": "n-test", "window_start": "12:00", "window_end": "20:00"})
    matrices.register("n-test", fresh.lat, fresh.lon, alias_of=data.requests[0].id)
    player.handle(Event(id="e1", type="new_request", time="11:00", request=fresh))
    owners = [eng for eng, order in player.order.items() if "n-test" in order]
    if not owners:
        assert any(u.request_id == "n-test" for u in player.unassigned)
        return
    # Все, кто стоит во входных данных раньше владельца, взять её в конец маршрута не могли.
    order = [e for e in settings.effective_engineers(data.engineers)]
    earlier = order[: [e.id for e in order].index(owners[0])]
    states = player.timed()
    for eng in earlier:
        state = states[eng.id]
        depart = max(state.clock, 11 * 60)
        road = leg(eng, state.position, "n-test", matrices, depart)
        assert not feasible(check_visit(eng, fresh, depart + road.minutes, matrices,
                                        prev_id=state.position, depart_min=depart))


@needs_data
def test_race_run_counts_the_same_day_for_all_three(region):
    """Один прогон: у трёх планов одно число заявок дня и часы по одной сетке."""
    data, _ = region
    run = run_one(data.id, "normal", 1)
    assert set(run["players"]) == {"control", "baseline", "ours"}
    for score in run["players"].values():
        assert score["on_time"] + score["late"] + score["missed"] == run["due"]
        assert len(score["done_by_hour"]) == len(HOURS)
        assert score["done_by_hour"] == sorted(score["done_by_hour"])


@needs_data
def test_live_day_uses_one_start_and_the_chosen_events(region):
    """«Живой день» — тот же сценарий, что в гонке: старт один у обоих планов, события — выбранные."""
    from bee_routing.models import ScenarioSpec
    from bee_routing.race import STARTS, day

    data, _ = region
    for start in ("office", "home"):
        spec = ScenarioSpec(dataset_id=data.id, seed=0, new_requests=0, cancels=0, no_shows=0, reschedules=0,
                            delays=0, engineer_off=0, policy="direct", time_limit_s=1, events_from="data",
                            settings={"options": STARTS[start]["options"]})
        out = day(data.id, spec)
        assert out["control"]["start"] == out["ours"]["start"] == start
        assert [e["id"] for e in out["events"]] == [e.id for e in sorted(data.events, key=lambda e: e.time)]
    quiet = day(data.id, spec.model_copy(update={"events_from": "random"}))
    assert quiet["events"] == []


@needs_data
def test_custom_events_happen_exactly_as_set(region):
    """Свои события приходят ровно такими, как заданы: вид, минута, бригада или заявка."""
    from bee_routing.models import CustomEvent, ScenarioSpec
    from bee_routing.simulate import make_events

    data, matrices = region
    eng, req = data.engineers[0].id, data.requests[0].id
    spec = ScenarioSpec(dataset_id=data.id, new_requests=0, cancels=0, no_shows=0, reschedules=0, delays=0,
                        engineer_off=0, custom=[CustomEvent(type="engineer_off", time="13:00", engineer_id=eng),
                                                CustomEvent(type="cancel", time="10:30", request_id=req),
                                                CustomEvent(type="delay", time="12:00", engineer_id="нет такой")])
    events = make_events(data, control_plan(data, matrices), spec, matrices)
    assert [(e.type, e.time) for e in events] == [("cancel", "10:30"), ("engineer_off", "13:00")]
    assert events[0].request_id == req and events[1].engineer_id == eng


@needs_data
def test_morning_is_solved_once_per_key(region):
    """Утро сценария считается один раз на участок, старт и настройки; другой старт — другое утро."""
    import time

    from bee_routing import mornings
    from bee_routing.race import STARTS

    data, matrices = region
    mornings.clear()
    with settings.use({"options": {**STARTS["office"]["options"], "time_limit_s": 1}}):
        first = mornings.morning(data, matrices, "office", 1)
        started = time.perf_counter()
        again = mornings.morning(data, matrices, "office", 1)
        assert time.perf_counter() - started < 0.5
        office_key = mornings.key(data, "office", 1)
    assert again.model_dump(exclude={"created_at"}) == first.model_dump(exclude={"created_at"})
    again.routes.clear()  # копия: запись в памяти остаётся утром
    with settings.use({"options": {**STARTS["office"]["options"], "time_limit_s": 1}}):
        assert mornings.morning(data, matrices, "office", 1).routes
    with settings.use({"options": {**STARTS["home"]["options"], "time_limit_s": 1}}):
        assert mornings.key(data, "home", 1) != office_key
    mornings.clear()
