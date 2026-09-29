"""Имитация операционного дня: утренний план, события по ходу дня, пересчёт.

Сценарий собирается из зерна (`seed`) и счётчиков: сколько новых заявок,
отмен, неявок клиента, переносов окна, задержек бригад, выбытий. Новые
заявки берутся по адресам того же региона (в утренней матрице точка есть,
так что дорога считается той же моделью), появляются с 11 до 17 часов
и просят окно через час-два после звонка. Сверх них диспетчер может вбросить
свои (`injected`): в названную минуту и по названной точке, — и увидеть,
вписалась ли заявка день в день при всём, что к той минуте случилось.

Правил ответа три, и их сравнивают между собой на одних событиях:

- `static` — новые заявки дня сразу уходят на завтра, остальное (отмены,
  неявки, задержки) отрабатывается пересчётом с горизонтом блокировки;
- `offer` — новая заявка предлагается лучшим бригадам, ответ имитируется
  с заданной долей согласия, отказались все — на завтра;
- `direct` — заявка отдаётся лучшему кандидату директивно.

Итог — лента событий с исходом каждого и показатели дня: сколько заявок
дня взяли сегодня, сколько перенесли, сколько визитов сдвинули, загрузка,
опоздания, бонусы и итог дня в рублях.

Запуск: `uv run python -m bee_routing.simulate <регион> [--seed N] [--new N] [--policy offer]`
пишет `data/simulation/<регион>-<seed>-<policy>.json`.
"""

from __future__ import annotations

import argparse
import json
import random
from copy import deepcopy
from pathlib import Path

from . import settings
from .checks import to_clock, to_min
from .economy import tariffs
from .geocode import DATA_DIR
from .insertion import assign
from .matrices import Matrices
from .models import (
    Dataset,
    Deferred,
    Event,
    Plan,
    ScenarioSpec,
    SimEvent,
    SimulationResult,
    SimulationRun,
)
from .replan import replan
from .solver import solve

SIM_DIR = DATA_DIR / "simulation"

KPI_LABELS: dict[str, tuple[str, str, bool]] = {
    "intraday_total": ("Заявок пришло за день", "", False),
    "intraday_served": ("Из них взято сегодня", "", False),
    "deferred": ("Перенесено на завтра", "", True),
    "changed_total": ("Сдвинуто визитов за день", "", True),
    "on_time": ("Визитов вовремя", "", False),
    "late": ("Опозданий", "", True),
    "unassigned": ("Не назначено к концу дня", "", True),
    "utilization_pct": ("Загрузка бригад", "%", False),
    "distance_km": ("Пробег", "км", True),
    "bonus_rub": ("Бонусы", "₽", True),
    "net_rub": ("Итог дня", "₽", False),
    "offers_sent": ("Предложений отправлено", "", False),
    "offers_accepted": ("Предложений принято", "", False),
    "emergencies": ("Аварий пришло за день", "", False),
    "reaction_worst_min": ("Реакция на аварию, худшая", "мин", True),
    "reaction_missed": ("Аварий позже предела реакции", "", True),
    "no_stock": ("Не взято из-за запаса оборудования", "", True),
    "waves": ("Волн пересчёта", "", False),
    "queue_wait_avg_min": ("Ожидание в очереди волны, среднее", "мин", True),
}


def intraday_count(spec: ScenarioSpec, dataset: Dataset) -> int:
    """Сколько заявок приходит днём: число из сценария, иначе доля региона из настроек.

    Билайн, 19.09.2026: день в день приходит 10—15 % заявок. Доля —
    настройка `intraday_share_pct`.
    """
    if spec.new_requests is not None:
        return int(spec.new_requests)
    share = float(settings.option("intraday_share_pct") or 0)
    return round(len(dataset.requests) * share / 100)


def reactions(plan: Plan) -> list[int]:
    """Минуты от появления аварии дня до начала работ по ней; не взятая — не в счёт."""
    from .replan import default_policy

    starts = {s.request_id: to_min(s.start) for r in plan.routes for s in r.stops if s.status != "no_show"}
    out = []
    for event in plan.history:
        req = event.request
        if req is not None and default_policy(req) == "direct" and req.id in starts:
            out.append(max(0, starts[req.id] - to_min(event.time)))
    return out


def _round5(minutes: int) -> int:
    return int(round(minutes / 5) * 5)


