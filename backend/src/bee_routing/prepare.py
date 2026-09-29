"""Подготовка датасетов: сырые CSV → `app/data/datasets/<регион>.json` по контракту.

Что здесь происходит:

1. адреса приводятся к единому виду «Москва, 1-й Советский проезд, 9А»
   и «Московская область, Домодедово, Зелёная улица, 85»;
2. заявка синтетического файла сшивается с контрольной строкой по
   адресу, окну и типу — номера у них разные, и наружу идёт номер
   синтетического файла;
3. из колонки «Бригада» контрольного файла собираются бригады: навык —
   по типам заявок, которые бригада делала в тот день;
4. адреса геокодируются (кэш на диске), и всё складывается в JSON.

Запуск: `uv run python -m bee_routing.prepare`.
"""

from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from .geocode import APP_DIR, DATA_DIR, Geocoder, load_assumptions

RAW_DIR = DATA_DIR / "raw"
DATASETS_DIR = DATA_DIR / "datasets"

# Типы улиц: и сокращение, и полное слово ведут к одному каноническому виду.
STREET_TYPES = {
    "ул": "улица", "улица": "улица",
    "пр-кт": "проспект", "проспект": "проспект", "пр-т": "проспект",
    "б-р": "бульвар", "бульвар": "бульвар",
    "наб": "набережная", "набережная": "набережная",
    "пер": "переулок", "переулок": "переулок",
    "проезд": "проезд", "пр-зд": "проезд", "проездъ": "проезд",
    "ш": "шоссе", "шоссе": "шоссе",
    "пл": "площадь", "площадь": "площадь",
    "туп": "тупик", "тупик": "тупик",
    "аллея": "аллея", "линия": "линия", "тракт": "тракт",
    "кв-л": "квартал", "квартал": "квартал",
}

TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "shch", "ъ": "", "ы": "y", "ь": "", "э": "e",
    "ю": "yu", "я": "ya",
}


def translit(surname: str) -> str:
    """Транслит фамилии в идентификатор: Смоленский → smolensky, Коваль → koval."""
    low = surname.strip().lower()
    for tail, repl in (("ский", "sky"), ("цкий", "tsky"), ("ская", "skaya")):
        if low.endswith(tail):
            low = low[: -len(tail)] + repl
            break
    return "".join(TRANSLIT.get(ch, ch) for ch in low if ch.isalpha() or ch in "-")


def _fix_house(chunk: str) -> str:
    """«128 к 5» → «128к5», «24/30 стр. 1» → «24/30с1», «83с 4» → «83с4»."""
    house = chunk.strip().strip(",.").strip()
    house = re.sub(r"\s*(?:корп\.?|к)\s*", "к", house)
    house = re.sub(r"\s*(?:стр\.?|с)\s*", "с", house)
    return house.replace(" ", "")


def _fix_street(chunk: str) -> str:
    """«проезд. Советский 1-й» → «1-й Советский проезд», «ул. Восточная» → «Восточная улица»."""
    words = [w for w in re.split(r"[\s,]+", chunk.strip()) if w]
    kind = ""
    rest: list[str] = []
    for word in words:
        key = word.rstrip(".").lower()
        if not kind and key in STREET_TYPES:
            kind = STREET_TYPES[key]
        else:
            rest.append(word)
    name = " ".join(rest).strip(" ,.")
    # Порядковое числительное в хвосте уезжает вперёд: «Советский 1-й» → «1-й Советский».
    tail = re.match(r"^(.*?)\s+(\d+-[а-яё]{1,2})$", name)
    if tail:
        name = f"{tail.group(2)} {tail.group(1)}"
    if not kind:
        return name
    return f"{name} {kind}".strip()


