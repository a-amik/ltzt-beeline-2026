"""Набор «Вся Москва»: три участка заказчика одним днём — и матрицы к нему.

Диспетчеру участки не нужны как отдельные наборы: он смотрит на всё сразу
и фильтрует то, что ему нужно. Набор складывается из собранных наборов
участков (`prepare.py`) как есть; у каждой заявки и бригады появляется поле
`sector`, у набора — список участков со своими офисами.

Что меняется от сложения:

1. **Старт из офиса — из своего.** Бригада стартует из офиса своего участка
   (`baseline.office_of`), точка `office:<участок>` лежит в матрице.
2. **Чужой участок разрешён, но стоит денег.** Эксперт Билайна назвал выезды
   в чужой участок нерациональной логистикой. Каждый въезд в другой участок
   стоит `economy.sector_cross_rub` — в цели поиска и в деньгах дня
   (`economy.summarize`, строка «Выезды в чужой участок»).
3. **Совпадающие идентификаторы разводятся.** Бригада с тем же идентификатором
   в двух участках и сценарные события (`e1`—`e3`, срочная `u-1`) получают
   приставку участка; контроль и события следуют за переименованием.

Матрицы считает тот же `matrices.build_for`, что и матрицы участков: OSRM
для машины, велосипеда и пешком, общественный транспорт — из пешей.

Запуск: `uv run python -m bee_routing.moscow` (нужен OSRM, как для `matrices`).
"""

from __future__ import annotations

import json
from collections import Counter

from .geocode import load_assumptions
from .matrices import DATASETS_DIR, MATRICES_DIR, build_for

MOSCOW_ID = "moskva"
MOSCOW_NAME = "Вся Москва"
SECTORS = ("vostok", "yugo-vostok", "yugocentr")
# Офис набора — точка по умолчанию для карты и для бригад без участка; у бригад набора свой.
CENTER = "yugocentr"


def build(parts: dict[str, dict]) -> dict:
    """Сложить наборы участков в один; `parts` — участок → набор по контракту."""
    engineer_ids = Counter(e["id"] for part in parts.values() for e in part["engineers"])
    out: dict = {
        "id": MOSCOW_ID,
        "name": MOSCOW_NAME,
        "date": next(iter(parts.values()))["date"],
        "office": parts[CENTER]["office"] if CENTER in parts else next(iter(parts.values()))["office"],
        "sectors": [{"id": sid, "name": part["name"], "office": part["office"]} for sid, part in parts.items()],
        "requests": [],
        "engineers": [],
        "events": [],
        "control": [],
    }
    for sid, part in parts.items():
        rename = {e["id"]: (f"{e['id']}-{sid}" if engineer_ids[e["id"]] > 1 else e["id"]) for e in part["engineers"]}
        office = part["office"]
        for req in part["requests"]:
            out["requests"].append({**req, "sector": sid})
        for eng in part["engineers"]:
            out["engineers"].append(
                {**eng, "id": rename[eng["id"]], "sector": sid, "start": {"lat": office["lat"], "lon": office["lon"]}}
            )
        for event in part.get("events", []):
            moved = {**event, "id": f"{sid}-{event['id']}"}
            if event.get("engineer_id"):
                moved["engineer_id"] = rename.get(event["engineer_id"], event["engineer_id"])
            if event.get("request"):
                moved["request"] = {**event["request"], "id": f"{sid}-{event['request']['id']}", "sector": sid}
            out["events"].append(moved)
        for row in part.get("control", []):
            out["control"].append({**row, "engineer_id": rename.get(row["engineer_id"], row["engineer_id"])})
    return out


def main() -> int:
    """Собрать набор и посчитать его матрицы."""
    parts = {}
    for sid in SECTORS:
        path = DATASETS_DIR / f"{sid}.json"
        if not path.exists():
            print(f"Нет набора участка {sid}: сначала `python -m bee_routing.prepare`")
            return 1
        parts[sid] = json.loads(path.read_text(encoding="utf-8"))
    data = build(parts)
    (DATASETS_DIR / f"{MOSCOW_ID}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tables, notes = build_for(data, load_assumptions())
    MATRICES_DIR.mkdir(parents=True, exist_ok=True)
    for profile, table in tables.items():
        (MATRICES_DIR / f"{MOSCOW_ID}-{profile}.json").write_text(json.dumps(table, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"{MOSCOW_NAME}: заявок {len(data['requests'])}, бригад {len(data['engineers'])}, "
        f"точек в матрице {len(tables['car']['ids'])}"
    )
    print("\n".join(notes) if notes else "Все матрицы посчитаны OSRM.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
