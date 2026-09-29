"""Портфель стратегий: несколько стартов решателя параллельно за те же секунды.

За три секунды пять стартовых стратегий OR-Tools дают на Юго-востоке разные
планы: 7—9 неназначенных, итог 265—284 тыс. ₽. Какая выиграет на конкретном
дне, заранее не видно, а времени ждать в интерфейсе нет. Поэтому утренний
план считается портфелем: четыре стратегии в отдельных процессах, каждая
с тем же бюджетом времени, берётся лучший по бизнес-порядку — сначала
больше выполненных, затем больше итог дня, затем меньше дороги.

Процессы живут между расчётами (пул поднимается один раз), настройки
запроса и регион уезжают в процесс явно: контекст запроса в дочерний
процесс не переезжает. Внутри процесса портфель выключен, иначе он породил
бы сам себя.

**Через пул едет ранг, а не план.** План на 2 000 заявок — 60 МБ JSON,
и четыре таких через канал процессов стоили 100 секунд из 110 на прогоне
нагрузки. Рабочий процесс кладёт план в файл каталога `spool/` и отдаёт
родителю ранг и путь; родитель читает один файл — лучший — и стирает
остальные. На регионах заказчика (200 КБ) разницы нет, на большом дне
она решающая.
"""

from __future__ import annotations

import os
import tempfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from contextvars import ContextVar
from pathlib import Path

from . import settings
from .matrices import Matrices
from .models import Dataset, Plan

# Четыре стартовые стратегии OR-Tools. Второй решатель, PyVRP (`pyvrp_plan.py`), в портфель не входит:
# замер 19.09.2026 (`search_bench.py`) — по нашей мерке он проигрывает OR-Tools на всех трёх регионах
# и на 4, и на 60 секундах (в его цели нет ни обеда, ни цены работы сверх нормы), хотя маршруты у него
# короче. Зовётся по имени, `strategy="PYVRP"`, — для замера.
STRATEGIES = ("PATH_CHEAPEST_ARC", "SAVINGS", "GLOBAL_CHEAPEST_ARC", "LOCAL_CHEAPEST_INSERTION")

SPOOL = Path(tempfile.gettempdir()) / "bee-portfolio"

# Пулов два. Фоновая доводка готового плана (`ready.py`) занимает процессы на
# десятки секунд; в общем пуле расчёт по нажатию вставал за ней в очередь —
# на дне в 250 заявок быстрый план ждал 12 секунд. Доводка объявляет себя
# переменной `BACKGROUND` и идёт своим пулом; там же, отдельным процессом,
# идёт поиск с большим соседством: в потоке сервера он держал бы GIL, и готовый
# план отдавался бы за 0,4 секунды вместо 0,006.
BACKGROUND: ContextVar[bool] = ContextVar("bee_background", default=False)
_pools: dict[bool, ProcessPoolExecutor] = {}


def _executor() -> ProcessPoolExecutor:
    background = BACKGROUND.get()
    if background not in _pools:
        _pools[background] = ProcessPoolExecutor(
            max_workers=min(len(STRATEGIES), max(2, (os.cpu_count() or 2) - 1)))
    return _pools[background]


def _lns_worker(dataset_id: str, overrides: dict, plan_path: str, budget_s: float) -> str:
    """Доводка большим соседством в отдельном процессе; ответ — файл с планом."""
    from .lns import refine
    from .loader import load_dataset, load_matrices

    data, matrices = load_dataset(dataset_id), load_matrices(dataset_id)
    plan = Plan.model_validate_json(Path(plan_path).read_text(encoding="utf-8"))
    for event in plan.history:
        if event.request is not None:
            matrices.register(event.request.id, event.request.lat, event.request.lon)
    with settings.use(overrides):
        better = refine(plan, data, matrices, budget_s=budget_s)
    better.settings = {}
    Path(plan_path).write_text(better.model_dump_json(), encoding="utf-8")
    return plan_path


def refine_in_process(plan: Plan, dataset: Dataset, budget_s: float) -> Plan | None:
    """Довести план в процессе пула; None — пул недоступен, доводите на месте."""
    overrides = settings.current()
    SPOOL.mkdir(parents=True, exist_ok=True)
    path = SPOOL / f"{plan.id}-lns-{os.getpid()}.json"
    try:
        path.write_text(plan.model_dump_json(), encoding="utf-8")
        done = _executor().submit(_lns_worker, dataset.id, overrides, str(path), budget_s).result()
        better = Plan.model_validate_json(Path(done).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — пул не поднялся или процесс упал: доводка не обязательна
        return None
    finally:
        path.unlink(missing_ok=True)
    better.settings = settings.current()
    return better




def _worker(dataset_id: str, overrides: dict, strategy: str, plan_id: str, start: str,
            time_limit_s: int | None) -> tuple[tuple[int, int, int, int], str]:
    """Один запуск решателя одной стратегией; ответ — ранг плана и файл с ним."""
    from .loader import load_dataset, load_matrices
    from .solver import solve

    data, matrices = load_dataset(dataset_id), load_matrices(dataset_id)
    with settings.use(overrides):
        plan, _ = solve(data, matrices, plan_id=plan_id, start=start, time_limit_s=time_limit_s,
                        strategy=strategy)
    plan.settings = {}
    SPOOL.mkdir(parents=True, exist_ok=True)
    path = SPOOL / f"{plan_id}-{strategy}-{os.getpid()}.json"
    path.write_text(plan.model_dump_json(), encoding="utf-8")
    return rank(plan), str(path)


def rank(plan: Plan) -> tuple:
    """Порядок выбора: меньше потеряно по приоритету, меньше неназначенных, больше итог, меньше дорога.

    Первое число — надбавки ступеней у неназначенных (`solver.finish` кладёт его
    в `timing`): план, бросивший аварию, хуже плана, бросившего два ремонта, —
    письменный ответ Билайна, п. 15. Пока бригад хватает, оно ноль, и порядок прежний.
    """
    from .objective import key

    return key(plan)  # порядок целей — настройка `objective_order`


def solve_portfolio(dataset: Dataset, matrices: Matrices, *, plan_id: str, start: str,
                    time_limit_s: int | None) -> Plan | None:
    """Прогнать стратегии параллельно и вернуть лучший план; None — портфель недоступен."""
    overrides = settings.current()
    overrides.setdefault("options", {})["portfolio"] = False
    try:
        pool = _executor()
        futures = {pool.submit(_worker, dataset.id, overrides, name, plan_id, start, time_limit_s): i
                   for i, name in enumerate(STRATEGIES)}
        results = [(*f.result(), futures[f]) for f in as_completed(futures)]
    except Exception:  # noqa: BLE001 — пул не поднялся: считаем одной стратегией
        return None
    if not results:
        return None
    # При равном ранге побеждает стратегия, стоящая раньше в списке, а не процесс, закончивший первым.
    _, best_path, _ = min(results, key=lambda r: (r[0], r[2]))
    best = Plan.model_validate_json(Path(best_path).read_text(encoding="utf-8"))
    for _, path, _ in results:
        Path(path).unlink(missing_ok=True)
    best.settings = settings.current()
    matrices.adopt(settings.effective_engineers(dataset.engineers))
    for event in best.history:
        if event.request is not None:
            matrices.register(event.request.id, event.request.lat, event.request.lon)
    return best