def make_events(dataset: Dataset, plan: Plan, spec: ScenarioSpec, matrices: Matrices) -> list[Event]:
    """Собрать события дня по зерну: воспроизводимо и по адресам региона."""
    rng = random.Random(spec.seed)
    shift_start = min(to_min(e.shift_start) for e in dataset.engineers)
    shift_end = max(to_min(e.shift_end) for e in dataset.engineers)
    stops = [(r.engineer_id, s) for r in plan.routes for s in r.stops]
    by_id = {req.id: req for req in dataset.requests}
    used: set[str] = set()
    events: list[Event] = []

    def pick_stop(after_min: int = 0):
        pool = [(e, s) for e, s in stops if s.request_id not in used and to_min(s.start) > after_min]
        if not pool:
            return None
        e, s = rng.choice(pool)
        used.add(s.request_id)
        return e, s

    for i in range(intraday_count(spec, dataset)):
        base = rng.choice(dataset.requests)
        appear = _round5(rng.randint(shift_start + 60, min(shift_end - 300, shift_start + 420)))
        lead = rng.choice([60, 90, 120])
        ws = _round5(appear + lead)
        we = min(ws + rng.choice([120, 180, 240]), shift_end)
        rid = f"n{i + 1}"
        fresh = base.model_copy(update={
            "id": rid, "priority": base.priority.__class__("normal"),
            "window_start": to_clock(ws), "window_end": to_clock(we),
        })
        matrices.register(rid, fresh.lat, fresh.lon, alias_of=base.id)
        events.append(Event(id=f"s-new-{i + 1}", type="new_request", time=to_clock(appear), request=fresh,
                            policy=None))
    # Вброшенные руками: в ту минуту, когда позвонил клиент, и по тем
    # координатам, куда ткнули. Точка того же адреса, что у известной заявки, —
    # её узел в матрице; иначе запасная оценка по координатам.
    for i, inj in enumerate(spec.injected):
        rid = f"v{i + 1}"
        template = dataset.requests[0]
        twin = next((r.id for r in dataset.requests if r.lat == inj.lat and r.lon == inj.lon), None)
        fresh = template.model_copy(update={
            "id": rid, "address": inj.address, "district": "—", "lat": inj.lat, "lon": inj.lon,
            "duration_min": inj.duration_min, "window_start": inj.window_start, "window_end": inj.window_end,
            "priority": template.priority.__class__("normal"), "skill": template.skill.__class__(inj.skill),
            "type_hd": "Вброшена в имитацию",
        })
        matrices.register(rid, inj.lat, inj.lon, alias_of=twin)
        events.append(Event(id=f"s-inj-{i + 1}", type="new_request", time=inj.time, request=fresh, policy=None))
    for i in range(spec.cancels):
        picked = pick_stop(shift_start + 90)
        if picked is None:
            break
        _, s = picked
        at = max(shift_start + 30, to_min(s.start) - rng.choice([30, 60, 120]))
        events.append(Event(id=f"s-cancel-{i + 1}", type="cancel", time=to_clock(_round5(at)), request_id=s.request_id))
    for i in range(spec.no_shows):
        picked = pick_stop(shift_start + 60)
        if picked is None:
            break
        _, s = picked
        events.append(Event(id=f"s-noshow-{i + 1}", type="no_show", time=s.arrive, request_id=s.request_id,
                            note=rng.choice(["absent", "unreachable", "waiting"])))
    for i in range(spec.reschedules):
        picked = pick_stop(shift_start + 120)
        if picked is None:
            break
        _, s = picked
        req = by_id[s.request_id]
        at = max(shift_start + 30, to_min(s.start) - rng.choice([60, 120, 180]))
        ws = min(to_min(req.window_start) + 120, shift_end - req.duration_min - 60)
        we = min(to_min(req.window_end) + 120, shift_end)
        events.append(Event(id=f"s-move-{i + 1}", type="reschedule", time=to_clock(_round5(at)),
                            request_id=s.request_id, window_start=to_clock(ws), window_end=to_clock(we)))
    for i in range(spec.delays):
        picked = pick_stop(shift_start + 60)
        if picked is None:
            break
        eng, s = picked
        used.discard(s.request_id)
        events.append(Event(id=f"s-delay-{i + 1}", type="delay", time=s.start, engineer_id=eng,
                            delay_min=rng.choice([20, 30, 45])))
    for i in range(spec.engineer_off):
        eng = rng.choice(dataset.engineers)
        at = _round5(rng.randint(shift_start + 120, shift_start + 360))
        events.append(Event(id=f"s-off-{i + 1}", type="engineer_off", time=to_clock(at), engineer_id=eng.id))
    events.extend(custom_events(dataset, plan, spec, matrices))
    events.sort(key=lambda e: (to_min(e.time), e.id))
    return events


