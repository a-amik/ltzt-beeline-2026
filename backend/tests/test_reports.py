"""Раздел «Отчёты»: сервер отдаёт готовые прогоны из `data/`, ничего не пересчитывая."""

import json

from fastapi.testclient import TestClient

from bee_routing.api import app
from bee_routing.reports import simulation

client = TestClient(app)


def test_reports_have_three_pages():
    """GET /reports отдаёт сравнение с контролем, имитацию и масштаб из файлов прогона
    (и прогоны новых сценариев, поиска и нагрузки — для страниц моделей и безопасности)."""
    body = client.get("/reports").json()
    assert set(body) >= {"benchmark", "simulation", "scale"}
    bench = body["benchmark"]
    assert bench["kpis"] and all(region["rows"] for region in bench["regions"])
    assert {row["key"] for row in bench["regions"][0]["rows"]} >= {"control"}
    assert any(row["requests"] >= 2000 for row in body["scale"]["rows"])


def test_simulation_averages_seeds(tmp_path):
    """Имитация — среднее по зёрнам; «на завтра» из всех файлов участка."""
    folder = tmp_path / "simulation"
    folder.mkdir()
    for seed, (static, offer) in enumerate([(10, 20), (30, 40)], start=1):
        runs = [{"policy": "static", "kpis": {"on_time": static}}, {"policy": "offer", "kpis": {"on_time": offer}}]
        (folder / f"east-{seed}-offer.json").write_text(json.dumps({"runs": runs, "kpi_labels": [{"key": "on_time"}]}))
    region = simulation(tmp_path)["regions"][0]
    by_policy = {run["policy"]: run for run in region["runs"]}
    assert region["seeds"] == 2
    assert by_policy["static"]["kpis"]["on_time"] == 20
    assert by_policy["offer"]["kpis"]["on_time"] == 30
    assert simulation(tmp_path / "missing") is None
