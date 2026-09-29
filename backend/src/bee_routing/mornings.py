"""Утро нашего плана для «Живого дня» и «Имитации»: считается один раз и помнится.

Сценарий дня — это утро плюс события. Утро не зависит ни от событий, ни от
номера набора: только от участка, старта бригад, настроек и бюджета поиска.
А считается оно дольше всего остального дня вместе: на «Всей Москве» —
около 12 секунд из 13, на одном участке — 2,5 из 2,6 (замер 29.09.2026).
Поэтому утро по ключу считается один раз, и каждый следующий сценарий на
том же участке и старте занимает доли секунды.

Отличие от готовых планов главного экрана (`ready.py`): там лучший план
по ключу доводится в фоне десятками секунд, а здесь утро посчитано ровно
с бюджетом сценария — тем же, с каким посчитаны дни «Имитации». Иначе
«Живой день» и «Имитация» на одном наборе событий показывали бы разное утро.

Ключ — ключ готовых планов (участок, старт, действующие настройки без
бюджета), бюджет поиска и отпечаток самих данных: правка адреса дома
бригады или загрузка набора дают новое утро, а не старое.

Прогрев при старте сервиса считает утра всех участков для трёх вариантов
старта с настройками по умолчанию — теми, что у экрана, пока их не меняли.
Идёт фоновым пулом решателя, чтобы расчёт по нажатию его не ждал.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from concurrent.futures import Future

from . import settings
from .models import Dataset, Plan
from .ready import enabled, key_of

log = logging.getLogger(__name__)

# Сколько утр держать: участки × старты × несколько вариантов настроек.
LIMIT = 48

_entries: dict[str, Plan] = {}
_inflight: dict[str, Future] = {}
_lock = threading.Lock()


def _fingerprint(dataset: Dataset) -> str:
    """Отпечаток данных набора: миллисекунды на 205 заявках."""
    return hashlib.sha1(dataset.model_dump_json().encode()).hexdigest()[:12]


def key(dataset: Dataset, start: str, budget_s: int) -> str:
    """Ключ утра — внутри `settings.use(...)` сценария: настройки берутся действующие."""
    return f"{key_of(dataset.id, start, settings.current())}|{budget_s}|{_fingerprint(dataset)}"


def morning(dataset: Dataset, matrices, start: str, budget_s: int, plan_id: str = "morning") -> Plan:
    """Утренний план по ключу: готовый — сразу, считается — ждём его, иначе считаем.

    Зовётся внутри `settings.use(...)` сценария, где уже стоят старт и бюджет.
    Возвращается копия: день дальше меняет план, а запись должна остаться утром.
    """
    from .solver import solve

    k = key(dataset, start, budget_s)
    with _lock:
        ready = _entries.get(k)
        future = _inflight.get(k)
        owner = ready is None and future is None
        if owner:
            future = _inflight[k] = Future()
    if ready is not None:
        return ready.model_copy(deep=True)
    if not owner:
        return future.result().model_copy(deep=True)
    try:
        plan, _ = solve(dataset, matrices, plan_id=plan_id, start=start)
        with _lock:
            if len(_entries) >= LIMIT:
                _entries.pop(next(iter(_entries)))
            _entries[k] = plan
        future.set_result(plan)
        return plan.model_copy(deep=True)
    except BaseException as error:
        future.set_exception(error)
        raise
    finally:
        with _lock:
            _inflight.pop(k, None)


def is_ready(dataset: Dataset, start: str, budget_s: int) -> bool:
    """Утро по ключу уже посчитано — внутри `settings.use(...)` сценария. Считающееся не в счёт."""
    with _lock:
        return key(dataset, start, budget_s) in _entries


def warm_up(dataset_ids: list[str], budget_s: int = 3) -> threading.Thread | None:
    """Посчитать утра всех участков для трёх стартов фоном, по одному за раз."""
    if not enabled():
        return None

    def run() -> None:
        from .loader import load_dataset, load_matrices
        from .portfolio import BACKGROUND
        from .race import STARTS

        token = BACKGROUND.set(True)
        try:
            for start, conf in STARTS.items():
                for dataset_id in dataset_ids:
                    try:
                        dataset, matrices = load_dataset(dataset_id), load_matrices(dataset_id)
                        with settings.use({"options": {**conf["options"], "time_limit_s": budget_s}}):
                            morning(dataset, matrices, str(settings.option("start")), budget_s)
                    except Exception:
                        log.exception("Прогрев утра %s / %s не удался", dataset_id, start)
        finally:
            BACKGROUND.reset(token)

    thread = threading.Thread(target=run, name="mornings-warm-up", daemon=True)
    thread.start()
    return thread


def status() -> dict:
    """Сколько утр готово и какие считаются."""
    with _lock:
        return {"ready": len(_entries), "in_flight": list(_inflight)}


def clear() -> None:
    """Забыть все утра — для тестов."""
    with _lock:
        _entries.clear()
        _inflight.clear()