def normalize_address(raw: str, district: str = "") -> str:
    """Привести адрес к единому виду; квартира отбрасывается."""
    text = re.sub(r"\s+", " ", (raw or "").strip())
    text = re.sub(r",?\s*кв\.?\s*[\w\d/-]+\s*$", "", text)
    text = re.sub(r"\.(?=\S)", ". ", text)

    text = re.sub(r"\bобл\.?\s*Московская область\b", "Московская область", text)
    text = re.sub(r"^МО\.?\s*,?\s*", "Московская область, ", text)
    text = re.sub(r"\bг\.?\s*Город\s+Москва\b", "Москва", text)
    text = re.sub(r"\bГород\s+Москва\b", "Москва", text)
    text = re.sub(r"\bг\.?\s*Москва\b", "Москва", text)

    in_moscow = bool(re.search(r"\bМосква\b", text))
    text = re.sub(r"\bМосковская область\b,?\s*", "", text)
    text = re.sub(r"\bМосква\b,?\s*", "", text)

    town = ""
    town_match = re.search(r"\bг\.?\s+([А-ЯЁ][А-Яа-яёЁ\-]+)", text)
    if town_match:
        town = town_match.group(1)
        text = text[: town_match.start()] + text[town_match.end() :]
    settlement = ""
    stl = re.search(r"\b(?:пгт|п|дп|с|д)\.\s*([А-ЯЁ][А-Яа-яёЁ\d\-]+)", text)
    if stl:
        settlement = stl.group(1)
        text = text[: stl.start()] + text[stl.end() :]

    house = ""
    hm = re.search(r"(?:^|[,\s])д\.?\s+(.+)$", text)
    if hm:
        house = _fix_house(hm.group(1))
        text = text[: hm.start()]
    text = text.strip(" ,")

    if not town and not in_moscow:
        # Город стоит первым куском: «Домодедово, проезд. Советский 1-й».
        head, _, tail = text.partition(",")
        if tail.strip():
            town, text = head.strip(), tail.strip()

    street = _fix_street(text)
    parts = ["Москва"] if in_moscow else ["Московская область"]
    for extra in (town, settlement, street, house):
        if extra:
            parts.append(extra)
    if len(parts) == 1 and district:
        parts.append(re.sub(r"^GPON\s+", "", district).strip())
    return ", ".join(parts)


def hhmm(raw: str) -> str:
    """«17.08.2026 20:00» → «20:00»; «17.08.2026 0:01» → «00:01»."""
    clock = raw.strip().split(" ")[-1]
    hours, _, minutes = clock.partition(":")
    return f"{int(hours):02d}:{int(minutes or 0):02d}"


def read_rows(path: Path) -> tuple[list[dict], str]:
    """Прочитать `;`-CSV; вернуть строки и адрес офиса из последней строки."""
    rows: list[dict] = []
    office = ""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle, delimiter=";"):
            first = (row.get("Заявка") or "").strip()
            if first.lower().startswith("адрес офиса"):
                office = (row.get("Тип заявки BK") or "").strip()
                continue
            if not first or not (row.get("Адрес") or "").strip():
                continue
            rows.append({(k or "").strip(): (v or "").strip() for k, v in row.items() if k})
    return rows, office


def match_key(row: dict) -> tuple:
    """Ключ сшивки синтетической заявки с контрольной: адрес, окно, оба типа."""
    return (
        normalize_address(row["Адрес"], row.get("Район", "")),
        hhmm(row["Начало"]),
        hhmm(row["Окончание"]),
        row.get("Тип заявки HD", ""),
        row.get("Тип заявки BK", ""),
    )


def dedupe_control(rows: list[dict]) -> list[dict]:
    """Один номер заявки — одна строка: отменённый дубль уступает выполненному."""
    best: dict[str, dict] = {}
    for row in rows:
        num = row["Заявка"]
        old = best.get(num)
        if old is None or (old.get("Статус BK") == "Отменена" != row.get("Статус BK")):
            best[num] = row
    return [row for row in rows if best.get(row["Заявка"]) is row]


