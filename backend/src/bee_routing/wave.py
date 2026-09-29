"""Волна заявок: обычные события дня копятся и пересчитываются пачкой на границе отрезка.

Зачем. Каждый пересчёт двигает чьи-то визиты. Десять заявок за час —
десять пересчётов, и один и тот же клиент получает три новых времени
подряд. Если заявки копить и раскладывать разом, пересчётов вчетверо
меньше, а раскладка видит всю волну: вторая заявка не занимает место,
которое лучше подошло бы третьей.

Правила:

1. **Отрезок — настройка** `batch_window_min` (по умолчанию 15 минут);
   ноль выключает очередь: каждое событие пересчитывается само.
2. **Срочное — вне очереди.** Авария и срочная заявка ставятся сразу:
   у них предел реакции. Сразу идут и факты с линии — клиента нет,
   бригада задерживается, бригада выбыла: они меняют то, что происходит
   сейчас. В очереди ждут новая обычная заявка, отмена и перенос окна.
3. **Граница отрезка — по часам дня**, а не от первого события: 12:00,
   12:15, 12:30. Заявка, пришедшая в 12:07, уходит в пересчёт в 12:15.
4. **Событие волны считается минутой пересчёта**, а не минутой прихода:
   к 12:15 бригады уехали дальше, чем были в 12:07, и замораживать надо
   то, что начато к 12:15.
"""

from __future__ import annotations

from . import settings
from .checks import to_clock, to_min
from .models import Event

QUEUED_TYPES = ("new_request", "cancel", "reschedule")


def window() -> int:
    return max(0, int(settings.option("batch_window_min") or 0))


def is_urgent(event: Event) -> bool:
    """Идёт ли событие вне очереди."""
    if event.type not in QUEUED_TYPES:
        return True
    if event.request is not None:
        from .replan import default_policy

        return default_policy(event.request) == "direct"
    return False


def due(time: str, step: int | None = None) -> str:
    """Ближайшая граница отрезка не раньше этой минуты."""
    step = window() if step is None else step
    if step <= 0:
        return time
    minute = to_min(time)
    return to_clock(min(-(-minute // step) * step, 24 * 60 - 1))


def stamp(events: list[Event], moment: str) -> list[Event]:
    """События волны с минутой пересчёта; порядок — по времени прихода."""
    ordered = sorted(events, key=lambda e: (to_min(e.time), e.id))
    return [e.model_copy(update={"time": moment}) if to_min(e.time) < to_min(moment) else e for e in ordered]
