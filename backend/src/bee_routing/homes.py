"""Адрес дома мастера: ближайший настоящий дом к точке, откуда бригада выезжает.

Заказчик домов бригад не давал. Точка дома в наборе — центр заявок бригады
в контрольный день (`prepare.add_homes`): с неё бригада стартует «из дома».
Диспетчеру и эксперту нужна не пара координат, а адрес, поэтому точке
подбирается ближайший дом с номером — обратным геокодером Nominatim по слою
адресов. Где у ближайшего объекта номера нет (улица, парк), ищем по спирали
вокруг точки, шаг за шагом дальше, но не дальше `SEARCH_M`.

Координаты дома не сдвигаются: матрицы, планы и отчёты считаны от точки,
а адрес — её подпись. Отсюда и пометка «условный» на экране. Ответы
геокодера живут в общем кэше (`data/geocode.json`, ключ `reverse:…`),
и повторная сборка в сеть не ходит.

Запуск: `uv run python -m bee_routing.homes` — подписать дома во всех наборах.
"""

from __future__ import annotations

import json
import math
import re
import time

import httpx

from .geocode import CACHE_PATH, load_assumptions
from .matrices import DATASETS_DIR

REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"
SEARCH_M = 400  # дальше этого подпись перестаёт описывать точку
RINGS = (0, 60, 120, 200, 300, 400)


class Reverse:
    """Обратный геокодер с кэшем и паузой между запросами, как у прямого."""

    def __init__(self, *, offline: bool = False) -> None:
        conf = load_assumptions()["geocode"]
        self.agent = conf["user_agent"]
        self.pause = float(conf["min_interval_sec"])
        self.offline = offline
        self.cache: dict = json.loads(CACHE_PATH.read_text(encoding="utf-8")) if CACHE_PATH.exists() else {}
        self._last = 0.0
        self.calls = 0

    def save(self) -> None:
        CACHE_PATH.write_text(json.dumps(self.cache, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")

    def ask(self, lat: float, lon: float) -> dict:
        key = f"reverse:{lat:.5f},{lon:.5f}"
        if key in self.cache:
            return self.cache[key]
        if self.offline:
            return {}
        wait = self.pause - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        self.calls += 1
        try:
            resp = httpx.get(
                REVERSE_URL,
                params={"lat": lat, "lon": lon, "format": "jsonv2", "zoom": 18, "layer": "address",
                        "addressdetails": 1, "accept-language": "ru"},
                headers={"User-Agent": self.agent},
                timeout=30.0,
            )
            resp.raise_for_status()
            body = resp.json()
        except (httpx.HTTPError, ValueError):
            return {}
        found = body.get("address") or {}
        hit = {
            "road": found.get("road") or found.get("pedestrian") or "",
            "house": found.get("house_number") or "",
            "city": found.get("city") or found.get("town") or found.get("village") or "",
        }
        self.cache[key] = hit
        return hit


def format_address(hit: dict) -> str:
    """«Москва, улица Маршала Захарова, 21к1» — в том же виде, что адреса заявок."""
    house = re.sub(r"\s+", "", hit.get("house", ""))
    return ", ".join(part for part in (hit.get("city", ""), hit.get("road", ""), house) if part)


def _around(lat: float, lon: float):
    """Точки поиска: сама точка, затем кольца по восьми сторонам."""
    for ring in RINGS:
        if ring == 0:
            yield lat, lon
            continue
        for k in range(8):
            angle = k * math.pi / 4
            dlat = ring * math.cos(angle) / 111_320
            dlon = ring * math.sin(angle) / (111_320 * math.cos(math.radians(lat)))
            yield lat + dlat, lon + dlon


def home_address(lat: float, lon: float, geo: Reverse) -> str | None:
    """Адрес ближайшего дома с номером; None — в радиусе поиска не нашлось."""
    fallback = None
    for plat, plon in _around(lat, lon):
        hit = geo.ask(plat, plon)
        if not hit.get("road"):
            continue
        if hit.get("house"):
            return format_address(hit)
        fallback = fallback or format_address(hit)
    return fallback


def attach(engineers: list[dict], geo: Reverse) -> int:
    """Подписать дома бригад адресами; вернуть, сколько подписано заново."""
    done = 0
    for eng in engineers:
        home = eng.get("home")
        if not home or home.get("address"):
            continue
        address = home_address(float(home["lat"]), float(home["lon"]), geo)
        if address:
            home["address"] = address
            done += 1
    return done


def main() -> int:
    """Подписать дома во всех собранных наборах; кэш геокодера сохраняется."""
    geo = Reverse()
    for path in sorted(DATASETS_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        added = attach(data.get("engineers", []), geo)
        if added:
            path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        missing = sum(1 for e in data.get("engineers", []) if e.get("home") and not e["home"].get("address"))
        print(f"{data['id']}: подписано {added}, без адреса {missing}")
        geo.save()
    print(f"запросов к геокодеру: {geo.calls}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
