"""«На чём ехать»: дата расписания, разбор ответа 2ГИС, кэш, отказы словами. Сеть подменена."""

from datetime import date

from bee_routing import transit_trip as tt
from bee_routing.dgis import Usage
from bee_routing.solver import solve

from .conftest import needs_data

ANSWER = [{
    "total_duration": 2760, "transfer_count": 1, "total_walkway_distance": "пешком 12 мин",
    "schedules": [{"precise_time": "10:21", "type": "precise"}, {"precise_time": "10:36", "type": "precise"}],
    "movements": [
        {"type": "walkway", "moving_duration": 240, "waiting_duration": 0, "waypoint": {"name": ""}},
        {"type": "passage", "moving_duration": 300, "waiting_duration": 120,
         "waypoint": {"name": "Мебельная фабрика"}, "routes": [{"names": ["891", "891"], "subtype": "bus"}, {"names": ["891"], "subtype": "bus"}]},
        {"type": "crossing", "moving_duration": 360, "waiting_duration": 0, "waypoint": {"name": "Бирюлёво-Тов."}},
        {"type": "passage", "moving_duration": 1380, "waiting_duration": 60, "waypoint": {"name": "Бирюлёво-Тов."},
         "routes": [{"names": ["Павелецкий вокзал — Домодедово"], "subtype": "suburban_train"}]},
        {"type": "passage", "moving_duration": 480, "waiting_duration": 90, "routes": None,
         "waypoint": {"name": "Кантемировская", "subtype": "metro"},
         "metro": {"line_name": "Замоскворецкая линия", "ui_direction_suggest": "в сторону станции «Алма-Атинская»",
                   "ui_station_count": "2 станции", "exit_entrance_number": "7"}},
        {"type": "walkway", "moving_duration": 0},
    ],
}]


class FakeResponse:
    status_code = 200

    def json(self):
        return ANSWER


class FakeHttp:
    def __init__(self):
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append(kwargs["json"])
        return FakeResponse()


def test_trip_date_is_next_same_weekday():
    # День заказчика — понедельник; сегодня суббота 19.09.2026 → понедельник 21.09.
    assert tt.trip_date("2026-08-17", date(2026, 9, 19)) == date(2026, 9, 21)
    # Сегодня тот же день недели — берётся следующая неделя: час мог уже пройти.
    assert tt.trip_date("2026-08-17", date(2026, 9, 21)) == date(2026, 9, 28)


def test_parse_keeps_lines_waits_and_departures():
    from datetime import datetime

    options = tt.parse(ANSWER, datetime(2026, 9, 21, 10, 0))
    first = options[0]
    assert first.total_min == 46 and first.arrive == "10:46" and first.transfers == 1
    assert first.departures == ["10:21", "10:36"]
    kinds = [leg.kind for leg in first.legs]
    assert kinds == ["walk", "ride", "transfer", "ride", "ride"], "пустой пеший хвост не показывается"
    metro = first.legs[4]
    assert metro.vehicle == "метро" and metro.lines == ["Замоскворецкая линия"]
    assert metro.hint == "в сторону станции «Алма-Атинская», 2 станции, выход 7"
    bus, train = first.legs[1], first.legs[3]
    assert bus.vehicle == "автобус" and bus.lines == ["891"] and bus.wait_min == 2
    assert train.vehicle == "электричка" and train.place == "Бирюлёво-Тов."


@needs_data
def test_trip_asks_once_and_counts_units(region, tmp_path, monkeypatch):
    data, matrices = region
    plan, _ = solve(data, matrices, plan_id="p-transit", time_limit_s=1)
    route = next(r for r in plan.routes if len(r.stops) >= 2)
    usage = Usage(tmp_path / "usage.json")
    monkeypatch.setattr(tt, "Usage", lambda: usage)
    monkeypatch.setattr(tt, "load_key", lambda usage=None: ("KEYKEYKEY1", 1000))
    monkeypatch.setattr(tt, "_km", lambda a, b: 10.0)
    tt._cache.clear()
    http = FakeHttp()
    second = route.stops[1]
    got = tt.trip(plan, data, route.engineer_id, second.request_id, http=http, today=date(2026, 9, 19))
    again = tt.trip(plan, data, route.engineer_id, second.request_id, http=http, today=date(2026, 9, 19))
    assert got.options and got.options[0].legs and again == got
    assert len(http.calls) == 1, "второй раз путь берётся из памяти"
    assert usage.spent_by("KEYKEYKEY1") == 1
    prev = next(r for r in data.requests if r.id == route.stops[0].request_id)
    assert http.calls[0]["source"]["point"] == {"lat": prev.lat, "lon": prev.lon}
    assert got.origin == prev.address
    assert got.plan_arrive == second.arrive, "подсказка знает приезд по плану и сверяет с ним путь"


@needs_data
def test_far_points_and_missing_key_say_why(region, monkeypatch):
    data, matrices = region
    plan, _ = solve(data, matrices, plan_id="p-transit-2", time_limit_s=1)
    route = next(r for r in plan.routes if r.stops)
    stop = route.stops[0]
    tt._cache.clear()
    monkeypatch.setattr(tt, "_km", lambda a, b: 80.0)
    far = tt.trip(plan, data, route.engineer_id, stop.request_id, http=FakeHttp())
    assert not far.options and "50 км" in far.note
    monkeypatch.setattr(tt, "_km", lambda a, b: 10.0)
    monkeypatch.setattr(tt, "load_key", lambda usage=None: (None, 1000))
    none = tt.trip(plan, data, route.engineer_id, stop.request_id, http=FakeHttp())
    assert not none.options and "Ключа" in none.note


@needs_data
def test_baseline_stop_keeps_mode_it_was_timed_with(region):
    """Остановка базового плана несёт тот вид транспорта, по которому посчитаны её минуты."""
    from bee_routing.baseline import build_baseline
    from bee_routing.checks import to_min
    from bee_routing.travel import leg

    data, matrices = region
    plan, _ = build_baseline(data, matrices, plan_id="p-mode")
    engineers = {e.id: e for e in data.engineers}
    checked = 0
    for route in plan.routes:
        eng = engineers[route.engineer_id]
        for prev, stop in zip(route.stops, route.stops[1:], strict=False):
            road = leg(eng, prev.request_id, stop.request_id, matrices, to_min(stop.depart_prev))
            assert stop.mode == road.mode, f"{eng.id} → {stop.request_id}"
            checked += 1
    assert checked
