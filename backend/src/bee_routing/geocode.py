"""Геокодирование адресов через публичный Nominatim с кэшем на диске.

Публичный сервис просит не чаще одного запроса в секунду и требует
представиться в User-Agent — оба условия соблюдаются здесь. Всё, что
однажды нашлось, ложится в `app/data/geocode.json`, и повторный запуск
подготовки данных в сеть не ходит вовсе.

Точность падает ступенями: дом → улица → центр района. Координаты
за пределами Москвы и области считаются промахом — качество понижается.

Запуск сводки: `uv run python -m bee_routing.geocode`.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import httpx

APP_DIR = Path(__file__).resolve().parents[3]
# Папку данных можно подменить: стенд держит рядом два набора — обезличенный
# для гостей и данные задания за входом, и каждый экземпляр API читает свой.
DATA_DIR = Path(os.environ.get("BEE_DATA_DIR") or APP_DIR / "data").resolve()
CACHE_PATH = DATA_DIR / "geocode.json"
ASSUMPTIONS_PATH = DATA_DIR / "assumptions.json"


def load_assumptions() -> dict:
    """Прочитать допущения проекта — единственный источник чисел."""
    return json.loads(ASSUMPTIONS_PATH.read_text(encoding="utf-8"))


def street_only(address: str) -> str:
    """Отрезать номер дома: «Москва, Шверника улица, 4/1к2» → «Москва, Шверника улица»."""
    parts = [p.strip() for p in address.split(",")]
    if len(parts) > 1 and re.match(r"^[\dк/сА-Яа-я]+$", parts[-1]):
        parts = parts[:-1]
    return ", ".join(parts)


def district_only(address: str, district: str) -> str:
    """Свести адрес к городу и району: последняя ступень точности."""
    head = address.split(",")[0].strip()
    clean = re.sub(r"^GPON\s+", "", district).strip()
    return f"{head}, {clean}" if clean else head


class Geocoder:
    """Кэширующий геокодер: сначала диск, потом сеть, не чаще раза в секунду."""

    def __init__(self, assumptions: dict | None = None, *, offline: bool = False) -> None:
        self.conf = (assumptions or load_assumptions())["geocode"]
        self.offline = offline
        self.cache: dict[str, dict] = {}
        if CACHE_PATH.exists():
            self.cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        self._last_call = 0.0
        self.network_calls = 0

    def save(self) -> None:
        """Сложить кэш на диск (устойчивый порядок ключей — файл не шумит в git)."""
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        ordered = {k: self.cache[k] for k in sorted(self.cache)}
        CACHE_PATH.write_text(
            json.dumps(ordered, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )

    def in_bbox(self, lat: float, lon: float) -> bool:
        """Москва и область: всё, что вне рамки, — промах геокодера."""
        b = self.conf["bbox"]
        return b["lat_min"] <= lat <= b["lat_max"] and b["lon_min"] <= lon <= b["lon_max"]

    def _ask(self, query: str) -> dict | None:
        """Один запрос к Nominatim с соблюдением паузы; None — не нашлось."""
        if query in self.cache:
            return self.cache[query]
        if self.offline:
            return None
        pause = self.conf["min_interval_sec"] - (time.monotonic() - self._last_call)
        if pause > 0:
            time.sleep(pause)
        self._last_call = time.monotonic()
        self.network_calls += 1
        try:
            resp = httpx.get(
                self.conf["url"],
                params={"q": query, "format": "json", "countrycodes": "ru", "limit": 1},
                headers={"User-Agent": self.conf["user_agent"]},
                timeout=30.0,
            )
            resp.raise_for_status()
            found = resp.json()
        except (httpx.HTTPError, ValueError):
            return None
        if not found:
            self.cache[query] = {}
            return {}
        hit = {"lat": float(found[0]["lat"]), "lon": float(found[0]["lon"])}
        self.cache[query] = hit
        return hit

    def locate(self, address: str, district: str = "") -> tuple[float, float, str]:
        """Найти координаты, спускаясь по ступеням точности: дом → улица → район."""
        steps = [
            (address, "house"),
            (street_only(address), "street"),
            (district_only(address, district), "district"),
        ]
        seen: set[str] = set()
        for query, quality in steps:
            if not query or query in seen:
                continue
            seen.add(query)
            hit = self._ask(query)
            if hit and self.in_bbox(hit["lat"], hit["lon"]):
                return hit["lat"], hit["lon"], quality
        raise LookupError(f"Не нашёлся адрес: {address}")


def summary(datasets_dir: Path | None = None) -> str:
    """Сводка по качеству геокодирования собранных датасетов."""
    datasets_dir = datasets_dir or DATA_DIR / "datasets"
    lines: list[str] = []
    rough: list[str] = []
    for path in sorted(datasets_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        counts = {"house": 0, "street": 0, "district": 0}
        for req in data["requests"]:
            counts[req["geo_quality"]] += 1
            if req["geo_quality"] == "district":
                rough.append(f"  {data['id']} / {req['id']}: {req['address']}")
        lines.append(
            f"{data['id']:>12}: дом {counts['house']:>3}, улица {counts['street']:>3},"
            f" район {counts['district']:>3}"
        )
    lines.append("Адреса, доехавшие только до района (правятся руками):")
    lines.extend(rough or ["  нет"])
    return "\n".join(lines)


if __name__ == "__main__":
    print(summary())
