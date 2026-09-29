"""Готовые планы и остановка поиска по застою."""

import time

from fastapi.testclient import TestClient

from bee_routing import ready, settings
from bee_routing.api import app
from bee_routing.loader import load_dataset, load_matrices
from bee_routing.solver import solve

from .conftest import REGIONS, needs_data

client = TestClient(app)


@needs_data
def test_stall_stops_before_budget():
    """Восток сходится за секунды: с порогом застоя поиск кончается раньше потолка."""
    data, matrices = load_dataset(REGIONS[0]), load_matrices(REGIONS[0])
    with settings.use({"options": {"portfolio": False, "stall_s": 1.0}}):
        started = time.perf_counter()
        plan, _ = solve(data, matrices, time_limit_s=30)
        elapsed = time.perf_counter() - started
    assert elapsed < 30
    assert plan.timing["search_s"] < 30
    assert plan.timing["first_solution_s"] <= plan.timing["last_improvement_s"]
    assert plan.timing["budget_s"] == 30


@needs_data
def test_key_ignores_budget():
    """Бюджет и порог застоя в ключ не входят, прочие настройки — входят."""
    base = ready.key_of("vostok", "home", {"options": {"time_limit_s": 4, "stall_s": 1.5}})
    assert base == ready.key_of("vostok", "home", {"options": {"time_limit_s": 16, "stall_s": 0}})
    assert base == ready.key_of("vostok", "home", None)
    assert base == ready.key_of("vostok", "home", settings.defaults())  # экран шлёт форму целиком
    assert base != ready.key_of("vostok", "home", {"crews": {"lebedev": {"transports": ["car"]}}})
    assert base != ready.key_of("vostok", "office", None)
    assert base != ready.key_of("vostok", "home", {"options": {"breaks": False}})


@needs_data
def test_plan_is_served_ready_second_time():
    """Второй POST /plan с теми же настройками отдаёт готовый план, а не считает заново."""
    body = {"dataset_id": REGIONS[0], "algorithm": "solver",
            "settings": {"options": {"portfolio": False, "time_limit_s": 2}}}
    first = client.post("/plan", json=body).json()
    started = time.perf_counter()
    second = client.post("/plan", json=body).json()
    assert time.perf_counter() - started < 1.0
    assert second["id"] == first["id"]
    status = client.get("/ready").json()
    assert any(row["plan_id"] == first["id"] for row in status["ready"])

    fresh = client.post("/plan", json={**body, "fresh": True}).json()
    assert fresh["id"] != first["id"]


@needs_data
def test_refine_keeps_better_plan():
    """Доводка заменяет план только тем, что лучше по порядку выбора."""
    overrides = {"options": {"portfolio": False, "time_limit_s": 1}}
    ids = iter(f"r{i}" for i in range(10))
    quick = ready.get_or_build(REGIONS[0], "home", overrides, 1, lambda: next(ids), refine=False)
    future = ready.refine_later(REGIONS[0], "home", overrides, lambda: next(ids), budget_s=2)
    assert future is not None
    future.result()
    entry = ready._entries[ready.key_of(REGIONS[0], "home", overrides)]
    assert entry.budget_s == 2
    assert entry.builds == 2
    from bee_routing.portfolio import rank

    assert rank(entry.plan) <= rank(quick)
    # Доведённый ключ второй раз в очередь не встаёт.
    assert ready.refine_later(REGIONS[0], "home", overrides, lambda: next(ids), budget_s=2) is None


@needs_data
def test_request_does_not_wait_for_refine():
    """Идёт доводка, а быстрый план есть: запрос с большим бюджетом отдаёт быстрый сразу."""
    overrides = {"options": {"portfolio": False, "time_limit_s": 1, "breaks": False}}
    ids = iter(f"w{i}" for i in range(10))
    quick = ready.get_or_build(REGIONS[0], "home", overrides, 1, lambda: next(ids), refine=False)
    future = ready.refine_later(REGIONS[0], "home", overrides, lambda: next(ids), budget_s=6)
    assert future is not None
    time.sleep(0.2)  # доводка взяла ключ
    started = time.perf_counter()
    served = ready.get_or_build(REGIONS[0], "home", overrides, 6, lambda: next(ids))
    assert time.perf_counter() - started < 1.0
    assert served.id == quick.id
    future.result()