def custom_events(dataset: Dataset, plan: Plan, spec: ScenarioSpec, matrices: Matrices) -> list[Event]:
    """События, заданные руками: те же виды и та же форма, что у случайных.

    Окно новой заявки и сдвиг переноса — как у генератора: визит через час
    после звонка на три часа, перенос — на два часа позже. «Клиента нет»
    случается в минуту приезда бригады по утреннему плану, если заявка в нём есть.
    """
    shift_end = max(to_min(e.shift_end) for e in dataset.engineers)
    by_id = {req.id: req for req in dataset.requests}
    arrive = {s.request_id: s.arrive for r in plan.routes for s in r.stops}
    engineers = {e.id for e in dataset.engineers}
    out: list[Event] = []
    for i, c in enumerate(spec.custom, 1):
        at = to_min(c.time)
        eid = f"c-{c.type}-{i}"
        if c.type == "new_request":
            base = by_id.get(c.request_id or "") or dataset.requests[0]
            ws = _round5(at + 60)
            rid = f"c{i}"
            fresh = base.model_copy(update={
                "id": rid, "priority": base.priority.__class__("normal"),
                "window_start": to_clock(ws), "window_end": to_clock(min(ws + 180, shift_end)),
            })
            matrices.register(rid, fresh.lat, fresh.lon, alias_of=base.id)
            out.append(Event(id=eid, type="new_request", time=c.time, request=fresh, policy=None))
        elif c.type in ("cancel", "no_show", "reschedule") and c.request_id in by_id:
            if c.type == "cancel":
                out.append(Event(id=eid, type="cancel", time=c.time, request_id=c.request_id))
            elif c.type == "no_show":
                out.append(Event(id=eid, type="no_show", time=arrive.get(c.request_id, c.time),
                                 request_id=c.request_id, note="absent"))
            else:
                req = by_id[c.request_id]
                ws = min(to_min(req.window_start) + 120, shift_end - req.duration_min - 60)
                we = min(to_min(req.window_end) + 120, shift_end)
                out.append(Event(id=eid, type="reschedule", time=c.time, request_id=c.request_id,
                                 window_start=to_clock(ws), window_end=to_clock(we)))
        elif c.type in ("delay", "engineer_off") and c.engineer_id in engineers:
            out.append(Event(id=eid, type=c.type, time=c.time, engineer_id=c.engineer_id,
                             delay_min=c.delay_min if c.type == "delay" else None))
    return out


def kpis_of(plan: Plan, dataset: Dataset, intraday: list[str], timeline: list[SimEvent]) -> dict[str, float]:
    """Показатели дня из итогового плана и ленты событий."""
    conf = tariffs()
    placed = {s.request_id for r in plan.routes for s in r.stops if s.status != "no_show"}
    stops = [s for r in plan.routes for s in r.stops if s.status != "no_show"]
    used = [r for r in plan.routes if r.stops]
    norm_day = int(conf["norm_day_min"])
    utilization = 100 * sum(r.norm_min for r in used) / (len(used) * norm_day) if used else 0.0
    waits = reactions(plan)
    limit = int(settings.option("emergency_reaction_min") or 0)
    return {
        "intraday_total": len(intraday),
        "intraday_served": sum(1 for rid in intraday if rid in placed),
        "deferred": len(plan.deferred),
        "changed_total": sum(e.changed_requests for e in timeline),
        "on_time": sum(1 for s in stops if s.late_min == 0),
        "late": sum(1 for s in stops if s.late_min > 0),
        "unassigned": len(plan.unassigned),
        "utilization_pct": round(utilization, 1),
        "distance_km": round(sum(r.distance_km for r in plan.routes), 1),
        "bonus_rub": plan.economy.bonus_rub if plan.economy else 0,
        "net_rub": plan.economy.net_rub if plan.economy else 0,
        "offers_sent": sum(1 for e in timeline if e.outcome_code in ("offered", "accepted", "declined")),
        "offers_accepted": sum(1 for e in timeline if e.outcome_code == "accepted"),
        "emergencies": len(waits),
        "reaction_worst_min": max(waits, default=0),
        "reaction_missed": sum(1 for w in waits if limit and w > limit),
        "no_stock": sum(1 for u in plan.unassigned if u.reason_code == "no_stock")
        + sum(1 for d in plan.deferred if "оборудования" in d.reason),
    }


def _snapshot(plan: Plan) -> dict[str, float]:
    return {
        "unassigned": len(plan.unassigned), "deferred": len(plan.deferred),
        "late": sum(1 for r in plan.routes for s in r.stops if s.late_min > 0),
        "net_rub": plan.economy.net_rub if plan.economy else 0,
    }


