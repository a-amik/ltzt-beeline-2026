"""Проверка ограничений при постановке заявки в маршрут.

Одна функция `check_visit` отвечает на вопрос «может ли эта бригада
взять эту заявку, приехав в такое-то время» — и отвечает списком
проверок с русским текстом и числами. Её зовут и базовый алгоритм,
и объяснитель, её же возьмёт решатель: второго места, где записаны
ограничения, в проекте быть не должно.
"""

from __future__ import annotations

from .matrices import Matrices
from .models import Check, Engineer, Request
from .travel import leg

SKILL_RU = {
    "local": "локальные работы",
    "connect": "подключение и дозаказы",
    "emergency": "аварийные работы",
}
TRANSPORT_RU = {
    "car": "автомобиль",
    "foot": "пешком",
    "bike": "велосипед",
    "transit": "общественный транспорт",
}
KIND_TO_REASON = {
    "skill": "no_skill",
    "transport": "no_transport",
    "window": "no_fit_window",
    "shift": "no_fit_shift",
    "distance": "no_engineer",
}


def km_ru(value: float) -> str:
    """Километры по-русски: запятая, один знак."""
    return f"{value:.1f}".replace(".", ",")


def to_min(clock: str) -> int:
    """«14:30» → 870 минут от полуночи."""
    hours, _, minutes = clock.partition(":")
    return int(hours) * 60 + int(minutes)


def to_clock(minutes: int) -> str:
    """870 → «14:30»; сутки не перескакиваем — план живёт внутри одного дня."""
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def visit_times(request: Request, arrive_min: int) -> dict[str, int]:
    """Когда работа начнётся и кончится, сколько ждали и насколько опоздали."""
    window_start = to_min(request.window_start)
    window_end = to_min(request.window_end)
    start = max(arrive_min, window_start)
    return {
        "arrive": arrive_min,
        "start": start,
        "end": start + request.duration_min,
        "wait": max(0, window_start - arrive_min),
        "late": max(0, start - window_end),
    }


def check_visit(
    engineer: Engineer,
    request: Request,
    arrive_time: int,
    matrices: Matrices,
    *,
    prev_id: str = "office",
    depart_min: int | None = None,
) -> list[Check]:
    """Все ограничения одной постановки: навык, транспорт, окно, смена, дорога.

    `arrive_time` — минуты от полуночи, `prev_id` — точка, из которой едут
    (идентификатор предыдущей заявки или «office»).
    """
    name = engineer.name
    skill = request.skill.value
    skill_ru = SKILL_RU.get(skill, skill)
    times = visit_times(request, arrive_time)
    road = leg(engineer, prev_id, request.id, matrices, depart_min)
    travel_min, travel_km = road.minutes, road.km

    has_skill = skill in [s.value for s in engineer.skills]
    checks = [
        Check(
            kind="skill",
            ok=has_skill,
            text=(
                f"Навык «{skill_ru}» есть у бригады {name}"
                if has_skill
                else f"У бригады {name} нет навыка «{skill_ru}»"
            ),
        )
    ]

    need = request.transport.value if request.transport else None
    own_all = [t.value for t in engineer.transports]
    own = ", ".join(TRANSPORT_RU[t] for t in own_all)
    ok_transport = need is None or need in own_all
    checks.append(
        Check(
            kind="transport",
            ok=ok_transport,
            text=(
                f"Транспорт подходит: у бригады {name} {own}"
                if ok_transport
                else f"Заявке нужен {TRANSPORT_RU[need]}, а у бригады {name} {own}"
            ),
        )
    )

    ok_window = times["late"] == 0
    window = f"{request.window_start}–{request.window_end}"
    checks.append(
        Check(
            kind="window",
            ok=ok_window,
            text=(
                f"Приезд в {to_clock(times['arrive'])}, начало в {to_clock(times['start'])}"
                f" — внутри окна {window}"
                + (f", ожидание {times['wait']} мин" if times["wait"] else "")
                if ok_window
                else f"Приезд в {to_clock(times['arrive'])} — окно {window} уже закрыто,"
                f" опоздание {times['late']} мин"
            ),
        )
    )

    shift_end = to_min(engineer.shift_end)
    ok_shift = times["end"] <= shift_end
    checks.append(
        Check(
            kind="shift",
            ok=ok_shift,
            text=(
                f"Работа {request.duration_min} мин кончается в {to_clock(times['end'])}"
                f" — до конца смены в {engineer.shift_end}"
                if ok_shift
                else f"Работа {request.duration_min} мин кончилась бы в {to_clock(times['end'])}"
                f", а смена у бригады {name} до {engineer.shift_end}"
            ),
        )
    )

    checks.append(
        Check(
            kind="distance",
            ok=True,
            text=(
                f"Дорога — {TRANSPORT_RU[road.mode.value]}, {km_ru(travel_km)} км, {travel_min} мин"
                if travel_min or travel_km
                else "Дорога от предыдущей точки не нужна"
            ),
        )
    )
    return checks


def feasible(checks: list[Check]) -> bool:
    """Постановка возможна, если прошли все проверки."""
    return all(check.ok for check in checks)


def first_failure(checks: list[Check]) -> str | None:
    """Код причины первой не прошедшей проверки."""
    for check in checks:
        if not check.ok:
            return KIND_TO_REASON[check.kind]
    return None