def window_for(row: dict, conf: dict) -> tuple[str, str]:
    """Окно заявки как в файле заказчика.

    «Весь день» (0:01–23:59) остаётся суточным: раньше и позже смены бригада
    всё равно не выедет, и это держит смена, а не подменённое окно
    (эксперты 22.09.2026: окна фиксированы). Старое поведение — ключ
    `all_day_window.to_workday` в допущениях.
    """
    start, end = hhmm(row["Начало"]), hhmm(row["Окончание"])
    whole = conf["all_day_window"]
    if whole.get("to_workday") and (start, end) == (hhmm(whole["start"]), hhmm(whole["end"])):
        return conf["workday"]["start"], conf["workday"]["end"]
    return start, end


def skill_for(row: dict, conf: dict) -> str:
    """Навык заявки: по типу HD, если он уточняет тип BK, иначе по типу BK.

    «Глобальная проблема / Информация» — не авария (письменный ответ
    Билайна, п. 15): навык локальной работы, без права встать первой.
    """
    by_hd = {k: v for k, v in conf.get("skill_by_type_hd", {}).items() if not k.startswith("_")}
    type_hd = row.get("Тип заявки HD", "")
    if type_hd in by_hd:
        return by_hd[type_hd]
    return conf["skill_by_type_bk"].get(row.get("Тип заявки BK", ""), conf["default_skill"])


def build_request(row: dict, conf: dict, geo: Geocoder) -> dict:
    """Собрать заявку по контракту из строки синтетического файла."""
    address = normalize_address(row["Адрес"], row.get("Район", ""))
    lat, lon, quality = geo.locate(address, row.get("Район", ""))
    type_hd = row.get("Тип заявки HD", "")
    start, end = window_for(row, conf)
    return {
        "id": row["Заявка"],
        "type_bk": row.get("Тип заявки BK", ""),
        "type_hd": type_hd,
        "address": address,
        "district": row.get("Район", ""),
        "lat": round(lat, 6),
        "lon": round(lon, 6),
        "geo_quality": quality,
        "duration_min": conf["duration_by_type_bk"].get(
            row.get("Тип заявки BK", ""), conf["default_duration_min"]
        ),
        "window_start": start,
        "window_end": end,
        "priority": "normal",
        "skill": skill_for(row, conf),
        "transport": None,
    }


def build_engineers(control: list[dict], conf: dict, region: dict, office: dict) -> list[dict]:
    """Бригады региона: навыки по сделанному за день, транспорт — по допущениям."""
    order: list[str] = []
    skills: dict[str, set[str]] = defaultdict(set)
    load: Counter = Counter()
    for row in control:
        raw = row.get("Бригада", "").strip()
        if not raw:
            continue
        name = re.sub(r"^Бригада\s+", "", raw).strip()
        ident = translit(name.split()[0])
        if ident not in order:
            order.append(ident)
        skills[ident].add(skill_for(row, conf))
        load[ident] += 1
        skills.setdefault(ident, set())
        row["_engineer_id"] = ident
        row["_engineer_name"] = name

    names = {row["_engineer_id"]: row["_engineer_name"] for row in control if row.get("_engineer_id")}
    top = [ident for ident, _ in load.most_common(conf["engineers"]["full_skill_engineers_per_region"])]
    all_skills = sorted({"local", "connect", "emergency"})

    engineers = []
    for position, ident in enumerate(order):
        own = sorted(skills[ident]) or list(conf["engineers"]["default_skills"])
        if ident in top:
            own = all_skills
        transports = transport_mix_for(position, len(order), conf["engineers"]["transport_mix"])
        engineers.append({
            "id": ident,
            "name": names[ident],
            "start": {"lat": office["lat"], "lon": office["lon"]},
            "shift_start": conf["engineers"]["shift_start"],
            "shift_end": conf["engineers"]["shift_end"],
            "skills": own,
            "transport": transports[0],
            "transports": transports,
            "extra_load": extra_load_for(position, len(order), conf["engineers"]),
            "extra_limit_min": conf["engineers"]["extra_limit_min"],
        })
    return engineers


def extra_load_for(position: int, total: int, conf: dict) -> bool:
    """Готовность к нагрузке сверх нормы: доля из допущений, раздача по позиции."""
    share = float(conf.get("extra_load_share", 1.0))
    return (position + 0.5) / max(total, 1) < share


