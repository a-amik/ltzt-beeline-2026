"""Гонка планов: контроль, базовый вариант и наш план на одних событиях дня.

Заявки у всех трёх одни — день заказчика 17 августа, — и события дня тоже
одни, минута в минуту: новые заявки, отмены, «клиента нет», переносы окна,
задержки и выбытия бригад собираются по зерну (`simulate.make_events`).
Каждый участок проживает день столько раз, сколько зёрен, и счёт копится
по прогонам — как у транспортного стенда модели копят счёт по датам.

Утро у каждого своё:

- **контроль** — распределение из файла заказчика (`control.control_plan`);
- **базовый** — правило п. 2.3 задания (`baseline.build_baseline`);
- **наш** — решатель с текущими настройками; утро по ключу считается один раз (`mornings.py`).

Правило ответа на события тоже своё, и это главное условие честности:

- контроль и базовый отвечают **правилом п. 2.3** — новую заявку получает
  первый по порядку во входных данных инженер, которому она по силам
  в конец маршрута; порядок визитов не пересобирается, задержка сдвигает
  хвост, заявки выбывшей бригады раздаются тем же правилом. Это единственное
  правило ответа, которое заказчик назвал сам;
- наш план отвечает своим перепланировщиком (`simulate.run_policy`),
  новая заявка отдаётся лучшему кандидату.

Счёт — доля заявок дня, сделанных вовремя: утренние плюс пришедшие днём,
минус отменённые и те, где клиента не оказалось. Рядом — бригады в работе,
пробег (две обязательные метрики задания) и итог дня в рублях по тарифам
из допущений.

Запуск: `uv run python -m bee_routing.race [--seeds 20] [--workers 4]`
пишет `data/race/race.json`; экран «Имитация» читает его через `GET /race`.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from . import settings
from .baseline import append, build_baseline, new_states
from .checks import check_visit, feasible, to_min, visit_times
from .control import control_plan
from .economy import summarize
from .geocode import DATA_DIR
from .matrices import Matrices
from .mornings import morning as cached_morning
from .metrics import compute_metrics
from .models import Dataset, Event, Plan, Request, ScenarioSpec, Unassigned
from .travel import leg

RACE_DIR = DATA_DIR / "race"
REGIONS = ("vostok", "yugo-vostok", "yugocentr")
PLAYERS = ("control", "baseline", "ours")
HOURS = list(range(8, 23))

# Режимы: обычный день — счётчики нынешней имитации по умолчанию; тяжёлый —
# вдвое больше событий и одна выбывшая бригада. new=None — доля региона
# из настройки intraday_share_pct (Билайн: 10—15 % заявок день в день).
MODES: dict[str, dict] = {
    "normal": {"label": "Обычный день", "new": None, "cancels": 2, "no_shows": 2, "reschedules": 1,
               "delays": 1, "off": 0},
    "hard": {"label": "Тяжёлый день", "new": 2.0, "cancels": 4, "no_shows": 3, "reschedules": 2,
             "delays": 3, "off": 1},
}

# День из набора: события, которые заказчик положил в набор участка (авария,
# отмена, выбытие бригады), — один прогон на участок и старт, номер набора 0.
DATA_MODE = "data"
DATA_LABEL = "События из набора"

# День без событий: утренние планы как есть, днём ничего не случается. Тот же
# вариант, что в «Живом дне», — один прогон на участок и старт, номер набора 0.
NONE_MODE = "none"
NONE_LABEL = "Без событий"
SINGLE_MODES = (NONE_MODE, DATA_MODE)
# Свои события считаются на месте, по запросу экрана, и в файл гонки не пишутся.
CUSTOM_MODE = "custom"

# Откуда стартуют бригады — одно жёсткое условие для всех трёх планов: иначе
# гонка сравнивает не планы, а точки старта. «Из офиса» — по регламенту и без
# старта дальних бригад из своей зоны; «Гибрид» — дальние из дома, ближние
# из офиса (порог — настройка hybrid_home_km); «Из дома» — по практике.
STARTS: dict[str, dict] = {
    "office": {"label": "Из офиса", "options": {"start": "office", "zone_start": False}},
    "hybrid": {"label": "Гибрид", "options": {"start": "hybrid", "zone_start": False}},
    "home": {"label": "Из дома", "options": {"start": "home"}},
}


@dataclass
class RulePlayer:
    """План, который днём отвечает правилом п. 2.3 и ничего не пересобирает."""

    dataset: Dataset
    matrices: Matrices
    start: str
    order: dict[str, list[str]]
    requests: dict[str, Request]
    unassigned: list[Unassigned]
    appear: dict[str, int] = field(default_factory=dict)
    delay: dict[str, int] = field(default_factory=dict)
    no_show: set[str] = field(default_factory=set)
    off: dict[str, int] = field(default_factory=dict)

    @classmethod
    def of(cls, plan: Plan, dataset: Dataset, matrices: Matrices, start: str | None = None) -> RulePlayer:
        """Проживать план с его утра; `start` — пересчитать утро от другой точки старта."""
        return cls(
            dataset=dataset, matrices=matrices, start=start or plan.start or "office",
            order={r.engineer_id: [s.request_id for s in r.stops] for r in plan.routes},
            requests={req.id: req for req in dataset.requests},
            unassigned=list(plan.unassigned),
        )

    @property
    def engineers(self):
        return settings.effective_engineers(self.dataset.engineers)

    def timed(self, only: str | None = None):
        """Прожить маршруты по порядку: когда бригада где, с задержками и неявками."""
        states = new_states(self.engineers, self.start)
        for eng in self.engineers:
            if only is not None and eng.id != only:
                continue
            state = states[eng.id]
            for rid in self.order.get(eng.id, []):
                req = self.requests[rid]
                depart = max(state.clock, self.appear.get(rid, 0))
                road = leg(eng, state.position, rid, self.matrices, depart)
                state.clock = depart
                times = visit_times(req, depart + road.minutes)
                if rid in self.no_show:
                    times = {**times, "end": times["arrive"] + 5, "start": times["arrive"], "late": 0, "wait": 0}
                times["end"] += self.delay.get(rid, 0)
                append(state, req, times, road.minutes, road.km, road.mode)
                if rid in self.no_show:
                    state.stops[-1].status = "no_show"
                    state.work_min -= req.duration_min
        return states

    def place(self, rid: str, at: int) -> None:
        """Правило п. 2.3: первый по порядку инженер, которому заявка по силам в конец маршрута."""
        req = self.requests[rid]
        self.appear[rid] = at
        for eng in self.engineers:
            if eng.id in self.off:
                continue
            state = self.timed(only=eng.id)[eng.id]
            depart = max(state.clock, at)
            road = leg(eng, state.position, rid, self.matrices, depart)
            checks = check_visit(eng, req, depart + road.minutes, self.matrices,
                                 prev_id=state.position, depart_min=depart)
            if feasible(checks):
                self.order.setdefault(eng.id, []).append(rid)
                return
        self.unassigned.append(Unassigned(request_id=rid, reason="Правило п. 2.3: ни одной бригаде не по силам",
                                          reason_code="no_engineer"))

    def pending(self, at: int) -> dict[str, tuple[str, int, int]]:
        """Где заявка сейчас: бригада, начало и конец работ."""
        out = {}
        for eng_id, state in self.timed().items():
            for s in state.stops:
                out[s.request_id] = (eng_id, to_min(s.start), to_min(s.end))
        return out

    def handle(self, ev: Event) -> None:
        at = to_min(ev.time)
        if ev.type in ("new_request", "urgent") and ev.request is not None:
            self.requests[ev.request.id] = ev.request
            self.place(ev.request.id, at)
        elif ev.type == "cancel" and ev.request_id:
            where = self.pending(at).get(ev.request_id)
            if where and where[1] >= at:
                self.order[where[0]].remove(ev.request_id)
            self.unassigned = [u for u in self.unassigned if u.request_id != ev.request_id]
        elif ev.type == "no_show" and ev.request_id:
            self.no_show.add(ev.request_id)
        elif ev.type == "reschedule" and ev.request_id and ev.window_start and ev.window_end:
            req = self.requests[ev.request_id]
            self.requests[ev.request_id] = req.model_copy(update={"window_start": ev.window_start,
                                                                  "window_end": ev.window_end})
        elif ev.type == "delay" and ev.engineer_id:
            stops = [(rid, a, b) for rid, (eng, a, b) in self.pending(at).items() if eng == ev.engineer_id]
            now = [s for s in stops if s[1] <= at < s[2]] or sorted((s for s in stops if s[1] >= at), key=lambda s: s[1])
            if now:
                self.delay[now[0][0]] = self.delay.get(now[0][0], 0) + int(ev.delay_min or 0)
        elif ev.type == "engineer_off" and ev.engineer_id:
            where = self.pending(at)
            left = [rid for rid in self.order.get(ev.engineer_id, []) if where.get(rid, ("", 0, 0))[1] >= at]
            self.order[ev.engineer_id] = [rid for rid in self.order.get(ev.engineer_id, []) if rid not in left]
            self.off[ev.engineer_id] = at
            for rid in left:
                self.place(rid, at)

    def plan(self, plan_id: str, algorithm: str, events: list[Event] | None = None) -> Plan:
        states = self.timed()
        routes = [states[eng.id].to_route() for eng in self.engineers]
        plan = Plan(id=plan_id, dataset_id=self.dataset.id, algorithm=algorithm, start=self.start,
                    created_at="", routes=routes, unassigned=self.unassigned,
                    metrics=compute_metrics(routes, self.unassigned), history=list(events or []))
        plan.economy = summarize(plan, self.dataset, requests=list(self.requests.values()))
        return plan


def score(plan: Plan, dataset: Dataset, requests: list[Request], due: set[str]) -> dict:
    """Счёт прогона: вовремя из заявок дня, бригады, пробег, рубли, часы."""
    econ = summarize(plan, dataset, requests=requests)
    stops = [s for r in plan.routes for s in r.stops if s.status != "no_show" and s.request_id in due]
    on_time = [s for s in stops if s.late_min == 0]
    late = [s for s in stops if s.late_min > 0]
    return {
        "on_time": len(on_time),
        "late": len(late),
        "late_min": sum(s.late_min for s in late),
        "missed": len(due) - len(stops),
        "engineers": sum(1 for r in plan.routes if r.stops),
        "km": round(sum(r.distance_km for r in plan.routes), 1),
        "net_rub": econ.net_rub,
        "done_by_hour": [sum(1 for s in on_time if to_min(s.end) <= h * 60 + 60) for h in HOURS],
        "late_by_hour": [sum(1 for s in late if h * 60 <= to_min(s.start) < h * 60 + 60) for h in HOURS],
    }


def spec_for(region: str, mode: str, seed: int, dataset: Dataset) -> ScenarioSpec:
    conf = MODES[mode]
    base = round(len(dataset.requests) * float(settings.option("intraday_share_pct") or 0) / 100)
    new = None if conf["new"] is None else round(base * conf["new"])
    return ScenarioSpec(dataset_id=region, seed=seed, new_requests=new, cancels=conf["cancels"],
                        no_shows=conf["no_shows"], reschedules=conf["reschedules"], delays=conf["delays"],
                        engineer_off=conf["off"], policy="direct", time_limit_s=3)


def run_one(region: str, mode: str, seed: int, start: str = "office", custom: list | None = None) -> dict:
    """Один прогон дня: три утра от одной точки старта, одни события, три правила ответа.

    `custom` — свои события (режим custom): только они, без случайных, как в «Живом дне».
    """
    from .loader import load_dataset, load_matrices
    from .simulate import make_events, run_policy

    started = time.perf_counter()
    dataset, matrices = load_dataset(region), load_matrices(region)
    spec = spec_for(region, "normal" if mode in SINGLE_MODES or mode == CUSTOM_MODE else mode, seed, dataset)
    if mode == CUSTOM_MODE:
        spec = spec.model_copy(update={"new_requests": 0, "cancels": 0, "no_shows": 0, "reschedules": 0,
                                       "delays": 0, "engineer_off": 0, "custom": list(custom or [])})
    options = {"time_limit_s": spec.time_limit_s, **STARTS[start]["options"]}
    with settings.use({"options": options}):
        where = str(settings.option("start"))
        control = control_plan(dataset, matrices)
        events = ([] if mode == NONE_MODE
                  else sorted(dataset.events, key=lambda e: to_min(e.time)) if mode == DATA_MODE
                  else make_events(dataset, control, spec, matrices))
        mornings = {
            "control": control,
            "baseline": build_baseline(dataset, matrices, plan_id="baseline", start=where)[0],
        }
        ours_morning = cached_morning(dataset, matrices, where, spec.time_limit_s)
        # Контроль — распределение заказчика; точка старта у него та же, что у двух других.
        finals = {name: _live(RulePlayer.of(plan, dataset, matrices, start=where), events).plan(name, name)
                  for name, plan in mornings.items()}
        finals["ours"] = run_policy(dataset, matrices, ours_morning, events, "direct", spec).plan
    fresh = [e.request for e in events if e.type in ("new_request", "urgent") and e.request is not None]
    gone = {e.request_id for e in events if e.type in ("cancel", "no_show") and e.request_id}
    requests = [*dataset.requests, *fresh]
    due = {r.id for r in requests} - gone
    windows = {r.id: r.window_end for r in requests}
    for e in events:
        if e.type == "reschedule" and e.request_id and e.window_end:
            windows[e.request_id] = e.window_end
    return {
        "region": region, "mode": mode, "seed": seed, "start": start,
        "due": len(due),
        "demand_by_hour": [sum(1 for rid in due if h * 60 <= to_min(windows[rid]) < h * 60 + 60) for h in HOURS],
        "events": [{"t": e.time, "type": e.type} for e in events],
        "players": {name: score(plan, dataset, requests, due) for name, plan in finals.items()},
        "seconds": round(time.perf_counter() - started, 1),
    }


def day(dataset_id: str, spec: ScenarioSpec) -> dict:
    """Один день по сценарию для «Живого дня»: контроль по правилу п. 2.3 и наш план на одних событиях.

    Экран проигрывает оба плана на двух картах; события приходят в плане
    историей, новые заявки — отдельным списком, чтобы их точки были на карте.
    """
    from .loader import load_dataset, load_matrices
    from .simulate import make_events, run_policy

    dataset, matrices = load_dataset(dataset_id), load_matrices(dataset_id)
    with settings.use({**(spec.settings or {}), "options": {**((spec.settings or {}).get("options") or {}),
                                                            "time_limit_s": spec.time_limit_s}}):
        # Старт у обоих планов один, как в гонке: иначе сравниваются точки старта, а не планы.
        where = str(settings.option("start"))
        control = control_plan(dataset, matrices)
        events = (sorted(dataset.events, key=lambda e: to_min(e.time)) if spec.events_from == "data"
                  else make_events(dataset, control, spec, matrices))
        theirs = _live(RulePlayer.of(control, dataset, matrices, start=where), events).plan(
            "control-day", "control", events)
        morning = cached_morning(dataset, matrices, where, spec.time_limit_s)
        ours = run_policy(dataset, matrices, morning, events, spec.policy if spec.policy != "static" else "direct",
                          spec).plan
    fresh = [e.request for e in events if e.type in ("new_request", "urgent") and e.request is not None]
    return {
        "control": theirs.model_dump(mode="json"),
        "ours": ours.model_dump(mode="json"),
        "requests": [r.model_dump(mode="json") for r in fresh],
        "events": [e.model_dump(mode="json") for e in events],
    }


def morning_ready(dataset_id: str, start: str, overrides: dict | None, time_limit_s: int) -> bool:
    """Готово ли утро сценария: те же настройки и старт, что у `day` и `run_one`."""
    from .loader import load_dataset
    from .mornings import is_ready

    base = overrides or {}
    options = {**(base.get("options") or {}), **STARTS[start]["options"], "time_limit_s": time_limit_s}
    with settings.use({**base, "options": options}):
        return is_ready(load_dataset(dataset_id), str(settings.option("start")), time_limit_s)


def sets(dataset_id: str, kind: str, start: str, overrides: dict | None = None, seeds: int = 20) -> list[dict]:
    """Состав случайных наборов событий — чтобы экран сказал, что в каком наборе случится.

    Наборы те же, что у гонки и «Живого дня»: то же зерно, те же счётчики
    типа дня, то же утро контроля, от которого генератор выбирает визиты.
    """
    from .loader import load_dataset, load_matrices
    from .simulate import make_events

    dataset, matrices = load_dataset(dataset_id), load_matrices(dataset_id)
    base = overrides or {}
    options = {**(base.get("options") or {}), **STARTS[start]["options"]}
    out = []
    with settings.use({**base, "options": options}):
        control = control_plan(dataset, matrices)
        for seed in range(1, seeds + 1):
            events = make_events(dataset, control, spec_for(dataset_id, kind, seed, dataset), matrices)
            out.append({"seed": seed, "events": [
                {"time": e.time, "type": e.type, "delay_min": e.delay_min} for e in events]})
    return out


def load(path: Path | None = None) -> dict | None:
    """Готовый файл гонки или None, если его ещё не посчитали."""
    path = path or RACE_DIR / "race.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _live(player: RulePlayer, events: list[Event]) -> RulePlayer:
    for ev in events:
        player.handle(ev)
    return player


def _task(args: tuple[str, str, int, str]) -> dict:
    return run_one(*args)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Гонка планов: контроль, базовый и наш на одних событиях")
    parser.add_argument("--seeds", type=int, default=20)
    parser.add_argument("--modes", default=",".join(MODES))
    parser.add_argument("--starts", default=",".join(STARTS))
    parser.add_argument("--regions", default=",".join(REGIONS))
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--out", default=str(RACE_DIR / "race.json"))
    parser.add_argument("--append", action="store_true",
                        help="дописать прогоны в готовый файл, заменив совпавшие (участок, режим, набор, старт)")
    args = parser.parse_args(argv)

    # Режимы none и data — день без событий и день из набора: один прогон, номер набора 0.
    tasks = [(region, mode, seed, start) for start in args.starts.split(",") for mode in args.modes.split(",")
             for region in args.regions.split(",")
             for seed in ([0] if mode in SINGLE_MODES else range(1, args.seeds + 1))]
    started = time.perf_counter()
    runs: list[dict] = []
    # Решатель в каждом прогоне держит свой портфель процессов, и закрытие пула
    # ждёт их без конца: файл пишется сразу после последнего прогона, выход — жёсткий.
    pool = ProcessPoolExecutor(max_workers=args.workers)
    for i, run in enumerate(pool.map(_task, tasks), 1):
        runs.append(run)
        p = run["players"]
        print(f"[{i}/{len(tasks)}] {run['start']} {run['mode']} {run['region']} #{run['seed']}: "
              + " · ".join(f"{k} {v['on_time']}/{run['due']}" for k, v in p.items())
              + f" · {run['seconds']} с", flush=True)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    labels = {**{k: v["label"] for k, v in MODES.items()}, DATA_MODE: DATA_LABEL, NONE_MODE: NONE_LABEL}
    modes = [m for m in args.modes.split(",")]
    if args.append and out.exists():
        old = json.loads(out.read_text(encoding="utf-8"))
        key = lambda r: (r["region"], r["mode"], r["seed"], r.get("start", "office"))  # noqa: E731
        fresh = {key(r) for r in runs}
        runs = [r for r in old["runs"] if key(r) not in fresh] + runs
        modes = list(dict.fromkeys([*old["meta"].get("modes", {}), *modes]))
        args.seeds = old["meta"].get("seeds", args.seeds)
    report = {
        "meta": {"seeds": args.seeds, "regions": args.regions.split(","), "hours": HOURS,
                 "modes": {k: labels[k] for k in modes if k in labels},
                 "starts": {k: v["label"] for k, v in STARTS.items() if k in args.starts.split(",")},
                 "spec": {k: {kk: vv for kk, vv in v.items() if kk != "label"} for k, v in MODES.items()},
                 "players": list(PLAYERS), "seconds": round(time.perf_counter() - started, 1)},
        "runs": runs,
    }
    out.write_text(json.dumps(report, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"→ {out}", flush=True)
    # Процессы пула и их портфели гасятся руками: иначе остаются сиротами.
    workers = list(getattr(pool, "_processes", {}) or {})
    pool.shutdown(wait=False, cancel_futures=True)
    for pid in workers:
        subprocess.run(["pkill", "-P", str(pid)], check=False)
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    return 0


if __name__ == "__main__":
    code = main()
    os._exit(code)