def run_policy(
    dataset: Dataset, matrices: Matrices, morning: Plan, events: list[Event], policy: str,
    spec: ScenarioSpec,
) -> SimulationRun:
    """Прожить день по одному правилу ответа на новые заявки."""
    rng = random.Random(spec.seed * 7919 + hash(policy) % 1000)
    plan = deepcopy(morning)
    timeline: list[SimEvent] = []
    intraday: list[str] = []
    counter = 0

    def next_id() -> str:
        nonlocal counter
        counter += 1
        return f"sim-{policy}-{counter}"

    from . import wave

    queue: list[Event] = []
    waits: list[int] = []
    waves = 0

    def handle(event: Event) -> None:
        nonlocal plan
        ev = event.model_copy(deep=True)
        if ev.type == "new_request":
            intraday.append(ev.request.id)
            if policy == "static":
                plan = plan.model_copy(deep=True)
                plan.id = next_id()
                plan.history = [*plan.history, ev]
                plan.deferred.append(Deferred(
                    request_id=ev.request.id, since=ev.time,
                    reason="Правило дня: заявки, пришедшие после утреннего плана, ставятся на следующий день",
                ))
                timeline.append(SimEvent(time=ev.time, type=ev.type, request_id=ev.request.id,
                                         outcome="На завтра по правилу статического дня",
                                         outcome_code="deferred", kpis=_snapshot(plan)))
                return
            from .replan import default_policy

            # Авария не предлагается, а ставится: у неё предел реакции, и ждать ответа бригад некогда.
            hot = default_policy(ev.request) == "direct"
            ev.policy = "direct" if policy == "direct" or hot else "offer"
        plan = replan(plan, dataset, matrices, ev, plan_id=next_id())
        outcome, code = describe(plan, ev)
        changed = plan.metrics.changed_requests
        if ev.type == "new_request" and policy == "offer" and code == "offered":
            offer = next(o for o in plan.offers if o.request_id == ev.request.id)
            accepted = None
            for candidate in offer.candidates:
                if rng.random() < spec.accept_prob:
                    accepted = candidate
                    break
                timeline.append(SimEvent(time=ev.time, type="offer", request_id=ev.request.id,
                                         engineer_id=candidate.engineer_id, outcome="Бригада отказалась",
                                         outcome_code="declined", kpis=_snapshot(plan)))
            if accepted is not None:
                built, _ = assign(plan, dataset, matrices, ev.request.id, accepted.engineer_id,
                                  accepted.insert_after, plan_id=next_id())
                if built is not None:
                    built.history, built.deferred = plan.history, plan.deferred
                    plan = built
                    changed += plan.metrics.changed_requests
                    outcome = f"Приняла бригада {accepted.engineer_id}, приезд {accepted.arrive}, бонус {accepted.bonus_rub} ₽"
                    code = "accepted"
            else:
                plan = plan.model_copy(deep=True)
                plan.id = next_id()
                plan.offers = [o for o in plan.offers if o.request_id != ev.request.id]
                plan.unassigned = [u for u in plan.unassigned if u.request_id != ev.request.id]
                plan.metrics.unassigned = len(plan.unassigned)
                plan.deferred.append(Deferred(
                    request_id=ev.request.id, since=ev.time,
                    reason="Все бригады, кому подходило, отказались: заявка переносится на следующий день",
                ))
                outcome, code = "Отказались все кандидаты — на завтра", "deferred"
        timeline.append(SimEvent(time=ev.time, type=ev.type, request_id=ev.request_id or (ev.request.id if ev.request else None),
                                 engineer_id=ev.engineer_id, outcome=outcome, outcome_code=code,
                                 changed_requests=changed, kpis=_snapshot(plan)))

    def flush(moment: str) -> None:
        nonlocal waves
        if not queue:
            return
        waves += 1
        waits.extend(to_min(moment) - to_min(e.time) for e in queue)
        for item in wave.stamp(queue, moment):
            handle(item)
        queue.clear()

    # Волна заявок: обычные события ждут границы отрезка, срочные идут сразу (`wave.py`).
    for event in events:
        if queue and to_min(event.time) >= to_min(wave.due(queue[0].time)):
            flush(wave.due(queue[0].time))
        if wave.window() <= 0 or wave.is_urgent(event) or policy == "static":
            handle(event)
        else:
            queue.append(event)
    if queue:
        flush(wave.due(queue[-1].time))
    extra = {"waves": waves,
             "queue_wait_avg_min": round(sum(waits) / len(waits), 1) if waits else 0.0}
    return SimulationRun(policy=policy, timeline=timeline,
                         kpis={**kpis_of(plan, dataset, intraday, timeline), **extra}, plan=plan)


