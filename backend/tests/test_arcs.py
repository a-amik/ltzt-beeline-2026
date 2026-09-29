"""Матрицы дуг решателя равны обратному вызову через `travel.leg` — на всех парах узлов."""

import pytest

from bee_routing import settings
from bee_routing.arcs import group_matrices
from bee_routing.baseline import new_states
from bee_routing.economy import tariffs
from bee_routing.travel import leg

from .conftest import needs_data


@needs_data
@pytest.mark.parametrize("start", ["office", "home"])
def test_group_matrices_match_leg(region, start):
    """Время и цена каждой дуги совпадают с тем, что считал бы обратный вызов."""
    data, matrices = region
    with settings.use({"options": {"traffic": True}}):
        engineers = settings.effective_engineers(data.engineers)
        matrices.adopt(engineers)
        states = new_states(engineers, start)
        conf = tariffs()
        rub_min, rub_km = int(conf["travel_rub_per_min"]), float(conf["car_rub_per_km"])
        n_veh = len(engineers)
        node_point = [states[e.id].position for e in engineers] + [r.id for r in data.requests] + [None]
        service = [0] * n_veh + [r.duration_min for r in data.requests] + [0]
        end = len(node_point) - 1
        seen = set()
        for eng in engineers:
            key = tuple(t.value for t in eng.transports)
            if key in seen:
                continue
            seen.add(key)
            time_m, cost_m = group_matrices(eng, node_point, service, matrices, rub_min, rub_km)
            for a in range(len(node_point)):
                for b in range(len(node_point)):
                    if a == end or b == end:
                        assert cost_m[a][b] == 0
                        assert time_m[a][b] == service[a]
                        continue
                    road = leg(eng, node_point[a], node_point[b], matrices) if a != b else None
                    minutes = road.minutes if road else 0
                    expected_cost = int(minutes * rub_min + (road.km * rub_km if road and road.mode.value == "car" else 0))
                    assert time_m[a][b] == service[a] + minutes, (a, b, key)
                    assert cost_m[a][b] == expected_cost, (a, b, key)


@needs_data
def test_unknown_point_uses_estimate(region):
    """Узел, которого нет в таблицах, считается запасной оценкой — как в `leg`."""
    data, matrices = region
    eng = data.engineers[0]
    matrices.register("x-new", data.office.lat + 0.01, data.office.lon + 0.01)
    node_point = ["office", "x-new", data.requests[0].id, None]
    service = [0, 20, 30, 0]
    with settings.use(None):
        time_m, cost_m = group_matrices(eng, node_point, service, matrices, 10, 5.0)
        road = leg(eng, "office", "x-new", matrices)
    assert time_m[0][1] == road.minutes
    assert cost_m[0][1] == int(road.minutes * 10 + (road.km * 5.0 if road.mode.value == "car" else 0))
    assert time_m[1][2] == 20 + leg(eng, "x-new", data.requests[0].id, matrices).minutes
