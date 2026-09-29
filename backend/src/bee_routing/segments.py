"""Сегмент клиента аварии — KA, A, B, C, D — и цена аварии от него.

Зачем. Клиенты заказчика — бизнес, и простой связи парализует их работу:
кассы, склад, колл-центр. Насколько это дорого компании, решает размер
клиента, а не здание: один ключевой клиент важнее целого этажа мелких.
Поэтому авария стоит по сегменту клиента — как ABCD-сегментация клиентской
базы, по ежемесячному счёту за связь, плюс ключевые клиенты (KA): штучные
и самые крупные.

Цена аварии = риск потерять клиента × что он принесёт за договор + эскалация:
счёт в месяц × срок договора × маржа × риск ухода после дня простоя + цена
эскалации (`economy.emergency_segments`). Каждый час ожидания стоит долю этой
цены, после срока восстановления по SLA — дороже (`economy.late_rate`).

Три вещи, которые нельзя ломать:

1. **Сегмент синтетический и детерминированный.** В данных заказчика его
   нет. Сегмент выводится из номера заявки хешем SHA-256 по долям
   сегментов (`assumptions.json`, `emergency_segment_mix`): тот же номер —
   тот же сегмент при любом запуске. Сегмент из своего набора и сегмент,
   поставленный диспетчером руками, главнее синтетики.
2. **Сегмент — только у аварий.** Подключение, ремонт и дозаказ стоят
   по своим тарифам.
3. **Ступени старше сегмента по умолчанию** — как у организаторов: любая
   авария выше любого подключения (`options.priority_order`). Режим
   «по деньгам» разрешает мелкой аварии уступить подключению.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache

from .geocode import load_assumptions

SEGMENTS = ("KA", "A", "B", "C", "D")

# Запасные значения на случай, если допущения не прочитались.
FALLBACK_MIX = {"KA": 0.01, "A": 0.08, "B": 0.12, "C": 0.21, "D": 0.58}
FALLBACK_TARIFFS = {
    "KA": {"label": "ключевой клиент", "bill_rub": 500000, "churn_pct": 12, "escalation_rub": 50000, "sla_h": 2},
    "A": {"label": "крупный", "bill_rub": 250000, "churn_pct": 10, "escalation_rub": 20000, "sla_h": 2},
    "B": {"label": "средний", "bill_rub": 35000, "churn_pct": 8, "escalation_rub": 10000, "sla_h": 4},
    "C": {"label": "малый", "bill_rub": 7500, "churn_pct": 5, "escalation_rub": 3000, "sla_h": 0},
    "D": {"label": "микро", "bill_rub": 2500, "churn_pct": 3, "escalation_rub": 1000, "sla_h": 0},
}


@lru_cache(maxsize=1)
def _mix() -> dict[str, float]:
    try:
        own = load_assumptions().get("emergency_segment_mix") or {}
    except (FileNotFoundError, ValueError):
        own = {}
    shares = {k: float(v) for k, v in own.items() if k in SEGMENTS}
    return shares or dict(FALLBACK_MIX)


def estimate(request_id: str) -> str:
    """Сегмент клиента аварии из номера заявки: хеш, а не случайность."""
    digest = hashlib.sha256(f"segment:{request_id}".encode()).digest()
    mix = _mix()
    pick = int.from_bytes(digest[:8], "big") / 2**64 * (sum(mix.values()) or 1)
    for segment, share in mix.items():
        if pick < share:
            return segment
        pick -= share
    return next(reversed(mix))


def tariff(segment: str | None, conf: dict) -> dict:
    """Тарифы сегмента из `economy.emergency_segments`; неизвестный сегмент — как C."""
    table = conf.get("emergency_segments") or FALLBACK_TARIFFS
    return {**FALLBACK_TARIFFS["C"], **(table.get(segment or "C") or table.get("C") or {})}


def value_rub(segment: str | None, conf: dict) -> int:
    """Цена аварии: счёт × срок договора × маржа × риск ухода + эскалация."""
    t = tariff(segment, conf)
    months = float(conf.get("contract_months", 48))
    margin = float(conf.get("margin_pct", 50)) / 100
    return round(float(t["bill_rub"]) * months * margin * float(t["churn_pct"]) / 100 + float(t["escalation_rub"]))


def sla_min(segment: str | None, conf: dict) -> int:
    """Срок восстановления по SLA в минутах; 0 — до конца дня."""
    return round(float(tariff(segment, conf).get("sla_h", 0)) * 60)


def text(segment: str, value: int, conf: dict) -> str:
    """Строка для человека: «Авария у клиента A (крупный, 250 000 ₽ в месяц): цена 620 000 ₽, восстановить за 2 ч»."""
    t = tariff(segment, conf)
    money = lambda n: f"{round(n):,}".replace(",", " ")
    sla = f"восстановить за {t['sla_h']:g} ч" if float(t.get("sla_h", 0)) > 0 else "восстановить до конца дня"
    return (f"Авария у клиента {segment} ({t.get('label', '')}, {money(t['bill_rub'])} ₽ в месяц): "
            f"цена {money(value)} ₽, {sla}")
