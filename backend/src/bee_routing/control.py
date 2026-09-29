"""Контрольное распределение заказчика как план: чтобы сравнивать с ним честно.

Эксперты назвали контрольный файл ориентиром: так распределили заявки
диспетчеры 17 августа. Порядка визитов в нём нет, поэтому он восстанавливается
по началу окон, а дорога считается нашей же моделью — той, что и у решателя.
Проверки при этом не останавливают сборку: контрольный план обязан быть
показан таким, каким он был, с просрочками и перегруженными окнами,
а не таким, каким его починил бы наш алгоритм.
"""

from __future__ import annotations

from datetime import UTC, datetime

from .baseline import append, new_states
from .checks import visit_times
from .economy import summarize
from .matrices import Matrices
from .metrics import compute_metrics
from .models import Dataset, Plan, Unassigned
from .travel import leg


def control_plan(dataset: Dataset, matrices: Matrices, *, plan_id: str = "control") -> Plan:
    """План по контрольному файлу: кому отдали, в порядке окон, с нашей дорогой."""
    by_id = {req.id: req for req in dataset.requests}
    states = new_states(dataset.engineers, "office")
    given: dict[str, list] = {eng.id: [] for eng in dataset.engineers}
    seen: set[str] = set()
    for row in dataset.control:
        if row.request_id in by_id and row.engineer_id in given and row.request_id not in seen:
            given[row.engineer_id].append(by_id[row.request_id])
            seen.add(row.request_id)
    for eng in dataset.engineers:
        state = states[eng.id]
        for req in sorted(given[eng.id], key=lambda r: (r.window_start, r.window_end, r.id)):
            road = leg(eng, state.position, req.id, matrices, state.clock)
            append(state, req, visit_times(req, state.clock + road.minutes), road.minutes, road.km, road.mode)
    unassigned = [
        Unassigned(request_id=req.id, reason="В контрольном файле заявка не отдана ни одной бригаде",
                   reason_code="no_engineer")
        for req in dataset.requests if req.id not in seen
    ]
    routes = [states[eng.id].to_route() for eng in dataset.engineers]
    plan = Plan(
        id=plan_id, dataset_id=dataset.id, algorithm="control",
        created_at=datetime.now(UTC).isoformat(timespec="seconds"), start="office",
        routes=routes, unassigned=unassigned, metrics=compute_metrics(routes, unassigned),
    )
    plan.economy = summarize(plan, dataset)
    return plan
