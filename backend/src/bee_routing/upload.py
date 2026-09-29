"""Свой набор данных: CSV в формате заказчика или JSON по контракту — с экрана.

Задание, п. 2.1: сервис загружает тестовые данные из CSV или JSON либо
берёт встроенный набор. Встроенных три региона; здесь — четвёртый и любой
следующий, присланный файлом через `POST /datasets/upload`.

Два формата, и оба уже есть в проекте:

1. **CSV заказчика** — тот же `;`-файл, что «Синтетические данные» или
   «Контрольное распределение»: столбцы «Заявка», «Адрес», «Район»,
   «Тип заявки BK», «Тип заявки HD», окно и последняя строка «Адрес офиса».
   Разбирает его тот же `prepare.py`, что собирал регионы заказчика:
   адреса геокодируются Nominatim с кэшем, длительности и навыки —
   по допущениям. Есть столбец «Бригада» — бригады и контроль берутся
   из файла, как у регионов; нет — бригады заводятся синтетически,
   числом из запроса или по одной на шесть заявок.
2. **JSON по контракту** — датасет целиком, как `data/datasets/*.json`:
   офис, заявки, бригады, события. Проверяется моделью `Dataset`.

Матрицы дорог считает OSRM, если он поднят, иначе запасная оценка (прямая
× 1,3) — как у генератора нагрузки; источник записан в матрице и виден
в `GET /datasets`. Загруженное ложится в `data/uploads/` (в git не входит)
и переживает перезапуск сервиса; в списке регионов оно помечено `upload`.

Три вещи, которые нельзя ломать:

1. **Идентификатор — от содержимого.** Тот же файл второй раз — тот же
   регион, а не дубль в списке.
2. **Правила те же, что у регионов заказчика.** Нормативы, навыки, окна,
   устройства и удалённые подучастки считаются теми же функциями; своя
   ветка разбора для загруженного файла означала бы два прототипа.
3. **Ошибка возвращается словами**, а не трассировкой: чего не хватило
   в файле, какой адрес не нашёлся.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from collections import Counter, defaultdict

from pydantic import ValidationError

from . import enrich
from .geocode import Geocoder, load_assumptions
from .loader import UPLOAD_DATASETS_DIR, UPLOAD_MATRICES_DIR, load_dataset, load_matrices
from .models import Dataset
from .prepare import (
    add_homes,
    build_control,
    build_engineers,
    build_request,
    dedupe_control,
    match_key,
    normalize_address,
    transport_mix_for,
)


class UploadError(ValueError):
    """Файл не разобрался; текст — диспетчеру."""


def _slug(text: str) -> str:
    text = re.sub(r"\.(csv|json)$", "", text.strip(), flags=re.IGNORECASE)
    text = re.sub(r"[^a-zA-Z0-9а-яА-ЯёЁ]+", "-", text).strip("-").lower()
    table = str.maketrans("абвгдеёзийклмнопрстуфхыэ", "abvgdeezijklmnoprstufhye")
    text = text.translate(table)
    text = re.sub(r"[^a-z0-9-]+", "", text)
    return text[:24] or "nabor"


def dataset_id_for(filename: str, content: str) -> str:
    """`upload-<имя>-<отпечаток содержимого>`: тот же файл — тот же регион."""
    digest = hashlib.sha1(content.encode("utf-8")).hexdigest()[:6]
    return f"upload-{_slug(filename)}-{digest}"


def _rows(content: str) -> tuple[list[dict], str]:
    """Строки CSV заказчика и адрес офиса; разделитель — `;` или `,`."""
    sample = content[:2000]
    delimiter = ";" if sample.count(";") >= sample.count(",") else ","
    rows: list[dict] = []
    office = ""
    reader = csv.DictReader(io.StringIO(content.lstrip("﻿")), delimiter=delimiter)
    for row in reader:
        first = (row.get("Заявка") or "").strip()
        if first.lower().startswith("адрес офиса"):
            office = (row.get("Тип заявки BK") or "").strip()
            continue
        if not first or not (row.get("Адрес") or "").strip():
            continue
        rows.append({(k or "").strip(): (v or "").strip() for k, v in row.items() if k})
    required = {"Заявка", "Адрес"}
    if not rows:
        raise UploadError("В файле нет ни одной строки с заявкой: нужны столбцы «Заявка» и «Адрес»")
    missing = required - set(rows[0])
    if missing:
        raise UploadError("В файле нет столбцов: " + ", ".join(sorted(missing)))
    return rows, office


def _synthetic_engineers(count: int, office: dict, conf: dict) -> list[dict]:
    """Бригады без файла контроля: три с полным набором навыков, дальше по кругу."""
    eng_conf = conf["engineers"]
    skill_sets = [["local", "connect", "emergency"], ["local", "connect"], ["local", "emergency"], ["local"]]
    out = []
    for i in range(count):
        skills = skill_sets[0] if i < int(eng_conf.get("full_skill_engineers_per_region", 3)) else skill_sets[
            1 + (i % (len(skill_sets) - 1))
        ]
        transports = transport_mix_for(i, count, eng_conf["transport_mix"])
        out.append({
            "id": f"e{i + 1:02d}",
            "name": f"Бригада {i + 1}",
            "start": {"lat": office["lat"], "lon": office["lon"]},
            "shift_start": eng_conf["shift_start"],
            "shift_end": eng_conf["shift_end"],
            "skills": skills,
            "transport": transports[0],
            "transports": transports,
            "extra_load": True,
            "extra_limit_min": eng_conf["extra_limit_min"],
        })
    return out


def from_csv(filename: str, content: str, *, name: str | None = None, engineers: int | None = None,
             conf: dict | None = None, geo: Geocoder | None = None) -> dict:
    """Датасет из CSV заказчика — теми же функциями, что собирали регионы."""
    conf = conf or load_assumptions()
    geo = geo or Geocoder(conf)
    rows, office_address = _rows(content)
    if not office_address:
        raise UploadError("Нет строки «Адрес офиса» в конце файла: без офиса бригадам неоткуда стартовать")
    office_address = normalize_address(office_address)
    try:
        o_lat, o_lon, _ = geo.locate(office_address, "")
    except LookupError as error:
        raise UploadError(str(error)) from error
    office = {"address": office_address, "lat": round(o_lat, 6), "lon": round(o_lon, 6)}
    try:
        requests = [build_request(row, conf, geo) for row in rows]
    except LookupError as error:
        raise UploadError(str(error)) from error
    finally:
        geo.save()
    has_crews = any((row.get("Бригада") or "").strip() for row in rows)
    if has_crews:
        control = dedupe_control([dict(row) for row in rows])
        buckets: dict[tuple, list[dict]] = defaultdict(list)
        for row in control:
            buckets[match_key(row)].append(row)
        by_control = {row["Заявка"]: row["Заявка"] for row in control}
        engineers_list = build_engineers(control, conf, {"name": name or filename}, office)
        add_homes(engineers_list, control, by_control, requests, office)
        control_rows = build_control(control, by_control)
    else:
        count = engineers or max(3, min(15, -(-len(requests) // 6)))
        engineers_list = _synthetic_engineers(count, office, conf)
        control_rows = []
    return {
        "id": dataset_id_for(filename, content),
        "name": name or _title(filename),
        "date": conf["date"],
        "office": office,
        "requests": requests,
        "engineers": engineers_list,
        "events": [],
        "control": control_rows,
    }


def _title(filename: str) -> str:
    return re.sub(r"\.(csv|json)$", "", filename.strip(), flags=re.IGNORECASE) or "Свой набор"


def from_json(filename: str, content: str, *, name: str | None = None) -> dict:
    """Датасет из JSON по контракту; проверка — моделью."""
    try:
        raw = json.loads(content)
    except ValueError as error:
        raise UploadError(f"JSON не читается: {error}") from error
    if not isinstance(raw, dict) or "requests" not in raw:
        raise UploadError("В JSON нет поля requests: нужен датасет по контракту (офис, заявки, бригады)")
    raw.setdefault("id", dataset_id_for(filename, content))
    raw["id"] = dataset_id_for(filename, content)
    raw.setdefault("name", name or _title(filename))
    if name:
        raw["name"] = name
    raw.setdefault("date", load_assumptions()["date"])
    raw.setdefault("events", [])
    raw.setdefault("control", [])
    if "office" not in raw and raw.get("engineers"):
        first = raw["engineers"][0].get("start") or {}
        raw["office"] = {"address": "Старт бригад", "lat": first.get("lat"), "lon": first.get("lon")}
    try:
        Dataset.model_validate(raw)
    except ValidationError as error:
        first = error.errors()[0]
        where = ".".join(str(p) for p in first.get("loc", []))
        raise UploadError(f"Датасет не по контракту: {where} — {first.get('msg')}") from error
    return raw


def from_text(filename: str, content: str, *, name: str | None = None, engineers: int | None = None) -> dict:
    """Разобрать файл по расширению и дописать устройства с удалёнными подучастками."""
    if filename.lower().endswith(".json"):
        data = from_json(filename, content, name=name)
    elif filename.lower().endswith(".csv"):
        data = from_csv(filename, content, name=name, engineers=engineers)
    else:
        raise UploadError("Нужен файл .csv или .json")
    enrich.apply(data)
    return data


def save(data: dict, *, osrm: bool = True) -> str:
    """Положить датасет и матрицы в `data/uploads/`; вернуть идентификатор."""
    from .loadgen import build_matrices

    UPLOAD_DATASETS_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_MATRICES_DIR.mkdir(parents=True, exist_ok=True)
    (UPLOAD_DATASETS_DIR / f"{data['id']}.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    for profile, table in build_matrices(data, osrm=osrm).items():
        (UPLOAD_MATRICES_DIR / f"{data['id']}-{profile}.json").write_text(json.dumps(table) + "\n", encoding="utf-8")
    load_dataset.cache_clear()
    load_matrices.cache_clear()
    return data["id"]


def summary(data: dict) -> dict:
    """Что получилось из файла — диспетчеру в ответ."""
    quality = Counter(req.get("geo_quality", "house") for req in data["requests"])
    return {
        "id": data["id"],
        "name": data["name"],
        "requests": len(data["requests"]),
        "engineers": len(data["engineers"]),
        "control": len(data.get("control", [])),
        "geo": dict(quality),
    }
