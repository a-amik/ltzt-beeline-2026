"""Генератор нагрузки: регион растёт из настоящего и решается как настоящий."""

from bee_routing import settings
from bee_routing.loadgen import build_matrices, scale_id, synthesize
from bee_routing.matrices import Matrices
from bee_routing.models import Dataset
from bee_routing.solver import solve

from .conftest import REGIONS, needs_data


@needs_data
def test_synthetic_region_is_valid_and_reproducible():
    """Заданный размер, те же окна и навыки, что у образца, и тот же регион при том же семени."""
    raw = synthesize(REGIONS[0], 40, 6, seed=7)
    data = Dataset.model_validate(raw)
    assert data.id == scale_id(REGIONS[0], 40, 6, 7)
    assert len(data.requests) == 40 and len(data.engineers) == 6
    base = Dataset.model_validate_json(
        (__import__("bee_routing.loader", fromlist=["DATASETS_DIR"]).DATASETS_DIR / f"{REGIONS[0]}.json")
        .read_text(encoding="utf-8")
    )
    windows = {(r.window_start, r.window_end) for r in base.requests}
    assert {(r.window_start, r.window_end) for r in data.requests} <= windows
    assert {s for e in data.engineers for s in e.skills} == {s for e in base.engineers for s in e.skills}
    assert all(e.transports for e in data.engineers)
    assert synthesize(REGIONS[0], 40, 6, seed=7) == raw
    assert synthesize(REGIONS[0], 40, 6, seed=8) != raw


@needs_data
def test_synthetic_region_solves():
    """Запасные матрицы покрывают все точки, и решатель строит по ним план."""
    raw = synthesize(REGIONS[0], 30, 5, seed=3)
    tables = build_matrices(raw)
    assert set(tables) == {"car", "bike", "foot", "transit"}
    n = len(tables["car"]["ids"])
    assert n == 1 + 30 + 5  # офис, заявки, дома
    assert all(len(row) == n for row in tables["car"]["duration_min"])
    assert tables["car"]["duration_min"][0][0] == 0
    assert tables["car"]["duration_min"][0][1] <= tables["foot"]["duration_min"][0][1]

    data = Dataset.model_validate(raw)
    matrices = Matrices(tables)
    matrices.bind(data)
    with settings.use({"options": {"portfolio": False}}):
        plan, _ = solve(data, matrices, time_limit_s=2)
    assert len(plan.unassigned) < 30
    assert plan.timing["total_s"] > 0
