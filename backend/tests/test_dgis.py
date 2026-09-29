"""Клиент 2ГИС: блоки, бюджет, разбор ответа, отсутствие хранения ответов."""

from datetime import date

import pytest

from bee_routing import dgis


class FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self) -> dict:
        return self._payload


class FakeHttp:
    """Отвечает как 2ГИС 16.09.2026: время старта в ответе не возвращается."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def post(self, url, params=None, json=None, timeout=None):
        self.calls.append({"url": url, "params": params, "json": json})
        starts = json.get("start_time")
        starts = starts if isinstance(starts, list) else [starts]
        routes = []
        for i, s in enumerate(json["sources"]):
            for t in json["targets"]:
                for k, _ in enumerate(starts):
                    routes.append({
                        "source_id": s, "target_id": t, "status": "OK",
                        "distance": 1000, "duration": 60 * (1 + i + t + k),
                    })
        return FakeResponse(200, {"routes": routes})


def coords(n: int) -> list[tuple[float, float]]:
    return [(55.6 + i * 0.001, 37.6 + i * 0.001) for i in range(n)]


def client(tmp_path, budget=1000, http=None):
    usage = dgis.Usage(tmp_path / "usage.json")
    return dgis.DgisMatrix("KEY", budget, usage, http or FakeHttp())


def test_units_count_pairs_and_starts():
    assert dgis.units_for(3, 4) == 12
    assert dgis.units_for(3, 4, 3) == 36
    assert dgis.units_for(3, 4, 0) == 12


def test_msk_converted_to_utc():
    assert dgis.msk_to_rfc3339(date(2026, 9, 22), 19) == "2026-09-22T16:00:00Z"
    assert dgis.msk_to_rfc3339(date(2026, 9, 22), 1) == "2026-09-21T22:00:00Z"


def test_body_for_car_statistics_and_transit():
    body, order = dgis.build_body(coords(5), [0, 1], [3, 4], "car", ["A"], "statistics")
    assert order == [0, 1, 3, 4]
    assert body["sources"] == [0, 1] and body["targets"] == [2, 3]
    assert body["type"] == "statistics" and body["start_time"] == "A"
    with pytest.raises(ValueError):
        dgis.build_body(coords(5), [0], [1], "car", ["A", "B"], "statistics")
    assert body["transport"] == "driving"
    transit, _ = dgis.build_body(coords(5), [0], [1], "transit", ["A"], "statistics")
    assert "type" not in transit and transit["start_time"] == "A"
    assert transit["public_transport_params"] == {"enable_schedule": True}


def test_statistics_without_start_is_refused():
    with pytest.raises(ValueError):
        dgis.build_body(coords(3), [0], [1], "car", None, "statistics")


def test_big_matrix_split_into_sync_blocks(tmp_path):
    http = FakeHttp()
    c = client(tmp_path, budget=10_000, http=http)
    legs = c.matrix(coords(60), list(range(30)), list(range(30, 60)), "car", ["A"])
    assert len(http.calls) == 4  # 25+5 источников × 25+5 целей
    assert all(len(call["json"]["sources"]) <= 25 for call in http.calls)
    assert len(legs) == 900
    assert {(leg.source, leg.target) for leg in legs} == {
        (s, t) for s in range(30) for t in range(30, 60)
    }
    assert c.usage.spent == 900


def test_each_start_time_is_its_own_request(tmp_path):
    http = FakeHttp()
    c = client(tmp_path, http=http)
    legs = c.matrix(coords(5), [0, 1], [2, 3, 4], "car", ["T10", "T13", "T19"])
    assert len(http.calls) == 3
    assert [call["json"]["start_time"] for call in http.calls] == ["T10", "T13", "T19"]
    assert len(legs) == 18 and c.usage.spent == 18
    assert {leg.start for leg in legs} == {"T10", "T13", "T19"}


def test_budget_checked_before_request(tmp_path):
    http = FakeHttp()
    c = client(tmp_path, budget=10, http=http)
    with pytest.raises(dgis.BudgetExceeded):
        c.matrix(coords(8), [0, 1, 2], [3, 4, 5, 6], "car", ["A"])
    assert http.calls == [] and c.usage.spent == 0


def test_error_status_raises_and_spends_nothing(tmp_path):
    class Denied(FakeHttp):
        def post(self, url, **kwargs):
            return FakeResponse(403, text="key is not allowed")

    c = client(tmp_path, http=Denied())
    with pytest.raises(dgis.DgisError):
        c.matrix(coords(3), [0], [1, 2], "car", ["A"])
    assert c.usage.spent == 0


def test_failed_pair_has_no_duration(tmp_path):
    class Partial(FakeHttp):
        def post(self, url, **kwargs):
            return FakeResponse(200, {"routes": [
                {"source_id": 0, "target_id": 1, "status": "ROUTE_NOT_FOUND",
                 "distance": 0, "duration": 0},
            ]})

    legs = client(tmp_path, http=Partial()).matrix(coords(2), [0], [1], "car", ["A"])
    assert legs[0].status == "ROUTE_NOT_FOUND" and legs[0].minutes is None


def test_usage_file_keeps_counts_not_answers(tmp_path):
    c = client(tmp_path)
    c.matrix(coords(4), [0, 1], [2, 3], "car", ["2026-09-22T16:00:00Z"])
    saved = (tmp_path / "usage.json").read_text()
    assert '"units_spent": 4' in saved
    assert "duration" not in saved and "routes" not in saved


def test_next_weekday_is_in_future():
    assert dgis.next_weekday(1, date(2026, 9, 16)) == date(2026, 9, 22)  # среда → вторник
    assert dgis.next_weekday(1, date(2026, 9, 22)) == date(2026, 9, 29)  # вторник → следующий


def test_keys_are_spent_in_order_and_counted_apart(tmp_path):
    conf = tmp_path / "2gis.json"
    conf.write_text('{"keys": [{"key": "AAAAAAAA-1", "budget_units": 10}, {"key": "BBBBBBBB-2", "budget_units": 10}]}')
    usage = dgis.Usage(tmp_path / "usage.json")
    usage.data["by_key"] = {}
    key, budget = dgis.load_key(conf, usage)
    assert key == "AAAAAAAA-1" and budget == 10
    first = dgis.DgisMatrix(key, budget, usage, FakeHttp())
    first.matrix(coords(4), [0, 1], [2, 3], "car", ["X"])
    first.matrix(coords(4), [0, 1], [2, 3], "car", ["X"])
    assert first.left == 2
    # Первому не хватает на четыре пары — следующий ключ, со своим счётом.
    key, _ = dgis.load_key(conf, usage, need=4)
    assert key == "BBBBBBBB-2"
    assert dgis.DgisMatrix(key, 10, usage, FakeHttp()).left == 10
    assert dgis.total_left(conf, usage) == 12
    saved = (tmp_path / "usage.json").read_text()
    assert "AAAAAAAA-1" not in saved and '"AAAAAAAA": 8' in saved


def test_old_single_key_config_still_reads(tmp_path):
    conf = tmp_path / "2gis.json"
    conf.write_text('{"key": "OLD", "budget_units": 500}')
    assert dgis.load_keys(conf) == [("OLD", 500)]
