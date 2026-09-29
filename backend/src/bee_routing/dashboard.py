"""Сводка руководителя: один план «Всей Москвы» и его разбивка по участкам.

Руководителю нужны четыре ответа: идёт ли день к цели, где не хватает людей,
во что обходится день и где горит сейчас. Всё считается по одному плану города
(`moscow.py`), а участки — его разбивка, поэтому итоги не складываются дважды:
раньше «Вся Москва» стояла рядом с участками и попадала в сумму.

Что отдаётся (`GET /manager/dashboard`):

- `totals`, `sectors` — вовремя, бригады, загрузка смены, пробег, итог дня;
- `hours` — сколько визитов по плану к концу часа, сколько отмечено сделанными,
  сколько окон к этому часу уже закрылось;
- `load` — участки × окна: спрос к тому, что бригады могут закрыть
  (`deficit.deficit_map`, районы сложены в участки);
- `crews` — нормо-минуты бригады против нормы дня, сверх нормы, бонус;
- `economy` — из чего сложился итог дня по участкам: ценность выполненного,
  оклады, бонусы, дорога, ожидание, чужой участок — те же слагаемые, что
  в итоге плана (`economy.summarize`), и сумма участков с ним сходится;
- `signals` — SOS, проблемы, задержки, вопросы контроля и заявки без бригады;
- `versus` — наш план против контроля заказчика (прогон сравнения) и надёжность
  на синтетических днях (прогон гонки).

Считает только то, что уже есть в плане и в файлах прогонов; ничего не решает.
"""

from __future__ import annotations

import json
from collections import defaultdict
from statistics import mean

from .checks import to_min
from .deficit import _level, deficit_map
from .economy import request_value, sector_entries, tariffs, travel_cost, wait_cost
from .geocode import DATA_DIR
from .models import Dataset, Mark, Plan
from .replan import known_requests

HOURS = list(range(8, 23))
SIGNAL_KINDS = ("sos", "problem", "delay", "flag")
SEVERITY = {"sos": 0, "problem": 1, "unassigned": 2, "delay": 3, "flag": 4}


def _sectors(data: Dataset) -> list[tuple[str, str]]:
    return [(s.id, s.name) for s in data.sectors] or [(data.id, data.name)]


def _sector_of_request(data: Dataset) -> dict[str, str]:
    return {r.id: (r.sector or data.id) for r in data.requests}


def _sector_of_crew(data: Dataset) -> dict[str, str]:
    return {e.id: (e.sector or data.id) for e in data.engineers}


def _hour_index(clock: str) -> int:
    """Час, к концу которого событие уже случилось: 10:20 → индекс часа 10."""
    minute = to_min(clock)
    for i, hour in enumerate(HOURS):
        if minute < (hour + 1) * 60:
            return i
    return len(HOURS) - 1


def _cumulative(counts: list[int]) -> list[int]:
    out, acc = [], 0
    for value in counts:
        acc += value
        out.append(acc)
    return out


def figures(plan: Plan, data: Dataset, targets: dict) -> dict:
    """Итоги города и участков: вовремя, бригады, загрузка, пробег, итог дня."""
    of_req = _sector_of_request(data)
    of_crew = _sector_of_crew(data)
    shift = {e.id: to_min(e.shift_end) - to_min(e.shift_start) for e in data.engineers}

    def block(sector: str | None) -> dict:
        routes = [r for r in plan.routes if sector is None or of_crew.get(r.engineer_id) == sector]
        used = [r for r in routes if r.stops]
        stops = [s for r in plan.routes for s in r.stops if sector is None or of_req.get(s.request_id) == sector]
        unassigned = [u for u in plan.unassigned if sector is None or of_req.get(u.request_id) == sector]
        deferred = [d for d in plan.deferred if sector is None or of_req.get(d.request_id) == sector]
        visits = [s for s in stops if s.status != "no_show"]
        on_time = sum(1 for s in visits if s.late_min == 0)
        total = len(stops) + len(unassigned) + len(deferred)
        busy = [(r.travel_min + r.work_min) / max(shift.get(r.engineer_id, 720), 1) for r in used]
        crews_total = sum(1 for e in data.engineers if sector is None or of_crew.get(e.id) == sector)
        on_time_pct = round(100 * on_time / total, 1) if total else 0.0
        utilization = round(100 * mean(busy), 1) if busy else 0.0
        return {
            "requests": total, "on_time": on_time, "on_time_pct": on_time_pct,
            "late": sum(1 for s in visits if s.late_min > 0),
            "crews_used": len(used), "crews_total": crews_total, "utilization_pct": utilization,
            "km": round(sum(r.distance_km for r in used), 1),
            "unassigned": len(unassigned), "deferred": len(deferred),
            "ok": {"on_time": on_time_pct >= targets["on_time_pct"], "utilization": utilization >= targets["utilization_pct"]},
        }

    totals = block(None)
    totals["net_rub"] = plan.economy.net_rub if plan.economy else 0
    return {"totals": totals, "sectors": [{"id": sid, "name": name, **block(sid)} for sid, name in _sectors(data)]}


