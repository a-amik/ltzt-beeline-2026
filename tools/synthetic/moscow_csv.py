"""Синтетический день по Москве: CSV в формате заказчика для загрузки с экрана.

Районы — те же, что в задании: три участка («Восток», «Юго-Восток»,
«Юго-Центр»), 31 район и три города области. Адреса — настоящие дома
из выгрузки OpenStreetMap (`~/.bee-ltzp/osrm/moscow.osm.pbf`), попавшие
в границу своего района: дорога до них считается той же моделью, что
и у регионов заказчика. Типы заявок, окна и статусы разыгрываются по долям,
снятым с шести файлов задания; сами строки задания в файл не попадают.

Файл устроен как «Контрольное распределение»: у заявки есть «Бригада»
и «Статус BK». Поэтому после загрузки у набора есть бригады с домами
(старт «из дома» и «гибрид» работают) и факт, с которым план сравнивается
на экране «Сравнение». Бригада в факте — ближайшая к заявке внутри своего
участка, с потолком заявок на бригаду, но без учёта окон и дороги: так
раздаёт диспетчер «по районам», и выигрышу плана есть откуда взяться.
Адреса из файлов задания в синтетику не берутся.

Координаты каждого адреса дописываются в кэш геокодера `data/geocode.json`:
загрузка файла не ходит в сеть и не зависит от Nominatim.

Запуск из `backend/`:

    uv run python ../tools/synthetic/moscow_csv.py [--requests 210] [--seed 17]

Пишет `data/samples/moskva-sintetika.csv`.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from bee_routing.geocode import Geocoder  # noqa: E402
from bee_routing.prepare import normalize_address  # noqa: E402

PBF = Path.home() / ".bee-ltzp" / "osrm" / "moscow.osm.pbf"
WORK = Path.home() / ".bee-ltzp" / "synthetic"
OUT = ROOT / "data" / "samples" / "moskva-sintetika.csv"

OFFICE = "г.Москва проезд Симферопольский, д.7"

# Район задания → участок, граница в OSM и вес (сколько заявок района в задании).
DISTRICTS: dict[str, tuple[str, str, int]] = {
    "Таганский": ("vostok", "Таганский район", 12),
    "Текстильщики": ("vostok", "район Текстильщики", 10),
    "Кузьминки": ("vostok", "район Кузьминки", 9),
    "Рязанский": ("vostok", "Рязанский район", 8),
    "Нижегородский": ("vostok", "Нижегородский район", 8),
    "Выхино": ("vostok", "район Выхино-Жулебино", 7),
    "Лефортово": ("vostok", "район Лефортово", 6),
    "Басманный": ("vostok", "Басманный район", 4),
    "Южнопортовый": ("vostok", "Южнопортовый район", 2),
    "Кашира": ("yugo-vostok", "город:Кашира", 16),
    "Домодедово": ("yugo-vostok", "город:Домодедово", 12),
    "Царицыно": ("yugo-vostok", "район Царицыно", 10),
    "Зябликово": ("yugo-vostok", "район Зябликово", 8),
    "Бирюлево Восточное": ("yugo-vostok", "район Бирюлёво Восточное", 8),
    "Орехово Борисово Северное": ("yugo-vostok", "район Орехово-Борисово Северное", 7),
    "Орехово Борисово Южное": ("yugo-vostok", "Орехово-Борисово Южное", 6),
    "Братеево": ("yugo-vostok", "район Братеево", 6),
    "Бирюлево Западное": ("yugo-vostok", "район Бирюлёво Западное", 5),
    "Ступино": ("yugo-vostok", "город:Ступино", 4),
    "Москворечье - Сабурово": ("yugo-vostok", "район Москворечье-Сабурово", 1),
    "Академический": ("yugocentr", "Академический район", 12),
    "Нагатинский Затон": ("yugocentr", "район Нагатинский Затон", 9),
    "Даниловский": ("yugocentr", "Даниловский район", 8),
    "Зюзино": ("yugocentr", "район Зюзино", 8),
    "Хамовники": ("yugocentr", "район Хамовники", 4),
    "Котловка": ("yugocentr", "район Котловка", 3),
    "Нагатино - Садовники": ("yugocentr", "район Нагатино-Садовники", 3),
    "Замоскворечье": ("yugocentr", "район Замоскворечье", 3),
    "Нагорный": ("yugocentr", "Нагорный район", 3),
    "Донской": ("yugocentr", "Донской район", 1),
    "Гагаринский": ("yugocentr", "Гагаринский район", 1),
}

# Город области: городской округ в OSM и радиус от центра города, км.
TOWNS = {"Кашира": ("городской округ Кашира", 6), "Домодедово": ("городской округ Домодедово", 7),
         "Ступино": ("городской округ Ступино", 6)}

# Бригад на участок и их имена (вымышленные).
CREWS = {
    "vostok": ["Орлов", "Воронин", "Лебедев", "Новиков", "Морозов", "Волков", "Соловьёв", "Зайцев",
               "Павлов", "Семёнов"],
    "yugo-vostok": ["Голубев", "Виноградов", "Богданов", "Воробьёв", "Фёдоров", "Михайлов", "Беляев",
                    "Тарасов", "Белов", "Комаров", "Киселёв"],
    "yugocentr": ["Ковалёв", "Ильин", "Гусев", "Титов", "Кудрявцев", "Баранов", "Куликов", "Сорокин",
                  "Жуков"],
}

# Доли пар «Тип BK / Тип HD» — сумма по трём файлам заявок задания.
TYPES: list[tuple[str, str, int]] = [
    ("Подключение", "Конвергенция абонента", 75),
    ("Локальная заявка", "Нет линка", 31),
    ("Подключение", "Заказ подключения/Дозаказ оборудования", 11),
    ("Глобальная проблема", "Авария", 15),
    ("Подключение", "Заявка на подключение", 9),
    ("Дозаказ", "Дозаказ оборудования", 7),
    ("Локальная заявка", "Переключение на Гбит/с", 7),
    ("Локальная заявка", "Работа с кабелем", 7),
    ("Глобальная проблема", "Информация", 5),
    ("Локальная заявка", "IP-адрес 169...", 6),
    ("Локальная заявка", "Разрывы", 4),
    ("Локальная заявка", "Низкая скорость", 4),
    ("Локальная заявка", "Рост ошибок на порту", 4),
    ("Локальная заявка", "Роутер. Замена техническим специалистом", 2),
    ("Локальная заявка", "ТВ. Замена приставки техником", 2),
    ("Локальная заявка", "TVE/ENT. Замена приставки техником", 2),
]

# Окна по типу BK — доли из контрольных файлов задания.
WINDOWS: dict[str, list[tuple[str, str, int]]] = {
    "Подключение": [("10:00", "12:00", 24), ("12:00", "14:00", 28), ("14:00", "16:00", 13),
                    ("16:00", "18:00", 14), ("18:00", "20:00", 10), ("20:00", "22:00", 6)],
    "Локальная заявка": [("10:00", "12:00", 14), ("12:00", "14:00", 15), ("14:00", "16:00", 11),
                         ("16:00", "18:00", 11), ("18:00", "20:00", 17), ("20:00", "22:00", 9)],
    "Дозаказ": [("10:00", "12:00", 2), ("14:00", "16:00", 2), ("18:00", "20:00", 4), ("20:00", "22:00", 4)],
    "Глобальная проблема": [("0:01", "23:59", 11), ("10:00", "12:00", 2), ("14:00", "16:00", 2),
                            ("16:00", "18:00", 3), ("20:00", "22:00", 3)],
}

# Статус в факте по типу BK — доли из контрольных файлов задания.
STATUSES: dict[str, list[tuple[str, int]]] = {
    "Подключение": [("Выполнена", 50), ("Отменена", 18), ("Отправлена", 14), ("В работе", 5),
                    ("Просрочена", 5), ("В пути", 2), ("Не отправлена", 1)],
    "Локальная заявка": [("Выполнена", 49), ("Отправлена", 13), ("В работе", 6), ("Просрочена", 4),
                         ("В пути", 3), ("Отменена", 2)],
    "Дозаказ": [("Отправлена", 5), ("Выполнена", 4), ("Не отправлена", 1), ("Просрочена", 1), ("Отменена", 1)],
    "Глобальная проблема": [("Отправлена", 11), ("Выполнена", 9), ("В пути", 1)],
}

# Тип улицы OSM → сокращение, как в выгрузке заказчика.
STREET_ABBR = {"улица": "ул.", "проспект": "пр-кт.", "бульвар": "б-р.", "набережная": "наб.",
               "переулок": "пер.", "проезд": "проезд.", "шоссе": "ш.", "площадь": "пл.", "тупик": "туп."}

# Жилые дома: к ним и ездят бригады ШПД.
LIVING = {"apartments", "residential", "house", "detached", "dormitory", "terrace"}

HOUSE = re.compile(r"^(\d{1,3}[А-Я]?)(?:\s*к\s*(\d{1,2}))?(?:\s*с\s*(\d{1,2}))?$")


def extract() -> tuple[Path, Path]:
    """Дома с номером и административные границы из выгрузки OSM; один раз, дальше — с диска."""
    WORK.mkdir(parents=True, exist_ok=True)
    addr, admin = WORK / "addr.geojsonseq", WORK / "admin.geojsonseq"
    if not addr.exists():
        pbf = WORK / "addr.osm.pbf"
        subprocess.run(["osmium", "tags-filter", "-O", "-o", str(pbf), str(PBF), "nwr/addr:housenumber"], check=True)
        subprocess.run(["osmium", "export", "-O", "-f", "geojsonseq", "-o", str(addr), str(pbf)], check=True)
    if not admin.exists():
        pbf = WORK / "admin.osm.pbf"
        subprocess.run(["osmium", "tags-filter", "-O", "-o", str(pbf), str(PBF),
                        "r/boundary=administrative", "n/place=city,town"], check=True)
        subprocess.run(["osmium", "export", "-O", "-f", "geojsonseq", "-o", str(admin), str(pbf)], check=True)
    return addr, admin


def features(path: Path):
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            yield json.loads(line.strip("\x1e"))


def rings(geometry: dict) -> list[list[list[float]]]:
    """Внешние контуры многоугольника (дыры в районах не встречаются)."""
    if geometry["type"] == "Polygon":
        return [geometry["coordinates"][0]]
    return [poly[0] for poly in geometry["coordinates"]]


def inside(lon: float, lat: float, polys: list[list[list[float]]]) -> bool:
    hit = False
    for ring in polys:
        j = len(ring) - 1
        for i in range(len(ring)):
            xi, yi = ring[i]
            xj, yj = ring[j]
            if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
                hit = not hit
            j = i
    return hit


def km(a: tuple[float, float], b: tuple[float, float]) -> float:
    dlat = (a[0] - b[0]) * 111.2
    dlon = (a[1] - b[1]) * 111.2 * math.cos(math.radians(a[0]))
    return math.hypot(dlat, dlon)


def centroid(geometry: dict) -> tuple[float, float]:
    if geometry["type"] == "Point":
        lon, lat = geometry["coordinates"]
        return lat, lon
    ring = rings(geometry)[0] if geometry["type"] in ("Polygon", "MultiPolygon") else geometry["coordinates"]
    return sum(p[1] for p in ring) / len(ring), sum(p[0] for p in ring) / len(ring)


def street_in_task_style(street: str) -> str | None:
    """«Керченская улица» → «ул.Керченская»; тип, которого нет в словаре, — мимо."""
    words = street.split()
    for pos, word in enumerate(words):
        if word.lower() in STREET_ABBR and len(words) > 1:
            rest = " ".join(words[:pos] + words[pos + 1:])
            return STREET_ABBR[word.lower()] + rest
    return None


def house_in_task_style(number: str) -> str | None:
    """«10к2» → «10 к 2», «4с1» → «4 с 1»; дроби, литеры и диапазоны — мимо."""
    match = HOUSE.match(number.strip())
    if not match:
        return None
    base, corp, build = match.groups()
    return base + (f" к {corp}" if corp else "") + (f" с {build}" if build else "")


def pool(addr: Path, admin: Path) -> dict[str, list[dict]]:
    """Адреса-кандидаты по районам задания."""
    by_name: dict[str, list] = {}
    towns: dict[str, tuple[float, float]] = {}
    for feat in features(admin):
        props, geom = feat["properties"], feat["geometry"]
        if geom["type"] in ("Polygon", "MultiPolygon"):
            by_name[props.get("name", "")] = rings(geom)
        elif props.get("place") in ("city", "town") and props.get("name") in TOWNS:
            lon, lat = geom["coordinates"]
            towns[props["name"]] = (lat, lon)
    areas = {}
    for district, (_sector, osm, _w) in DISTRICTS.items():
        key = TOWNS[district][0] if osm.startswith("город:") else osm
        polys = by_name[key]
        xs = [p[0] for r in polys for p in r]
        ys = [p[1] for r in polys for p in r]
        areas[district] = (polys, (min(xs), max(xs), min(ys), max(ys)))

    out: dict[str, list[dict]] = defaultdict(list)
    for feat in features(addr):
        props = feat["properties"]
        if props.get("building") not in LIVING:
            continue
        street = street_in_task_style(props.get("addr:street", ""))
        house = house_in_task_style(props.get("addr:housenumber", ""))
        if not street or not house:
            continue
        lat, lon = centroid(feat["geometry"])
        city = props.get("addr:city", "")
        for district, (polys, (x0, x1, y0, y1)) in areas.items():
            if not (x0 <= lon <= x1 and y0 <= lat <= y1):
                continue
            if district in TOWNS:
                if city not in ("", district) or km((lat, lon), towns[district]) > TOWNS[district][1]:
                    continue
                address = f"{district}, {street}, д. {house}"
            else:
                if city not in ("", "Москва"):
                    continue
                address = f"Город Москва, {street}, д. {house}"
            if inside(lon, lat, polys):
                out[district].append({"address": address, "lat": round(lat, 6), "lon": round(lon, 6)})
                break
    return out


def pick(rng: random.Random, weighted: list[tuple]) -> tuple:
    return rng.choices(weighted, weights=[w[-1] for w in weighted])[0]


def balanced(points: list[tuple[float, float]], k: int, rng: random.Random) -> list[int]:
    """Бригада заявке — ближайший центр, но не больше потолка в день: так раздаёт диспетчер."""
    centres = rng.sample(points, k)
    cap = -(-len(points) // k) + 1
    label = [0] * len(points)
    for _ in range(20):
        load = [0] * k
        pairs = sorted((km(p, centres[c]), i, c) for i, p in enumerate(points) for c in range(k))
        done: set[int] = set()
        for _dist, i, c in pairs:
            if i in done or load[c] >= cap:
                continue
            label[i] = c
            load[c] += 1
            done.add(i)
        for c in range(k):
            own = [p for p, lab in zip(points, label) if lab == c]
            if own:
                centres[c] = (sum(p[0] for p in own) / len(own), sum(p[1] for p in own) / len(own))
    return label


def build(total: int, seed: int, known: set[str]) -> tuple[list[dict], dict[str, dict]]:
    rng = random.Random(seed)
    candidates = pool(*extract())
    # Адреса, уже известные кэшу, — из файлов задания: их в синтетику не берут.
    for district, spots in candidates.items():
        candidates[district] = [s for s in spots if normalize_address(s["address"], district) not in known]
    empty = [d for d in DISTRICTS if len(candidates.get(d, [])) < 5]
    if empty:
        raise SystemExit("Мало домов в районах: " + ", ".join(empty))

    # Каждый район получает хотя бы две заявки, остальное — по весу из задания.
    counts = Counter({d: 2 for d in DISTRICTS})
    rest = total - sum(counts.values())
    names = list(DISTRICTS)
    for d in rng.choices(names, weights=[DISTRICTS[n][2] for n in names], k=rest):
        counts[d] += 1

    rows: list[dict] = []
    coords: dict[str, dict] = {}
    numbers = rng.sample(range(305_800_000, 305_999_999), total)
    for district in names:
        for spot in rng.sample(candidates[district], counts[district]):
            type_bk, type_hd, _ = pick(rng, TYPES)
            start, end, _ = pick(rng, WINDOWS[type_bk])
            status, _ = pick(rng, STATUSES[type_bk])
            address = spot["address"]
            if type_bk in ("Подключение", "Дозаказ"):
                address += f", кв. {rng.randint(1, 280)}"
            rows.append({
                "Заявка": str(numbers[len(rows)]),
                "Тип заявки BK": type_bk,
                "Статус BK": status,
                "Тип заявки HD": type_hd,
                "Начало": f"17.08.2026 {start}",
                "Окончание": f"17.08.2026 {end}",
                "Район": district,
                "Адрес": address,
                "Бригада": "",
                "Подключение": "FMC" if type_hd == "Конвергенция абонента" else "",
                "Гигабитное подключение": "Да" if type_hd == "Переключение на Гбит/с" else "Нет",
                "_sector": DISTRICTS[district][0],
                "_point": (spot["lat"], spot["lon"]),
            })
            coords[normalize_address(address, district)] = {"lat": spot["lat"], "lon": spot["lon"]}

    # Факт: бригада — кластер заявок своего участка; неотправленные — без бригады.
    for sector, crews in CREWS.items():
        own = [r for r in rows if r["_sector"] == sector]
        labels = balanced([r["_point"] for r in own], len(crews), rng)
        for row, lab in zip(own, labels):
            if row["Статус BK"] != "Не отправлена":
                row["Бригада"] = f"Бригада {crews[lab]}"
    rng.shuffle(rows)
    return rows, coords


COLUMNS = ["Заявка", "Тип заявки BK", "Статус BK", "Тип заявки HD", "Начало", "Окончание", "Район", "Адрес",
           "Бригада", "Подключение", "Гигабитное подключение"]


def write(rows: list[dict], path: Path) -> None:
    lines = [";".join(COLUMNS)]
    lines += [";".join(row[c] for c in COLUMNS) for row in rows]
    lines.append(";" * (len(COLUMNS) - 1))
    lines.append("Адрес офиса;" + OFFICE + ";" * (len(COLUMNS) - 2))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("﻿" + "\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--requests", type=int, default=210)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    geo = Geocoder(offline=True)
    rows, coords = build(args.requests, args.seed, set(geo.cache))
    write(rows, args.out)
    geo.cache.update(coords)
    geo.save()
    print(f"{args.out}: {len(rows)} заявок, {len({r['Бригада'] for r in rows if r['Бригада']})} бригад, "
          f"{len(coords)} адресов в кэше геокодера")


if __name__ == "__main__":
    main()
