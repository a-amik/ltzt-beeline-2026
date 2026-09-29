"""Отчёт по исполнителям: таблицы и страница «О проекте» читают один и тот же прогон."""

from bee_routing.mileage import markdown
from bee_routing.reports import mileage


def _report() -> dict:
    row = lambda km, stops: {"km": km, "stops": stops}  # noqa: E731
    totals = {"engineers": 1, "km": 12.5, "on_time": 3, "unassigned": 0, "requests": 3}
    return {
        "date": "2026-09-29", "commit": "abc1234",
        "plans": [{"key": "control", "label": "Контроль"}, {"key": "baseline", "label": "Базовый"},
                  {"key": "solver", "label": "Наш план"}],
        "zones": [{"id": "z", "name": "Участок", "start": "home",
                   "engineers": [{"id": "a", "name": "Бригада А", "control": row(12.5, 3), "baseline": row(0, 0),
                                  "solver": row(12.5, 3)}],
                   "totals": {"control": totals, "baseline": {**totals, "engineers": 0, "km": 0}, "solver": totals}}],
    }


def test_markdown_lists_each_engineer_and_totals():
    text = markdown(_report())
    assert "| Бригада А | 12,5 | 3 | — | — | 12,5 | 3 |" in text
    assert "| Участок | Наш план | 1 | 12,5 | 3 | 0 |" in text


def test_reports_page_reads_saved_run(tmp_path):
    import json
    (tmp_path / "mileage").mkdir()
    (tmp_path / "mileage" / "report.json").write_text(json.dumps(_report(), ensure_ascii=False), encoding="utf-8")
    assert mileage(tmp_path)["zones"][0]["name"] == "Участок"
    assert mileage(tmp_path / "нет") is None
