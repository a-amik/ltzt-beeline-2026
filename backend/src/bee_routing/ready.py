"""Готовые планы: утренний план считается заранее и в фоне, а не по нажатию.

До этого модуля `POST /plan` каждый раз считал план заново, и первая
загрузка экрана стояла столько, сколько задано бюджетом поиска, — четыре
секунды, а до того восемь. Диспетчеру ждать незачем: заявки на утро
известны с вечера, настройки меняются редко, и план по ключу «регион,
старт, настройки» можно посчитать до того, как его спросят.

Устроено так:

1. **Ключ плана — регион, старт и настройки без бюджета времени.** Бюджет
   и порог застоя в ключ не входят: план, посчитанный за 16 секунд с теми
   же правилами, годится и тому, кто просил 4. У записи хранится лучший
   из посчитанных по этому ключу и наибольший бюджет, которым его искали.
2. **Прогрев при старте сервиса.** Отдельная нить считает планы всех
   регионов с настройками по умолчанию: сперва быстрый (бюджет из
   настроек, остановка по застою), следом доводка — весь бюджет
   `REFINE_S` без остановки. Первое открытие экрана получает готовый план
   за время ответа сети.
   Доводка — это решатель с полным бюджетом и следом поиск с большим
   соседством (`lns.py`, `LNS_S` секунд): решатель двигает визиты по одному,
   LNS перекладывает район целиком, и на Юго-востоке за 20 секунд добирает
   обе неназначенные заявки при меньшем пробеге.
3. **Доводка в фоне после любого быстрого плана.** Запрос с новыми
   настройками считается быстро, отдаётся, и тут же ставится в очередь
   доводка. Второй запрос по тому же ключу — от кнопки «улучшить» на
   экране или от следующего диспетчера — ждёт её, а не считает третий
   раз. Заменяет план только результат лучше по бизнес-порядку
   (`portfolio.rank`): больше выполненных, больше итог, меньше дорога.
4. **Одна доводка за раз.** Портфель стратегий и так занимает все ядра;
   две доводки рядом замедлили бы друг друга и быстрый запрос с ними.
5. **Свежий расчёт — по просьбе.** `fresh=True` в теле запроса обходит
   запись; для прогонов и сравнения времени, не для экрана.

Пересчёты после событий дня (`/replan`, `/assign`) сюда не ходят: у них
своё состояние, и ключа «утро» у них нет.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass, field

from . import settings
from .models import Plan
from .portfolio import rank

log = logging.getLogger(__name__)

REFINE_S = 16
# Доводка большим соседством поверх решателя: только в фоне, экран её не ждёт. Замер: на Юго-востоке
# главный выигрыш приходит между 40-й и 60-й секундой. Переменная окружения — для тестов и слабых машин:
# минута LNS в фоновом процессе отнимает процессор у всего, что считается рядом с бюджетом в секунды.
LNS_S = int(os.environ.get("BEE_REFINE_LNS_S", "60"))
DROP_FROM_KEY = ("time_limit_s", "stall_s", "lns_s")


@dataclass
class Ready:
    """Лучший план по ключу и наибольший бюджет, которым его искали."""

    plan: Plan
    budget_s: int
    builds: int = 1
    key: str = ""
    dataset_id: str = ""
    extra: dict = field(default_factory=dict)


_entries: dict[str, Ready] = {}
_inflight: dict[str, Future] = {}
_lock = threading.Lock()
_epoch = 0  # растёт при `clear()`: расчёт, начатый до сброса, в новое хранилище не пишет
_pool: ThreadPoolExecutor | None = None


def _executor() -> ThreadPoolExecutor:
    global _pool
    if _pool is None:
        _pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ready")
    return _pool


def key_of(dataset_id: str, start: str, overrides: dict | None) -> str:
    """Ключ записи: регион, старт и действующие настройки без бюджета времени.

    Считается по настройкам поверх допущений, а не по присланным
    переопределениям: экран шлёт форму целиком, прогрев — ничего, и оба
    обязаны попасть в одну запись, пока значения совпадают.
    """
    clean = settings.sanitize(overrides)
    tree = deepcopy(settings._merge(clean))
    options = tree.get("options") or {}
    for name in DROP_FROM_KEY:
        options.pop(name, None)
    payload = {"tree": tree, "crews": clean.get("crews") or {}}
    digest = hashlib.sha1(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]
    return f"{dataset_id}|{start}|{digest}"


def _better(candidate: Plan, current: Plan) -> bool:
    return rank(candidate) < rank(current)


def _store(key: str, dataset_id: str, plan: Plan, budget_s: int, epoch: int | None = None) -> Ready:
    with _lock:
        if epoch is not None and epoch != _epoch:
            # Хранилище сбросили, пока шёл расчёт (минута доводки — долго): результат никому не нужен.
            return Ready(plan=plan, budget_s=budget_s, key=key, dataset_id=dataset_id)
        entry = _entries.get(key)
        if entry is None:
            entry = _entries[key] = Ready(plan=plan, budget_s=budget_s, key=key, dataset_id=dataset_id)
        else:
            entry.builds += 1
            entry.budget_s = max(entry.budget_s, budget_s)
            if _better(plan, entry.plan):
                entry.plan = plan
        return entry


def compute(dataset_id: str, start: str, overrides: dict | None, budget_s: int,
            stall_s: float | None, plan_id: str) -> Plan:
    """Посчитать план решателем с заданным бюджетом; настройки — поверх запроса."""
    from .loader import load_dataset, load_matrices
    from .solver import solve

    merged = deepcopy(settings.sanitize(overrides))
    options = merged.setdefault("options", {})
    options["time_limit_s"] = budget_s
    if stall_s is not None:
        options["stall_s"] = stall_s
    if budget_s >= REFINE_S:
        # Доводка идёт в фоне, и секунд у неё больше: после решателя план ломается
        # и чинится кусками (`lns.py`). Бюджет в ключ готового плана не входит.
        options.setdefault("lns_s", LNS_S)
    from .portfolio import BACKGROUND

    data, matrices = load_dataset(dataset_id), load_matrices(dataset_id)
    token = BACKGROUND.set(budget_s >= REFINE_S)  # доводка идёт своим пулом и расчёту по нажатию не мешает
    try:
        with settings.use(merged):
            built, _ = solve(data, matrices, plan_id=plan_id, start=start)
    finally:
        BACKGROUND.reset(token)
    return built


def _run_locked(key: str, dataset_id: str, start: str, overrides: dict | None, budget_s: int,
                stall_s: float | None, plan_id: str, epoch: int | None = None) -> tuple[Ready, Plan]:
    """Один расчёт по ключу; параллельный запрос того же ключа ждёт его.

    Возвращает запись и посчитанный план: запись может держать план лучше
    посчитанного, а свежему расчёту нужен именно его результат.
    """
    with _lock:
        future = _inflight.get(key)
        if future is None:
            future = _inflight[key] = Future()
            owner = True
        else:
            owner = False
    if not owner:
        future.result()
        with _lock:
            entry = _entries[key]
        return entry, entry.plan
    try:
        epoch = _epoch if epoch is None else epoch
        if epoch != _epoch:
            raise RuntimeError("хранилище готовых планов сброшено до начала расчёта")
        plan = compute(dataset_id, start, overrides, budget_s, stall_s, plan_id)
        entry = _store(key, dataset_id, plan, budget_s, epoch)
        future.set_result(entry)
        return entry, plan
    except BaseException as error:
        future.set_exception(error)
        raise
    finally:
        with _lock:
            _inflight.pop(key, None)


def refine_later(dataset_id: str, start: str, overrides: dict | None, new_id: Callable[[], str],
                 budget_s: int = REFINE_S) -> Future | None:
    """Поставить доводку в очередь; уже доведённый ключ второй раз не считается."""
    key = key_of(dataset_id, start, overrides)
    with _lock:
        entry = _entries.get(key)
        if entry is not None and entry.budget_s >= budget_s:
            return None

    queued_at = _epoch  # поставлено в очередь до сброса хранилища — после него не считается

    def job() -> None:
        if queued_at != _epoch:
            return
        try:
            _run_locked(key, dataset_id, start, overrides, budget_s, 0.0, new_id(), epoch=queued_at)
        except Exception:
            log.exception("Доводка плана %s не удалась", key)

    return _executor().submit(job)


def get_or_build(dataset_id: str, start: str, overrides: dict | None, budget_s: int,
                 new_id: Callable[[], str], *, fresh: bool = False, refine: bool = True) -> Plan:
    """Готовый план по ключу или расчёт с последующей доводкой в фоне."""
    key = key_of(dataset_id, start, overrides)
    if fresh:
        _, plan = _run_locked(key, dataset_id, start, overrides, budget_s, None, new_id())
        return plan
    with _lock:
        entry = _entries.get(key)
        pending = _inflight.get(key)
    if entry is not None and entry.budget_s >= budget_s:
        return entry.plan
    if pending is not None and entry is not None:
        # Идёт доводка, а быстрый план уже есть — отдаём его, а не ждём. Ожидание
        # доводки «Всей Москвы» на стенде (4 ядра) шло до пяти минут, запросы
        # занимали все слоты тяжёлых расчётов, и остальным шёл 429 (29.09.2026).
        return entry.plan
    if pending is not None:
        # Кто-то уже считает этот ключ — ждём его, а не считаем второй раз.
        pending.result()
        with _lock:
            entry = _entries.get(key)
        if entry is not None and entry.budget_s >= budget_s:
            return entry.plan
    if entry is not None and refine:
        # Быстрый план есть, просят дольше: это и есть доводка, считаем её сейчас.
        entry, _ = _run_locked(key, dataset_id, start, overrides, budget_s, 0.0, new_id())
        return entry.plan
    entry, _ = _run_locked(key, dataset_id, start, overrides, budget_s, None, new_id())
    if refine and budget_s < REFINE_S:
        refine_later(dataset_id, start, overrides, new_id)
    return entry.plan


def peek(dataset_id: str, start: str, overrides: dict | None) -> Plan | None:
    """Готовый план по ключу, если он есть; ничего не считает."""
    with _lock:
        entry = _entries.get(key_of(dataset_id, start, overrides))
    return entry.plan if entry is not None else None


def warm_up(dataset_ids: list[str], new_id: Callable[[], str], *, block: bool = False) -> threading.Thread | None:
    """Прогрев: планы всех регионов с настройками по умолчанию, быстрый и доведённый."""

    def run() -> None:
        with settings.use(None):
            start = str(settings.option("start") or "office")
            budget = int(settings.option("time_limit_s") or 4)
        waits = []
        for dataset_id in dataset_ids:
            try:
                get_or_build(dataset_id, start, None, budget, new_id, refine=False)
                waits.append(refine_later(dataset_id, start, None, new_id))
            except Exception:
                log.exception("Прогрев региона %s не удался", dataset_id)
        if block:
            for future in waits:
                if future is not None:
                    future.result()

    if block:
        run()
        return None
    thread = threading.Thread(target=run, name="ready-warm-up", daemon=True)
    thread.start()
    return thread


def enabled() -> bool:
    """Прогрев при старте выключается переменной окружения — тестам он ни к чему."""
    return os.environ.get("BEE_WARM_UP", "1") not in ("0", "false", "no")


def status() -> dict:
    """Что готово: ключ, регион, бюджет, число расчётов и замер последнего плана."""
    with _lock:
        rows = [
            {
                "key": entry.key,
                "dataset_id": entry.dataset_id,
                "plan_id": entry.plan.id,
                "budget_s": entry.budget_s,
                "builds": entry.builds,
                "unassigned": len(entry.plan.unassigned),
                "net_rub": entry.plan.economy.net_rub if entry.plan.economy else None,
                "timing": entry.plan.timing,
            }
            for entry in _entries.values()
        ]
        pending = list(_inflight)
    return {"ready": rows, "in_flight": pending}


def clear() -> None:
    """Забыть всё готовое — для тестов."""
    global _epoch
    with _lock:
        _epoch += 1
        _entries.clear()
        _inflight.clear()
