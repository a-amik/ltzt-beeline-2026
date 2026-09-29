"""Дописать датасету то, что считается из него самого: устройства и удалённые подучастки.

Две вещи, у которых нет источника в файлах заказчика, но есть правило:

- **устройства заявки** — синтетика по типу заявки (`equipment.py`);
- **удалённость бригады** (`remote_km`) — медиана расстояния её визитов
  в контроле от офиса, по прямой. По ней опция «удалённые бригады стартуют
  из своей зоны» решает, кому при регламентном старте из офиса всё равно
  начинать день там, где он работает: у Каширы и Ступино это 85—95 км,
  у остальных бригад Юго-востока — до 20.

Вызывается сборкой (`prepare.py`), загрузкой своего файла (`upload.py`)
и руками для уже собранных датасетов: `uv run python -m bee_routing.enrich`.
"""

from __future__ import annotations

import json
from pathlib import Path
from statistics import median

from .distance import haversine_km
from .equipment import enrich as add_equipment
from .geocode import load_assumptions


def remote_km(dataset: dict) -> dict[str, float]:
    """Медиана расстояния визитов бригады в контроле от офиса, км; без визитов — 0."""
    office = dataset["office"]
    coords = {req["id"]: (req["lat"], req["lon"]) for req in dataset.get("requests", [])}
    visits: dict[str, list[float]] = {}
    for row in dataset.get("control", []):
        point = coords.get(row.get("request_id"))
        if point is None:
            continue
        visits.setdefault(row["engineer_id"], []).append(
            haversine_km(office["lat"], office["lon"], point[0], point[1])
        )
    return {eng_id: round(median(values), 1) for eng_id, values in visits.items() if values}


def apply(dataset: dict, conf: dict | None = None) -> dict:
    """Устройства заявкам и удалённость бригадам — на месте; вернуть датасет."""
    conf = conf or load_assumptions()
    add_equipment(dataset, conf)
    # День без контроля (дни сверх 17 августа) берёт удалённость у бригад первого дня региона.
    far = remote_km(dataset) if dataset.get("control") else {
        eng["id"]: eng.get("remote_km", 0.0) for eng in dataset.get("engineers", [])}
    rules = conf.get("engineers", {})
    remote_set = [t for t in rules.get("remote_transports", []) if t]
    threshold = float(rules.get("zone_start_km", 40))
    for eng in dataset.get("engineers", []):
        eng["remote_km"] = far.get(eng["id"], 0.0)
        # Билайн, 19.09.2026: местные монтажники дальних городов преимущественно на машине.
        # Набор и порог — в допущениях (`engineers.remote_transports`, `zone_start_km`);
        # диспетчер правит транспорт бригады в настройках.
        if remote_set and eng["remote_km"] >= threshold:
            eng["transports"], eng["transport"] = list(remote_set), remote_set[0]
        eng.pop("anchor", None)
        eng.pop("anchor_name", None)
        home = eng.get("home")
        if home and eng["remote_km"] >= threshold:
            # Опорная точка района — ближайшая к дому из допущений (`engineers.anchors`).
            near = min(rules.get("anchors", []), default=None,
                       key=lambda a: haversine_km(home["lat"], home["lon"], a["lat"], a["lon"]))
            if near and haversine_km(home["lat"], home["lon"], near["lat"], near["lon"]) <= float(
                    rules.get("anchor_radius_km", 20)):
                eng["anchor"] = {"lat": near["lat"], "lon": near["lon"]}
                eng["anchor_name"] = near["name"]
    return dataset


def main() -> int:
    """Дописать устройства и удалённость во все собранные датасеты."""
    from .loader import DATASETS_DIR

    conf = load_assumptions()
    threshold = float(conf.get("engineers", {}).get("zone_start_km", 40))
    for path in sorted(Path(DATASETS_DIR).glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        apply(data, conf)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        with_kit = sum(1 for r in data["requests"] if r["equipment"])
        remote = [f"{e['id']} ({e['remote_km']} км)" for e in data["engineers"] if e["remote_km"] >= threshold]
        print(f"{data['id']}: с устройствами {with_kit} из {len(data['requests'])};"
              f" удалённые бригады: {', '.join(remote) or 'нет'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