def hours(plan: Plan, data: Dataset, marks: list[Mark]) -> dict:
    """День по часам: визиты по плану к концу часа, отмеченные сделанными, окна, закрывшиеся к этому часу."""
    by_id = {r.id: r for r in known_requests(plan, data)}
    planned = [0] * len(HOURS)
    due = [0] * len(HOURS)
    for route in plan.routes:
        for stop in route.stops:
            if stop.status == "no_show":
                continue
            planned[_hour_index(stop.end)] += 1
            request = by_id.get(stop.request_id)
            if request is not None:
                due[_hour_index(request.window_end)] += 1
    for item in plan.unassigned:
        request = by_id.get(item.request_id)
        if request is not None:
            due[_hour_index(request.window_end)] += 1
    done = [0] * len(HOURS)
    for mark in marks:
        if mark.kind == "done":
            done[_hour_index(mark.time)] += 1
    return {"hours": HOURS, "planned": _cumulative(planned), "done": _cumulative(done), "due": _cumulative(due)}


def load(plan: Plan, data: Dataset) -> dict:
    """Участки × окна: районы карты дефицита сложены в свои участки, давление пересчитано так же."""
    result = deficit_map(plan, data)
    district = {r.district: (r.sector or data.id) for r in data.requests}
    sums: dict[tuple[str, str], dict[str, float]] = defaultdict(lambda: {"d": 0.0, "s": 0.0, "f": 0.0, "u": 0.0})
    for area in result.areas:
        sector = district.get(area.district, data.id)
        for slot in area.slots:
            cell = sums[(sector, slot.window)]
            cell["d"] += slot.demand_min
            cell["s"] += slot.served_min
            cell["f"] += slot.free_min
            cell["u"] += slot.unassigned
    rows = []
    for sid, name in _sectors(data):
        cells = []
        for window in result.windows:
            t = sums[(sid, window)]
            pressure = round(t["d"] / max(t["s"] + t["f"], 1.0), 2) if t["d"] else 0.0
            level = _level(pressure, int(t["f"]), int(t["u"])) if t["d"] or t["f"] else "ok"
            cells.append({"window": window, "pressure": pressure, "level": level,
                          "demand_min": round(t["d"]), "unassigned": int(t["u"])})
        rows.append({"id": sid, "name": name, "cells": cells})
    return {"windows": result.windows, "rows": rows}


def crews(plan: Plan, data: Dataset, conf: dict, signals: list[dict]) -> list[dict]:
    """Бригады в работе: нормо-минуты против нормы дня, сверх нормы, бонус; по убыванию нагрузки."""
    norm_day = int(conf["norm_day_min"])
    of_crew = _sector_of_crew(data)
    names = {e.id: e.name for e in data.engineers}
    alarms: dict[str, set[str]] = defaultdict(set)
    for item in signals:
        if item.get("engineer_id"):
            alarms[item["engineer_id"]].add(item["kind"])
    out = []
    for route in plan.routes:
        if not route.stops:
            continue
        norm = int(route.norm_min or 0)
        out.append({
            "id": route.engineer_id, "name": names.get(route.engineer_id, route.engineer_id),
            "sector": of_crew.get(route.engineer_id), "visits": len(route.stops),
            "norm_min": norm, "norm_day": norm_day, "over_min": max(0, norm - norm_day),
            "bonus_rub": int(route.bonus_rub or 0), "km": route.distance_km,
            "late": sum(1 for s in route.stops if s.late_min > 0),
            "alarms": sorted(alarms.get(route.engineer_id, set())),
        })
    return sorted(out, key=lambda c: -c["norm_min"])