def describe(plan: Plan, event: Event) -> tuple[str, str]:
    """Чем кончилось событие — словами и кодом."""
    if event.type == "new_request":
        rid = event.request.id
        owner = next((r.engineer_id for r in plan.routes for s in r.stops if s.request_id == rid), None)
        if owner:
            stop = next(s for r in plan.routes for s in r.stops if s.request_id == rid)
            return f"Встала к бригаде {owner}, приезд {stop.arrive}", "assigned"
        if any(d.request_id == rid for d in plan.deferred):
            return next(d.reason for d in plan.deferred if d.request_id == rid), "deferred"
        offer = next((o for o in plan.offers if o.request_id == rid), None)
        if offer and offer.candidates:
            return f"Предложена {len(offer.candidates)} бригадам, лучшая — {offer.candidates[0].engineer_id}", "offered"
        return "Не назначена", "deferred"
    if event.type in ("cancel", "no_show"):
        return ("Визит снят, время использовано пересчётом" if event.type == "cancel"
                else "Клиента нет: заявка на завтра, бригада едет дальше"), "removed"
    if event.type == "reschedule":
        rid = event.request_id
        owner = next((r.engineer_id for r in plan.routes for s in r.stops if s.request_id == rid), None)
        return (f"Новое окно {event.window_start}–{event.window_end}, остаётся у {owner}" if owner
                else "В новое окно сегодня не встаёт"), "shifted" if owner else "deferred"
    if event.type == "delay":
        return f"Бригада {event.engineer_id} задержалась на {event.delay_min} мин, хвост пересчитан", "shifted"
    if event.type == "engineer_off":
        return f"Бригада {event.engineer_id} выбыла, её заявки перераспределены", "shifted"
    return "Пересчитано", "shifted"


def simulate(dataset: Dataset, matrices: Matrices, spec: ScenarioSpec) -> SimulationResult:
    """Утренний план, события дня и прогон по статическому и выбранному правилу."""
    overrides = deepcopy(spec.settings or {})
    overrides.setdefault("options", {})["time_limit_s"] = spec.time_limit_s
    with settings.use(overrides):
        start = settings.option("start") or "office"
        morning, _ = solve(dataset, matrices, plan_id="morning", start=start)
        events = make_events(dataset, morning, spec, matrices)
        policies = ["static"] + ([] if spec.policy == "static" else [spec.policy])
        runs = [run_policy(dataset, matrices, morning, events, policy, spec) for policy in policies]
    labels = [{"key": k, "label": label, "unit": unit, "less_is_better": less}
              for k, (label, unit, less) in KPI_LABELS.items()]
    return SimulationResult(spec=spec, events=events, runs=runs, kpi_labels=labels)


def main(argv: list[str] | None = None) -> int:
    """Прогнать имитацию региона и записать итог в data/simulation."""
    from .loader import load_dataset, load_matrices

    parser = argparse.ArgumentParser(description="Имитация операционного дня")
    parser.add_argument("dataset")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--new", type=int, default=6)
    parser.add_argument("--cancels", type=int, default=2)
    parser.add_argument("--no-shows", type=int, default=2)
    parser.add_argument("--reschedules", type=int, default=1)
    parser.add_argument("--delays", type=int, default=1)
    parser.add_argument("--off", type=int, default=0)
    parser.add_argument("--policy", default="offer", choices=["offer", "direct", "static"])
    parser.add_argument("--accept", type=float, default=0.7)
    parser.add_argument("--time-limit", type=int, default=3)
    parser.add_argument("--settings", default=None, help="JSON с переопределениями настроек")
    args = parser.parse_args(argv)
    spec = ScenarioSpec(
        dataset_id=args.dataset, seed=args.seed, new_requests=args.new, cancels=args.cancels,
        no_shows=args.no_shows, reschedules=args.reschedules, delays=args.delays, engineer_off=args.off,
        policy=args.policy, accept_prob=args.accept, time_limit_s=args.time_limit,
        settings=json.loads(args.settings) if args.settings else None,
    )
    result = simulate(load_dataset(args.dataset), load_matrices(args.dataset), spec)
    SIM_DIR.mkdir(parents=True, exist_ok=True)
    out = SIM_DIR / f"{args.dataset}-{args.seed}-{args.policy}.json"
    slim = result.model_dump()
    for run in slim["runs"]:
        run.pop("plan", None)
    Path(out).write_text(json.dumps(slim, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for run in result.runs:
        print(run.policy, json.dumps(run.kpis, ensure_ascii=False))
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