def add_homes(engineers: list[dict], control: list[dict], by_control: dict[str, str],
              requests: list[dict], office: dict) -> None:
    """Дом бригады — центр её заявок за день; без заявок — офис."""
    coords = {req["id"]: (req["lat"], req["lon"]) for req in requests}
    points: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for row in control:
        plain_id = by_control.get(row["Заявка"])
        ident = row.get("_engineer_id")
        if plain_id in coords and ident:
            points[ident].append(coords[plain_id])
    for eng in engineers:
        own = points.get(eng["id"])
        if own:
            lat = sum(p[0] for p in own) / len(own)
            lon = sum(p[1] for p in own) / len(own)
        else:
            lat, lon = office["lat"], office["lon"]
        eng["home"] = {"lat": round(lat, 6), "lon": round(lon, 6)}


def build_control(control: list[dict], by_control: dict[str, str]) -> list[dict]:
    """Контрольное распределение в терминах датасета: заявка → бригада, статус."""
    out = []
    for row in control:
        plain_id = by_control.get(row["Заявка"])
        ident = row.get("_engineer_id")
        if plain_id and ident:
            out.append({"request_id": plain_id, "engineer_id": ident, "status": row.get("Статус BK", "")})
    return out


def transport_mix_for(position: int, total: int, mix: list[dict]) -> list[str]:
    """Набор транспорта бригаде по её месту в списке: доли из допущений, без случайности.

    Бригады раскладываются по долям равномерно: при 12 бригадах и долях
    0,6 / 0,25 / 0,15 наборов выйдет 7, 3 и 2. Порядок бригад — порядок
    появления в контрольном файле, поэтому раздача повторяется от сборки
    к сборке.
    """
    share_before = 0.0
    point = (position + 0.5) / max(total, 1)
    for entry in mix:
        share_before += float(entry["share"])
        if point < share_before:
            return list(entry["transports"])
    return list(mix[-1]["transports"])


def build_events(
    control: list[dict], by_control: dict[str, str], conf: dict, geo: Geocoder, load: Counter
) -> list[dict]:
    """Три сценария на регион: срочная авария, отмена, выбывшая бригада."""
    events: list[dict] = []
    spec = conf["events"]["urgent"]
    source = next((r for r in control if r.get("Тип заявки HD") == "Авария"), None)
    source = source or next((r for r in control if r.get("Тип заявки BK") == "Локальная заявка"), None)
    if source:
        address = normalize_address(source["Адрес"], source.get("Район", ""))
        lat, lon, quality = geo.locate(address, source.get("Район", ""))
        events.append({
            "id": "e1", "type": "urgent", "time": spec["time"],
            "request": {
                "id": spec["id"], "type_bk": spec["type_bk"], "type_hd": spec["type_hd"],
                "address": address, "district": source.get("Район", ""),
                "lat": round(lat, 6), "lon": round(lon, 6), "geo_quality": quality,
                "duration_min": spec["duration_min"],
                "window_start": spec["window_start"], "window_end": spec["window_end"],
                "priority": spec["priority"], "skill": spec["skill"], "transport": None,
            },
        })
    cancelled = next(
        (r for r in control if r.get("Статус BK") == "Отменена" and r["Заявка"] in by_control), None
    )
    if cancelled:
        events.append({
            "id": "e2", "type": "cancel",
            "time": conf["events"]["cancel"]["time"],
            "request_id": by_control[cancelled["Заявка"]],
        })
    if load:
        events.append({
            "id": "e3", "type": "engineer_off",
            "time": conf["events"]["engineer_off"]["time"],
            "engineer_id": load.most_common(1)[0][0],
        })
    return events


DAY_FILE = re.compile(r"^(?P<region>.+)-(?P<day>\d{4}-\d{2}-\d{2})-zayavki\.csv$")
MONTHS = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября",
          "октября", "ноября", "декабря")