def economy(plan: Plan, data: Dataset, conf: dict) -> dict:
    """Из чего сложился итог дня по участкам: всё — по участку бригады, которая работала."""
    by_id = {r.id: r for r in known_requests(plan, data)}
    of_crew = _sector_of_crew(data)
    crews_by_id = {e.id: e for e in data.engineers}
    rate = int(conf.get("sector_cross_rub", 0))
    parts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for route in plan.routes:
        if not route.stops:
            continue
        part = parts[of_crew.get(route.engineer_id, data.id)]
        part["value_rub"] += sum(request_value(by_id[s.request_id], conf) for s in route.stops
                                 if s.status != "no_show" and s.request_id in by_id)
        part["payroll_rub"] += int(conf["engineer_day_rub"])
        part["bonus_rub"] += int(route.bonus_rub or 0)
        part["travel_rub"] += travel_cost(route, conf)
        part["wait_rub"] += wait_cost(route, conf)
        part["sector_rub"] += rate * sector_entries(crews_by_id.get(route.engineer_id),
                                                    [s.request_id for s in route.stops], by_id)
    keys = ("value_rub", "payroll_rub", "bonus_rub", "travel_rub", "wait_rub", "sector_rub")
    rows = []
    for sid, name in _sectors(data):
        p = parts.get(sid, {})
        values = {k: int(p.get(k, 0)) for k in keys}
        cost = sum(values[k] for k in keys if k != "value_rub")
        rows.append({"id": sid, "name": name, **values, "net_rub": values["value_rub"] - cost})
    return {"sectors": rows}


def signals(feed: list[dict], plan: Plan, data: Dataset) -> list[dict]:
    """Сигналы дня: SOS, проблемы, задержки, вопросы контроля — и заявки без бригады; срочное сверху."""
    of_req = _sector_of_request(data)
    of_crew = _sector_of_crew(data)
    out = []
    for item in feed:
        if item.get("kind") not in SIGNAL_KINDS or item.get("author") == "dispatcher":
            continue
        out.append({"kind": item["kind"], "time": item.get("time") or "", "engineer_id": item.get("engineer_id"),
                    "engineer": item.get("engineer"), "request_id": item.get("request_id"), "text": item.get("text", ""),
                    "sector": of_crew.get(item.get("engineer_id") or "") or of_req.get(item.get("request_id") or "")})
    for item in plan.unassigned:
        out.append({"kind": "unassigned", "time": "", "engineer_id": None, "engineer": None,
                    "request_id": item.request_id, "text": item.reason, "sector": of_req.get(item.request_id)})
    return sorted(out, key=lambda x: (SEVERITY.get(x["kind"], 9), -to_min(x["time"]) if x["time"] else 0))


def versus(start: str, dataset_id: str) -> dict:
    """Наш план против контроля заказчика: прогон сравнения и синтетические дни гонки.

    В прогоне сравнения может быть и сам набор города, и его участки: берётся строка
    набора, а сумма участков — только если её нет, иначе день посчитался бы дважды.
    """
    out: dict = {}
    try:
        report = json.loads((DATA_DIR / "benchmark" / "report.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        report = []
    own = [region for region in report if region["dataset_id"] == dataset_id]
    report = own or [region for region in report if "@" not in region["dataset_id"] and region["dataset_id"] != "moskva"]
    if report:
        keys = ("on_time", "requests_total", "engineers_used", "distance_km", "net_rub")
        sums = {role: dict.fromkeys(keys, 0.0) for role in ("control", "solver")}
        for region in report:
            for row in region["rows"]:
                if row["key"] in sums:
                    for k in keys:
                        sums[row["key"]][k] += float(row["kpis"].get(k, 0))
        out["benchmark"] = {role: {k: round(v, 1) for k, v in vals.items()} for role, vals in sums.items()}
    try:
        race = json.loads((DATA_DIR / "race" / "race.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        race = None
    if race:
        runs = [r for r in race["runs"] if r["mode"] == "normal" and r.get("start", "office") == start] \
            or [r for r in race["runs"] if r["mode"] == "normal"]
        if runs:
            def share(player: str) -> float:
                return round(100 * sum(r["players"][player]["on_time"] for r in runs) / max(sum(r["due"] for r in runs), 1), 1)

            out["race"] = {
                "days": len(runs), "start": runs[0].get("start", start),
                "ours_pct": share("ours"), "control_pct": share("control"), "baseline_pct": share("baseline"),
                "ours_best": sum(1 for r in runs if r["players"]["ours"]["on_time"] >= r["players"]["control"]["on_time"]),
            }
    return out


def dashboard(plan: Plan, data: Dataset, marks: list[Mark], feed: list[dict], targets: dict, start: str) -> dict:
    """Всё для экрана руководителя одним ответом."""
    conf = tariffs()
    sig = signals(feed, plan, data)
    return {
        "dataset_id": data.id, "name": data.name, "date": data.date, "plan_id": plan.id,
        "targets": targets,
        **figures(plan, data, targets),
        "hours": hours(plan, data, marks),
        "load": load(plan, data),
        "crews": crews(plan, data, conf, sig),
        "economy": economy(plan, data, conf),
        "signals": sig[:40],
        "versus": versus(start, data.id),
    }
