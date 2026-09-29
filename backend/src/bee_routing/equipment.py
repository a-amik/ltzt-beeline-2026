"""Оборудование заявки и утренний запас инженера — по слову эксперта 16.09.2026.

Матвей Олексенко: оборудование — дополнительный параметр заявки, который
выбирает клиент (роутер, ТВ-приставка, умная колонка); утром инженер видит
по заявкам дня, сколько чего взять; на вид транспорта не влияет — всё
помещается в рюкзак. В данных заказчика устройств нет, поэтому набор
синтетический, и синтетика честная: доли по типу заявки лежат
в `assumptions.json` (`equipment.by_type_bk`), а розыгрыш детерминирован
номером заявки — тот же датасет, те же устройства на любой машине.

Ограничением это не становится: задание называет учёт оборудования
допустимым усложнением, эксперт — параметром, а не барьером. Что даёт:
у заявки в карточке строка «взять: роутер, приставка», у бригады
в приложении карточка «Взять утром» с суммой по маршруту дня, у диспетчера
— тот же список в дне бригады. Передачу устройств между инженерами днём
прототип не моделирует.

Дописать устройства в собранные датасеты: `uv run python -m bee_routing.enrich`.
"""

from __future__ import annotations

import hashlib

from .geocode import load_assumptions
from .models import Dataset, Plan, Request

ORDER = ("router", "tv_box", "speaker")


def _draw(request_id: str, device: str) -> float:
    """Число в [0, 1) от номера заявки и устройства — вместо random."""
    digest = hashlib.sha1(f"{request_id}:{device}".encode()).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF


def equipment_for(request_id: str, type_bk: str, conf: dict | None = None) -> list[str]:
    """Устройства заявки по долям её типа; порядок фиксирован, повторов нет."""
    conf = conf or load_assumptions()
    shares = conf.get("equipment", {}).get("by_type_bk", {}).get(type_bk, {})
    return [device for device in ORDER if _draw(request_id, device) < float(shares.get(device, 0.0))]


def labels(conf: dict | None = None) -> dict[str, str]:
    """Подписи устройств по-русски."""
    conf = conf or load_assumptions()
    return dict(conf.get("equipment", {}).get("labels", {}))


def describe(equipment: list[str], conf: dict | None = None) -> str:
    """«роутер, ТВ-приставка» — для карточки заявки."""
    names = labels(conf)
    return ", ".join(names.get(device, device) for device in equipment)


def kit_for(plan: Plan, dataset: Dataset, engineer_id: str, requests: dict[str, Request] | None = None) -> dict[str, int]:
    """Что бригаде взять утром: сумма устройств по её маршруту дня."""
    by_id = requests or {req.id: req for req in dataset.requests}
    route = next((r for r in plan.routes if r.engineer_id == engineer_id), None)
    kit: dict[str, int] = {}
    if route is None:
        return kit
    for stop in route.stops:
        req = by_id.get(stop.request_id)
        if req is None or stop.status == "no_show":
            continue
        for device in req.equipment:
            kit[device] = kit.get(device, 0) + 1
    return {device: kit[device] for device in ORDER if device in kit}


def enrich(dataset: dict, conf: dict | None = None) -> int:
    """Дописать устройства заявкам датасета (словарь файла); вернуть, скольким."""
    conf = conf or load_assumptions()
    count = 0
    for req in dataset.get("requests", []):
        req["equipment"] = equipment_for(req["id"], req.get("type_bk", ""), conf)
        count += 1
    for event in dataset.get("events", []):
        extra = event.get("request")
        if extra:
            extra["equipment"] = equipment_for(extra["id"], extra.get("type_bk", ""), conf)
    return count