def extra_days(conf: dict, raw_dir: Path | None = None) -> list[tuple[str, str]]:
    """Дополнительные дни регионов: файлы `<регион>-<ГГГГ-ММ-ДД>-zayavki.csv` в `data/raw/`.

    Билайн обещал ещё 2—3 рабочих дня тех же регионов. Файл кладётся
    рядом с первым днём под именем с датой, рядом — `…-kontrol.csv`, если
    контроль дали; подготовка находит их сама, набор получает идентификатор
    `<регион>-<дата>` и встаёт в список наборов экрана.
    """
    found = []
    for path in sorted((raw_dir or RAW_DIR).glob("*-zayavki.csv")):
        match = DAY_FILE.match(path.name)
        if match and match["region"] in conf["regions"]:
            found.append((match["region"], match["day"]))
    return found


def build_dataset(region_id: str, conf: dict, geo: Geocoder, day: str | None = None,
                  raw_dir: Path | None = None) -> dict:
    """Собрать датасет одного региона целиком; `day` — дополнительный день того же региона."""
    region = conf["regions"][region_id]
    raw_dir = raw_dir or RAW_DIR
    stem = f"{region_id}-{day}" if day else region_id
    plain, _office_raw = read_rows(raw_dir / f"{stem}-zayavki.csv")
    control_path = raw_dir / f"{stem}-kontrol.csv"
    control = dedupe_control(read_rows(control_path)[0]) if control_path.exists() else []

    office_address = region["office_address"]
    o_lat, o_lon, _ = geo.locate(office_address, "")
    office = {"address": office_address, "lat": round(o_lat, 6), "lon": round(o_lon, 6)}

    # Сшивка: один ключ может встретиться дважды, поэтому очередь, а не словарь.
    buckets: dict[tuple, list[dict]] = defaultdict(list)
    for row in control:
        buckets[match_key(row)].append(row)
    by_control: dict[str, str] = {}
    unmatched = 0
    for row in plain:
        queue = buckets.get(match_key(row))
        if queue:
            by_control[queue.pop(0)["Заявка"]] = row["Заявка"]
        else:
            unmatched += 1

    requests = [build_request(row, conf, geo) for row in plain]
    if control:
        engineers = build_engineers(control, conf, region, office)
        add_homes(engineers, control, by_control, requests, office)
        # Подпись дома — ближайший дом с номером; ответы геокодера в кэше, повтор в сеть не ходит.
        from .homes import Reverse, attach

        attach(engineers, Reverse(offline=geo.offline))
        load = Counter(row["_engineer_id"] for row in control if row.get("_engineer_id"))
        events = build_events(control, by_control, conf, geo, load)
    else:
        # День без контрольного файла: бригады — из первого дня региона, события не разыгрываются.
        base = json.loads((DATASETS_DIR / f"{region_id}.json").read_text(encoding="utf-8"))
        engineers, events = base["engineers"], []
    control_rows = build_control(control, by_control)

    print(
        f"  {stem}: заявок {len(requests)}, бригад {len(engineers)},"
        f" сшито {len(by_control)}, без пары {unmatched}"
    )
    from .enrich import apply as enrich_apply

    return enrich_apply({
        "id": stem, "name": region["name"] + (f", {int(day[8:])} {MONTHS[int(day[5:7]) - 1]}" if day else ""),
        "date": day or conf["date"], "office": office,
        "requests": requests, "engineers": engineers, "events": events,
        "control": control_rows,
    }, conf)


def main(argv: list[str] | None = None) -> int:
    """Собрать все три датасета и положить их в app/data/datasets."""
    conf = load_assumptions()
    geo = Geocoder(conf, offline="--offline" in (argv or sys.argv[1:]))
    DATASETS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Подготовка данных ({APP_DIR}):")
    try:
        jobs = [(region_id, None) for region_id in conf["regions"]] + extra_days(conf)
        for region_id, day in jobs:
            data = build_dataset(region_id, conf, geo, day)
            path = DATASETS_DIR / f"{data['id']}.json"
            path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    finally:
        geo.save()
    print(f"Запросов к Nominatim: {geo.network_calls}")
    from .geocode import summary

    print(summary(DATASETS_DIR))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
