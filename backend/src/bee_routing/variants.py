"""Варианты пересчёта после пачки событий: диспетчер выбирает, а не жмёт «пересчитать».

Зачем. Событие дня — не приказ пересчитать, а вопрос «что теперь делать».
Ответов на него несколько, и каждый чего-то стоит: сохранить порядок визитов
дёшево для клиентов, но берёт меньше; перестроить день берёт больше, но
двигает обещанное; отложить новые заявки на завтра не трогает никого, но
теряет выручку дня. Поэтому диспетчер сохраняет события — одно или пачку, —
сервер считает все ответы разом, а план дня меняется только тем, который
диспетчер принял.

Варианты:

- `keep` — сохранить порядок: локальный ремонт, визиты не переставляются;
- `full` — перестроить день: решатель раскладывает хвост дня заново. Решатель
  идёт один раз на всю пачку, а не после каждого события: пять заявок пачки
  по три секунды на каждую — пятнадцать секунд ожидания, а раскладка после
  последнего события всё равно переставляет всё, что не заморожено;
- `tomorrow` — новые заявки дня на завтра, остальные события — ремонтом.
  Есть только тогда, когда в пачке есть обычная новая заявка: аварию
  на завтра не переносят.

Три вещи, которые нельзя ломать:

1. **События пачки применяются по порядку времени**, каждое к плану,
   который получился после предыдущего: вторая заявка пачки видит бригаду,
   уже занятую первой.
2. **Разница считается от плана до пачки**, а не от предпоследнего шага:
   «До события / После» на экране сравнивает день до вброса и после него.
3. **Быстрое не ждёт медленного.** `keys` в запросе выбирает, что считать:
   клиент сперва просит `keep` и `tomorrow` (доли секунды), показывает их
   и только потом — `full` с решателем.
4. **Вариант не становится планом дня сам.** Планы вариантов сервер помнит,
   но «последним» делает только принятый (`POST /plan/{id}/adopt`) — иначе
   бригады увидели бы в приложении день, которого диспетчер не выбирал.
"""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy

from . import settings
from .checks import to_min
from .matrices import Matrices
from .models import Dataset, Deferred, Event, Plan, ReplanVariant, VariantRequest
from .replan import NEW_TYPES, diff_of, replan
from .simulate import describe

TITLES = {
    "keep": ("Сохранить порядок", "Бригады едут прежним маршрутом, сдвигаются только времена; новое встаёт в свободное место"),
    "full": ("Перестроить день", "Решатель раскладывает хвост дня заново: берёт больше, но меняет время обещанных визитов"),
    "tomorrow": ("Новые заявки — на завтра", "День не трогается; новые заявки уходят на завтра, клиентская служба согласует окно"),
}


def _with_mode(base: dict | None, mode: str) -> dict:
    out = deepcopy(base or {})
    out.setdefault("options", {})["replan_mode"] = mode
    return out


def _is_new(event: Event) -> bool:
    return event.type in NEW_TYPES and event.request is not None


def _defer(plan: Plan, event: Event, plan_id: str) -> Plan:
    out = plan.model_copy(deep=True)
    out.id = plan_id
    out.history = [*out.history, event]
    out.deferred.append(Deferred(
        request_id=event.request.id, since=event.time,
        reason="Диспетчер перенёс на следующий день: сегодняшние маршруты не трогаем",
    ))
    return out


def _run(base: Plan, dataset: Dataset, matrices: Matrices, events: list[Event], key: str,
         next_id: Callable[[], str]) -> Plan:
    plan = base
    last = len(events) - 1
    for i, event in enumerate(events):
        mode = "full" if key == "full" and i == last else "local"
        with settings.use(_with_mode(base.settings, mode)):
            if key == "tomorrow" and event.type == "new_request" and event.request is not None:
                plan = _defer(plan, event, next_id())
            else:
                plan = replan(plan, dataset, matrices, event, plan_id=next_id())
    plan.settings = base.settings
    frozen = plan.diff.frozen_requests if plan.diff else []
    plan.diff = diff_of(base, plan, events[-1], frozen)
    plan.metrics.changed_requests = len(plan.diff.changed_requests)
    return plan


def _signature(plan: Plan) -> tuple:
    return tuple(sorted((r.engineer_id, tuple(s.request_id for s in r.stops)) for r in plan.routes))


def variants(base: Plan, dataset: Dataset, matrices: Matrices, events: list[Event],
             next_id: Callable[[], str], keys: list[str] | None = None) -> list[ReplanVariant]:
    """Ответы на пачку событий — с тем, что каждый стоит; `keys` сужает до названных."""
    events = sorted(events, key=lambda e: (to_min(e.time), e.id))
    wanted = ["keep", "full"]
    if any(e.type == "new_request" and e.request is not None for e in events):
        wanted.append("tomorrow")
    keys = [k for k in wanted if keys is None or k in keys]
    base_net = base.economy.net_rub if base.economy else 0
    out: list[ReplanVariant] = []
    seen: dict[tuple, str] = {}
    for key in keys:
        plan = _run(base, dataset, matrices, events, key, next_id)
        rows = []
        for event in events:
            if not _is_new(event):
                continue
            text, code = describe(plan, event.model_copy(update={"type": "new_request"}))
            rows.append(VariantRequest(request_id=event.request.id, time=event.time, outcome=text, code=code))
        sig = _signature(plan)
        title, hint = TITLES[key]
        net = plan.economy.net_rub if plan.economy else 0
        out.append(ReplanVariant(
            key=key, title=title, hint=hint, plan=plan,
            placed=sum(1 for r in rows if r.code == "assigned"),
            offered=sum(1 for r in rows if r.code == "offered"),
            deferred=sum(1 for r in rows if r.code == "deferred"),
            changed=plan.metrics.changed_requests,
            unassigned=len(plan.unassigned),
            net_rub=net, net_delta_rub=net - base_net,
            same_as=seen.get(sig),
            requests=rows,
        ))
        seen.setdefault(sig, key)
    return out
