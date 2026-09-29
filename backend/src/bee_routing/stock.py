"""Запас оборудования у бригады: что взято утром и что осталось к этой минуте.

Билайн, 19.09.2026: оборудование остаётся синтетическим, но запас у бригады
конечен — у пешего инженера в рюкзаке 1—2 устройства сверх нужного, —
и при перепланировании заявку нельзя отдавать бригаде, у которой нужного
устройства нет.

Как это устроено:

1. **Утренний запас — маршрут плюс резерв.** Бригада берёт устройства
   по заявкам утреннего плана и запас сверх них: `spare_units_foot`
   у бригады без машины, `spare_units_car` у бригады на машине. Запас
   раскладывается по кругу — роутер, приставка, колонка, — поэтому два
   устройства пешего инженера это роутер и приставка. Запас считается один
   раз, с первого плана дня, и едет в плане дальше (`Plan.stock`).
2. **Остаток — запас минус устройства стоящих визитов.** Сорвавшийся визит
   («клиента нет») устройство не тратит; отменённая заявка его возвращает.
3. **Проверка стоит в одном месте — в примерке заявки в маршрут**
   (`insertion.best_insertion`): через неё идут вставка при событии,
   предложения бригадам, ответ бригады и ручная замена у диспетчера.
   Полный пересчёт хвоста решателем держит тот же остаток ёмкостью
   (`solver.py`).
4. **Числа — в настройках** (`options.equipment_stock`, `spare_units_*`),
   как всё в этом проекте: выключенный учёт возвращает запас в подсказку
   «взять утром».

Передачу устройств между бригадами и заезд на склад среди дня прототип
не моделирует: бригада, у которой устройство кончилось, заявку с ним
не получает.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from . import settings
from .equipment import ORDER
from .models import Dataset, Plan, Request

_stock: ContextVar[dict[str, dict[str, int]] | None] = ContextVar("bee_stock", default=None)
_known: ContextVar[dict[str, Request] | None] = ContextVar("bee_stock_requests", default=None)


def enabled() -> bool:
    return settings.option("equipment_stock") is not False


def spare_for(transports: list[str]) -> dict[str, int]:
    """Запас сверх маршрута: число из настроек, устройства по кругу."""
    key = "spare_units_car" if "car" in transports else "spare_units_foot"
    units = int(settings.option(key) or 0)
    out = dict.fromkeys(ORDER, 0)
    for i in range(units):
        out[ORDER[i % len(ORDER)]] += 1
    return out


def morning(plan: Plan, dataset: Dataset, by_id: dict[str, Request] | None = None) -> dict[str, dict[str, int]]:
    """Утренний запас каждой бригады: устройства её маршрута плюс резерв."""
    by_id = by_id or {r.id: r for r in dataset.requests}
    routes = {r.engineer_id: r for r in plan.routes}
    out: dict[str, dict[str, int]] = {}
    for eng in settings.effective_engineers(dataset.engineers):
        have = spare_for([t.value for t in eng.transports])
        route = routes.get(eng.id)
        for stop in route.stops if route else []:
            req = by_id.get(stop.request_id)
            for device in req.equipment if req else []:
                have[device] = have.get(device, 0) + 1
        out[eng.id] = have
    return out


def of(plan: Plan, dataset: Dataset, by_id: dict[str, Request] | None = None) -> dict[str, dict[str, int]]:
    """Запас дня: тот, что едет в плане; у первого плана дня — посчитать."""
    return plan.stock or morning(plan, dataset, by_id)


@contextmanager
def use(stock: dict[str, dict[str, int]] | None, by_id: dict[str, Request] | None = None) -> Iterator[None]:
    """Запас, с которым идёт примерка заявок в этом пересчёте, и заявки дня для подсчёта остатка."""
    token = _stock.set(stock if stock and enabled() else None)
    known = _known.set(by_id)
    try:
        yield
    finally:
        _stock.reset(token)
        _known.reset(known)


def current() -> dict[str, dict[str, int]] | None:
    return _stock.get()


def used(stops, by_id: dict[str, Request]) -> dict[str, int]:
    out: dict[str, int] = {}
    for stop in stops:
        req = by_id.get(stop.request_id)
        if req is None or stop.status == "no_show":
            continue
        for device in req.equipment:
            out[device] = out.get(device, 0) + 1
    return out


def left(engineer_id: str, stops, by_id: dict[str, Request],
         stock: dict[str, dict[str, int]] | None = None) -> dict[str, int] | None:
    """Остаток устройств у бригады; `None` — запас не учитывается."""
    stock = stock if stock is not None else current()
    if stock is None or engineer_id not in stock:
        return None
    spent = used(stops, by_id)
    return {device: n - spent.get(device, 0) for device, n in stock[engineer_id].items()}


def missing(engineer_id: str, stops, request: Request, by_id: dict[str, Request] | None = None) -> list[str]:
    """Каких устройств заявки у бригады не осталось. Заявка уже в маршруте — её устройства при ней."""
    if not request.equipment or any(s.request_id == request.id for s in stops):
        return []
    if current() is None:
        return []
    rest = left(engineer_id, stops, {**(by_id or {}), **(_known.get() or {})})
    if rest is None:
        return []
    return [device for device in request.equipment if rest.get(device, 0) < 1]
