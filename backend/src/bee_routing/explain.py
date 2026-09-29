"""Почему заявка досталась этой бригаде — и почему не досталась никому.

Объяснения собираются из тех же проверок, по которым распределял базовый
алгоритм (`checks.check_visit`), поэтому разойтись с планом им нечем.
Текст всегда приходит с сервера готовым: клиент фраз не собирает.
"""

from __future__ import annotations

from typing import Any

from .checks import SKILL_RU, TRANSPORT_RU, check_visit, feasible, first_failure, km_ru
from .matrices import Matrices
from .models import Alternative, Check, Engineer, Explanation, Request
from .travel import leg

# Шаблоны причин — один словарь на весь проект, коды по контракту.
REASON_TEMPLATES = {
    "no_skill": "Навык «{skill}» нужен, а его нет ни у одной свободной бригады",
    "no_transport": "Заявке нужен {transport}, а у бригад региона его нет",
    "no_fit_window": (
        "Работа {duration} мин не помещается в окно {window} ни у кого с учётом дороги"
    ),
    "no_fit_shift": "Работа {duration} мин не укладывается в смену до {shift_end} ни у кого",
    "all_busy": "Все бригады заняты: до конца окна {window} никто не освобождается",
    "no_engineer": "В регионе нет бригады, которой можно отдать эту заявку",
}


def _probe(state: Any, request: Request, matrices: Matrices) -> tuple[list[Check], float]:
    """Примерить заявку в конец маршрута бригады: проверки и добавочные километры."""
    road = leg(state.engineer, state.position, request.id, matrices, state.clock)
    checks = check_visit(
        state.engineer, request, state.clock + road.minutes, matrices, prev_id=state.position,
        depart_min=state.clock,
    )
    return checks, road.km


def fold_reason(codes: list[str]) -> str:
    """Свернуть причины отказа всех бригад в один код по контракту."""
    if not codes:
        return "no_engineer"
    unique = set(codes)
    if unique == {"no_skill"}:
        return "no_skill"
    if unique <= {"no_skill", "no_transport"}:
        return "no_transport"
    for code in ("no_fit_window", "no_fit_shift", "all_busy"):
        if code in codes:
            return code
    return "all_busy"


def unassigned_reason(
    request: Request, engineers: list[Engineer], states: dict[str, Any], matrices: Matrices
) -> tuple[str, str]:
    """Код и фраза для заявки, которую не взял никто."""
    from . import stock

    able = [e for e in engineers if request.skill in e.skills]
    if request.equipment and able:
        lacking = [stock.missing(e.id, states[e.id].stops, request) for e in able]
        if all(lacking):
            from .insertion import stock_labels

            names = ", ".join(stock_labels(sorted({d for row in lacking for d in row})))
            return "no_stock", (f"Ни у одной подходящей бригады не осталось нужного оборудования: {names}. "
                                "Запас утренний, днём он не пополняется")
    codes: list[str] = []
    for engineer in engineers:
        state = states[engineer.id]
        checks, _ = _probe(state, request, matrices)
        code = first_failure(checks)
        if code in ("no_fit_window", "no_fit_shift") and state.stops:
            code = "all_busy"
        if code:
            codes.append(code)
    code = fold_reason(codes)
    shift_end = engineers[0].shift_end if engineers else "22:00"
    text = REASON_TEMPLATES[code].format(
        skill=SKILL_RU.get(request.skill.value, request.skill.value),
        transport=TRANSPORT_RU[request.transport.value] if request.transport else "транспорт",
        duration=request.duration_min,
        window=f"{request.window_start}–{request.window_end}",
        shift_end=shift_end,
    )
    return code, text


def alternatives_for(
    request: Request, engineers: list[Engineer], states: dict[str, Any],
    owner_id: str, matrices: Matrices,
) -> list[Alternative]:
    """Что было бы, если бы заявку отдали другой бригаде.

    Примеряются ближайшие к заявке бригады, числом `scan_limit` (12), а не
    все: на дне в сто бригад полный перебор давал 75 тысяч примерок, треть
    хвоста после поиска, и ответ в 16 МБ — а диспетчеру нужны два-три
    соседа, «портянку никто не прочтёт» (эксперты, 16.09.2026). В регионах
    заказчика бригад 11—12, и отбор ничего не меняет.
    """
    from .insertion import nearest_states

    out: list[Alternative] = []
    near = {st.engineer.id for st in nearest_states(states, request, matrices)} if len(engineers) > 12 else None
    for engineer in engineers:
        if engineer.id == owner_id or (near is not None and engineer.id not in near):
            continue
        state = states[engineer.id]
        checks, delta_km = _probe(state, request, matrices)
        if feasible(checks):
            out.append(
                Alternative(
                    engineer_id=engineer.id,
                    feasible=True,
                    delta_km=round(delta_km, 1),
                    text=f"{engineer.name} успевал, но добавил бы {km_ru(delta_km)} км",
                )
            )
        else:
            failed = next(check for check in checks if not check.ok)
            out.append(
                Alternative(
                    engineer_id=engineer.id,
                    feasible=False,
                    reason_code=first_failure(checks),
                    # Альтернатива читается в списке из многих бригад: имя стоит первым,
                    # если проверка сама его не назвала.
                    text=failed.text if engineer.name in failed.text else f"{engineer.name}: {failed.text}",
                )
            )
    return out


def explain_assignments(
    requests: list[Request], engineers: list[Engineer], states: dict[str, Any],
    owner: dict[str, str], matrices: Matrices,
) -> dict[str, Explanation]:
    """Объяснение по каждой назначенной заявке: проверки и альтернативы."""
    by_id = {req.id: req for req in requests}
    stop_of = {
        stop.request_id: (state, stop)
        for state in states.values()
        for stop in state.stops
    }
    out: dict[str, Explanation] = {}
    for request_id, engineer_id in owner.items():
        request = by_id.get(request_id)
        found = stop_of.get(request_id)
        if request is None or found is None:
            continue
        state, stop = found
        seq = stop.seq
        prev_id = state.stops[seq - 2].request_id if seq > 1 else state.start_position
        arrive = int(stop.arrive[:2]) * 60 + int(stop.arrive[3:])
        checks = check_visit(state.engineer, request, arrive, matrices, prev_id=prev_id)
        out[request_id] = Explanation(
            engineer_id=engineer_id,
            checks=checks,
            alternatives=alternatives_for(request, engineers, states, engineer_id, matrices),
        )
    return out
