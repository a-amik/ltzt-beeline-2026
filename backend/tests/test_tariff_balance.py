"""Тарифы B2B сами держат порядок ступеней; дорога — время, километры, проезд, усталость, дорога домой, сезон."""

from bee_routing import settings
from bee_routing.baseline import start_point
from bee_routing.arcs import group_matrices, home_column
from bee_routing.economy import balance_issues, tariffs, travel_cost
from bee_routing.loader import load_dataset, load_matrices
from bee_routing.models import Route, Stop, Transport
from bee_routing.objective import long_leg
from bee_routing.travel import adjusted

from .conftest import needs_data


def test_tariff_balance_names_cheap_emergencies_and_broken_tiers():
    with settings.use({}):
        issues = balance_issues(tariffs())
    assert issues and all("Авария у клиента" in s for s in issues), "подключение и ремонт держат порядок сами"
    assert {s.split()[3] for s in issues} == {"C", "D"}, "дешевле двух подключений — только мелкие сегменты"
    with settings.use({"economy": {"request_value_rub": {"connect": 4000}}}):
        assert any(s.startswith("Подключение") for s in balance_issues(tariffs())), "сторож говорит словами"


def _stop(mode: str, minutes: int, km: float) -> Stop:
    return Stop(request_id="x", seq=1, depart_prev="09:30", arrive="10:00", start="10:00", end="11:00",
                travel_min=minutes, travel_km=km, wait_min=0, late_min=0, mode=Transport(mode))


def test_travel_cost_counts_transit_fare_and_follows_setting():
    route = Route(engineer_id="e", distance_km=10, travel_min=60, work_min=0,
                  stops=[_stop("transit", 30, 5), _stop("transit", 30, 5)])
    with settings.use({}):
        assert travel_cost(route, tariffs()) == 60 * 18 + 2 * 75
    with settings.use({"economy": {"transit_rub_per_leg": 0}}):
        assert travel_cost(route, tariffs()) == 60 * 18


def test_long_leg_surcharge_follows_setting():
    with settings.use({}):
        assert long_leg(tariffs()) == (40, 9)
    with settings.use({"economy": {"long_leg_surcharge": 0}}):
        assert long_leg(tariffs())[1] == 0


def test_season_factor_slows_every_mode():
    with settings.use({}):
        summer = adjusted("foot", 60, 5.0)[0]
    with settings.use({"options": {"season_factor": 1.3}}):
        winter = adjusted("foot", 60, 5.0)[0]
    assert winter > summer


@needs_data
def test_return_home_prices_the_arc_into_route_end():
    data, matrices = load_dataset("yugo-vostok"), load_matrices("yugo-vostok")
    eng = data.engineers[0]
    matrices.adopt([eng])
    far = max(data.requests[:30], key=lambda r: r.id)
    home = start_point(eng, "office")
    points = [home, far.id, None]
    with settings.use({}):
        conf = tariffs()
        _, cost = group_matrices(eng, points, [0, far.duration_min, 0], matrices, 18, 14.0,
                                 transit_rub=int(conf["transit_rub_per_leg"]), home=home, home_share=0.5)
        _, free = group_matrices(eng, points, [0, far.duration_min, 0], matrices, 18, 14.0)
    assert free[1][2] == 0, "без дома конец маршрута бесплатный"
    full = home_column(eng, points, home, matrices, 18, 14.0, int(conf["transit_rub_per_leg"]))[1]
    assert full > 0 and cost[1][2] == round(full * 0.5), "половина дороги домой"
    assert conf["return_home_share"] == 0.5
