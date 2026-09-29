"""Границы районов Москвы для карты «Нагрузки»: `frontend/public/geo/moscow-districts.geojson`.

Карта закрашивает районы, а не рисует круги, поэтому ей нужны их контуры.
Берутся все районы города (административный уровень 8 внутри округов
Москвы), а не только районы задания: какой бы файл ни загрузили,
его районы найдутся по имени. Подмосковные города задания — Кашира,
Ступино, Домодедово — обводятся по жилой застройке: граница городского
округа в сотни раз больше города и закрасила бы поля.

Источник — выгрузка OpenStreetMap `~/.bee-ltzp/osrm/moscow.osm.pbf`
(© OpenStreetMap contributors, ODbL). Контуры упрощаются до ~30 м: файл
весит сотни килобайт, а не десятки мегабайт, и грузится с экрана сразу.

У каждого района — имя, ключ для сопоставления и точка подписи внутри
контура. Ключ: строчные буквы без «район», «поселение», «ё» и знаков —
тот же, что строит экран (`frontend/src/lib/districts.ts`).

Запуск (нужны osmium и shapely):

    uv run --with shapely python tools/geo/moscow_districts.py
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from shapely.geometry import mapping, shape
from shapely.ops import polylabel, unary_union

ROOT = Path(__file__).resolve().parents[2]
PBF = Path.home() / ".bee-ltzp" / "osrm" / "moscow.osm.pbf"
WORK = Path.home() / ".bee-ltzp" / "geo"
OUT = ROOT / "frontend" / "public" / "geo" / "moscow-districts.geojson"

SIMPLIFY_DEG = 0.0003
DIGITS = 5
# Подмосковные города задания: радиус застройки от центра города, км.
TOWNS = {"Кашира": 5, "Ступино": 6, "Домодедово": 7}


def key(name: str) -> str:
    """Ключ сопоставления: «район Бирюлёво Восточное» и «Бирюлево Восточное» — одно."""
    text = name.lower().replace("ё", "е")
    text = re.sub(r"\b(район|поселение|городской округ|gpon)\b", " ", text)
    return re.sub(r"[^a-zа-я0-9]", "", text)


def title(name: str) -> str:
    """«район Текстильщики» → «Текстильщики», «Таганский район» → «Таганский»."""
    return re.sub(r"^район\s+|\s+район$", "", name).strip()


def export(tags: list[str], name: str, extra: list[str] | None = None) -> list[dict]:
    WORK.mkdir(parents=True, exist_ok=True)
    pbf, seq = WORK / f"{name}.osm.pbf", WORK / f"{name}.geojsonseq"
    if not seq.exists():
        subprocess.run(["osmium", "tags-filter", "-O", "-o", str(pbf), str(PBF), *tags], check=True)
        subprocess.run(["osmium", "export", "-O", "-f", "geojsonseq", "-o", str(seq), *(extra or []), str(pbf)], check=True)
    with seq.open(encoding="utf-8") as handle:
        return [json.loads(line.strip("\x1e")) for line in handle]


def rounded(geom):
    def walk(coords):
        if isinstance(coords[0], (int, float)):
            return [round(coords[0], DIGITS), round(coords[1], DIGITS)]
        return [walk(c) for c in coords]

    out = mapping(geom)
    return {"type": out["type"], "coordinates": walk(out["coordinates"])}


def feature(name: str, geom, kind: str) -> dict:
    geom = geom.buffer(0).simplify(SIMPLIFY_DEG, preserve_topology=True)
    largest = max(getattr(geom, "geoms", [geom]), key=lambda g: g.area)
    point = polylabel(largest, tolerance=0.0005)
    return {
        "type": "Feature",
        "properties": {"name": name, "key": key(name), "kind": kind,
                       "lx": round(point.x, DIGITS), "ly": round(point.y, DIGITS)},
        "geometry": rounded(geom),
    }


def km_deg(km: float, lat: float) -> tuple[float, float]:
    import math
    return km / 111.2, km / (111.2 * math.cos(math.radians(lat)))


def main() -> None:
    admin = export(["r/boundary=administrative", "n/place=city,town"], "admin")
    polys = [f for f in admin if f["geometry"]["type"] in ("Polygon", "MultiPolygon")]
    okrugs = unary_union([shape(f["geometry"]).buffer(0) for f in polys if f["properties"].get("admin_level") == "5"])
    out = []
    for f in polys:
        props = f["properties"]
        if props.get("admin_level") != "8" or not props.get("name"):
            continue
        geom = shape(f["geometry"]).buffer(0)
        if okrugs.contains(geom.representative_point()):
            out.append(feature(title(props["name"]), geom, "district"))

    centres = {f["properties"]["name"]: f["geometry"]["coordinates"] for f in admin
               if f["geometry"]["type"] == "Point" and f["properties"].get("name") in TOWNS}
    living = [shape(f["geometry"]) for f in export(["wr/landuse=residential"], "residential", ["--geometry-types=polygon"])]
    for town, radius in TOWNS.items():
        lon, lat = centres[town]
        dlat, dlon = km_deg(radius, lat)
        near = [g.buffer(0) for g in living if abs(g.centroid.y - lat) < dlat and abs(g.centroid.x - lon) < dlon]
        # Кварталы сливаются в один контур: раздуть на ~450 м и сжать обратно;
        # отдельные посёлки вокруг — мельче пятой части города — отбрасываются.
        body = unary_union(near).buffer(0.006).buffer(-0.005)
        parts = sorted(getattr(body, "geoms", [body]), key=lambda g: g.area, reverse=True)
        body = unary_union([g for g in parts if g.area >= parts[0].area * 0.2])
        out.append(feature(town, body, "town"))

    out.sort(key=lambda f: f["properties"]["name"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"type": "FeatureCollection", "features": out}, ensure_ascii=False, separators=(",", ":")) + "\n",
                   encoding="utf-8")
    print(f"{OUT}: {len(out)} контуров, {OUT.stat().st_size // 1024} КБ")


if __name__ == "__main__":
    main()
