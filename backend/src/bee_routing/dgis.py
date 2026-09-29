"""Время в пути с пробками от 2ГИС (Distance Matrix API) — живой источник, без хранения.

Зачем. OSRM считает дорогу по свободной сети: 25 минут между точками
в 13:00 и в 19:00 для него одно и то же. 2ГИС отдаёт время по текущим
пробкам (`type: jam`) и по статистике на заданный час (`type: statistics`
со `start_time`), а ещё велосипед, самокат, пешком и общественный
транспорт по расписанию. Этим модулем планировщик спрашивает время
на те часы, на которые он строит план.

Четыре вещи, которые нельзя ломать:

1. **Ответы хранятся только там, где это разрешено.** Оферта на WebAPI
   (редакция от 27.03.2026, п. 3.1) запрещает извлекать и сохранять
   полученные данные. 16.09.2026 команда получила у 2ГИС разрешение
   хранить ответы для проекта; поэтому сам клиент ничего не пишет,
   а ряды копит отдельный сборщик (`dgis_collect`) — вне репозитория,
   в `~/.bee-ltzp/traffic-2gis/`. В git и на сайт уезжают только
   сводные коэффициенты, сырых времён 2ГИС там нет.
2. **Единица тарификации — пара «откуда → куда», а не запрос.**
   Матрица 3 × 4 стоит 12 единиц. Справочник обещает массив времён
   старта в одном запросе, но сервер 16.09.2026 отвечал на массив
   ошибкой 400 «non-RFC3339 form» — поэтому одно время на запрос,
   и 12 × число времён. Демо-ключ
   даёт 1 000 единиц на всё время, поэтому бюджет проверяется до
   запроса, а не после.
3. **Демо-ключ не считает точки дальше 50 км друг от друга** (ответ 403
   «excessive distance between points for demo-keys»). Для Юго-востока
   это Кашира и Ступино — 20 заявок из 83; они требуют платного ключа.
4. **Синхронный режим — не больше 25 точек отправления и 25 прибытия.**
   Больше — режем на блоки сами; асинхронный режим включает только
   поддержка 2ГИС.

Ключ: переменная `DGIS_API_KEY` или `~/.bee-ltzp/2gis.json`, вне репозитория:
`{"keys": [{"key": "...", "budget_units": 1000}, ...]}` — ключи расходуются
по порядку, израсходованный пропускается; старая запись `{"key": ...}` тоже
читается. Расход считается по каждому ключу отдельно (`by_key` в счётчике,
по первым восьми знакам ключа — самого ключа в счётчике нет).

Запуск:
    uv run python -m bee_routing.dgis usage
    uv run python -m bee_routing.dgis probe --dry-run
    uv run python -m bee_routing.dgis probe --hours 10,13,19 --profiles car,transit
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

import httpx

ENDPOINT = "https://routing.api.2gis.com/get_dist_matrix"
API_VERSION = "2.0"
SYNC_LIMIT = 25
HOME_DIR = Path.home() / ".bee-ltzp"
KEY_PATH = HOME_DIR / "2gis.json"
USAGE_PATH = HOME_DIR / "2gis-usage.json"
DEMO_BUDGET = 1000
MSK = timezone(timedelta(hours=3))

# Профили планировщика → способ передвижения 2ГИС.
TRANSPORT = {
    "car": "driving",
    "taxi": "taxi",
    "bike": "bicycle",
    "scooter": "scooter",
    "foot": "walking",
    "transit": "public_transport",
}
# Тип маршрута (`jam`, `statistics`, `shortest`) относится к автомобилю.
ROAD_PROFILES = {"car", "taxi"}


class BudgetExceeded(RuntimeError):
    """Запрос съел бы больше единиц, чем осталось в бюджете ключа."""


class DgisError(RuntimeError):
    """2ГИС ответил ошибкой: ключ, лимит, содержимое запроса."""


class RateLimited(DgisError):
    """Поминутный предел ключа: 429 «too many requests». Ждать минуту."""


class Http(Protocol):
    def post(self, url: str, **kwargs: Any) -> Any: ...


@dataclass(frozen=True)
class Leg:
    """Одна пара «откуда → куда» на одно время старта."""

    source: int
    target: int
    start: str | None
    status: str
    duration_s: int | None
    distance_m: int | None

    @property
    def minutes(self) -> float | None:
        return None if self.duration_s is None else self.duration_s / 60


def units_for(n_sources: int, n_targets: int, n_starts: int = 1) -> int:
    """Сколько единиц тарификации стоит матрица."""
    return n_sources * n_targets * max(1, n_starts)


def msk_to_rfc3339(day: date, hour: int, minute: int = 0) -> str:
    """Московское время → RFC 3339 в UTC, как его ждёт 2ГИС."""
    local = datetime(day.year, day.month, day.day, hour, minute, tzinfo=MSK)
    return local.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_keys(path: Path = KEY_PATH) -> list[tuple[str, int]]:
    """Все ключи с бюджетами по порядку: переменная окружения главнее файла."""
    conf: dict = {}
    if path.exists():
        conf = json.loads(path.read_text(encoding="utf-8"))
    default = int(conf.get("budget_units", DEMO_BUDGET))
    if os.environ.get("DGIS_API_KEY"):
        return [(os.environ["DGIS_API_KEY"], default)]
    keys = [(k["key"], int(k.get("budget_units", default))) for k in conf.get("keys", []) if k.get("key")]
    if conf.get("key"):
        keys.insert(0, (conf["key"], default))
    return keys


def load_key(path: Path = KEY_PATH, usage: Usage | None = None, need: int = 1) -> tuple[str | None, int]:
    """Первый ключ, у которого осталось хотя бы `need` единиц; иначе первый по списку."""
    keys = load_keys(path)
    if not keys:
        return None, DEMO_BUDGET
    usage = usage or Usage()
    for key, budget in keys:
        if budget - usage.spent_by(key) >= need:
            return key, budget
    return keys[0]


def total_left(path: Path = KEY_PATH, usage: Usage | None = None) -> int:
    """Сколько единиц осталось на всех ключах вместе."""
    usage = usage or Usage()
    return sum(max(0, budget - usage.spent_by(key)) for key, budget in load_keys(path))


class Usage:
    """Счётчик израсходованных единиц. Хранит числа, ответов 2ГИС в нём нет."""

    def __init__(self, path: Path = USAGE_PATH) -> None:
        self.path = path
        self.data = {"units_spent": 0, "requests": 0, "by_day": {}}
        if path.exists():
            self.data.update(json.loads(path.read_text(encoding="utf-8")))

    @property
    def spent(self) -> int:
        return int(self.data["units_spent"])

    def spent_by(self, key: str) -> int:
        """Расход одного ключа. Ключ, заведённый до учёта по ключам, считается весь общий расход."""
        by_key = self.data.get("by_key")
        if by_key is None:
            return self.spent
        return int(by_key.get(key[:8], 0))

    def add(self, units: int, today: date | None = None, key: str | None = None) -> None:
        day = (today or datetime.now(MSK).date()).isoformat()
        if key:
            by_key = self.data.setdefault("by_key", {})
            by_key[key[:8]] = int(by_key.get(key[:8], 0)) + units
        self.data["units_spent"] = self.spent + units
        self.data["requests"] = int(self.data["requests"]) + 1
        self.data["by_day"][day] = int(self.data["by_day"].get(day, 0)) + units
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=1) + "\n")


def build_body(
    coords: list[tuple[float, float]],
    sources: list[int],
    targets: list[int],
    profile: str,
    starts: list[str] | None,
    mode: str,
    transit_modes: list[str] | None = None,
) -> tuple[dict, list[int]]:
    """Тело запроса для одного блока и таблица «местный индекс → общий»."""
    if profile not in TRANSPORT:
        raise ValueError(f"Нет такого профиля у 2ГИС: {profile}")
    order = list(sources) + list(targets)
    body: dict[str, Any] = {
        "points": [{"lat": coords[i][0], "lon": coords[i][1]} for i in order],
        "sources": list(range(len(sources))),
        "targets": list(range(len(sources), len(order))),
        "transport": TRANSPORT[profile],
    }
    if profile in ROAD_PROFILES:
        body["type"] = mode
    if starts:
        if len(starts) > 1:
            raise ValueError("2ГИС принимает одно время старта на запрос")
        body["start_time"] = starts[0]
    elif mode == "statistics" and profile in ROAD_PROFILES:
        raise ValueError("Статистика пробок требует времени старта")
    if profile == "transit":
        params: dict[str, Any] = {"enable_schedule": True}
        if transit_modes:
            params["transport"] = transit_modes
        body["public_transport_params"] = params
    return body, order


def parse_routes(data: dict, order: list[int], starts: list[str] | None) -> list[Leg]:
    """Ответ 2ГИС → пары с общими индексами точек."""
    legs = []
    for route in data.get("routes") or []:
        start = route.get("start_time")
        if isinstance(start, (int, float)):
            start = datetime.fromtimestamp(start, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        elif starts and len(starts) == 1:
            start = starts[0]
        ok = route.get("status") == "OK"
        legs.append(
            Leg(
                source=order[route["source_id"]],
                target=order[route["target_id"]],
                start=start,
                status=route.get("status", "FAIL"),
                duration_s=route.get("duration") if ok else None,
                distance_m=route.get("distance") if ok else None,
            )
        )
    return legs


def chunks(items: list[int], size: int) -> list[list[int]]:
    return [items[i : i + size] for i in range(0, len(items), size)] or [[]]


class DgisMatrix:
    """Клиент синхронной матрицы 2ГИС с бюджетом и без памяти об ответах."""

    def __init__(
        self,
        key: str,
        budget_units: int = DEMO_BUDGET,
        usage: Usage | None = None,
        http: Http | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.key = key
        self.budget = budget_units
        self.usage = usage or Usage()
        self.http = http or httpx
        self.timeout = timeout

    @property
    def left(self) -> int:
        return self.budget - self.usage.spent_by(self.key)

    def matrix(
        self,
        coords: list[tuple[float, float]],
        sources: list[int],
        targets: list[int],
        profile: str = "car",
        starts: list[str] | None = None,
        mode: str = "statistics",
        transit_modes: list[str] | None = None,
    ) -> list[Leg]:
        """Все пары sources × targets на каждое время старта."""
        total = units_for(len(sources), len(targets), len(starts or []))
        if total > self.left:
            raise BudgetExceeded(f"Нужно {total} единиц, осталось {self.left} из {self.budget}")
        legs: list[Leg] = []
        for start in starts or [None]:
            one = [start] if start else None
            for src in chunks(sources, SYNC_LIMIT):
                for tgt in chunks(targets, SYNC_LIMIT):
                    legs.extend(self._block(coords, src, tgt, profile, one, mode, transit_modes))
        return legs

    def _block(
        self,
        coords: list[tuple[float, float]],
        src: list[int],
        tgt: list[int],
        profile: str,
        starts: list[str] | None,
        mode: str,
        transit_modes: list[str] | None,
    ) -> list[Leg]:
        """Один синхронный запрос: блок до 25 × 25 на одно время старта."""
        body, order = build_body(coords, src, tgt, profile, starts, mode, transit_modes)
        resp = self.http.post(
            ENDPOINT,
            params={"key": self.key, "version": API_VERSION},
            json=body,
            timeout=self.timeout,
        )
        if resp.status_code == 204:
            data: dict = {"routes": []}
        elif resp.status_code == 429:
            raise RateLimited(f"2ГИС ответил 429: {resp.text[:300]}")
        elif resp.status_code != 200:
            raise DgisError(f"2ГИС ответил {resp.status_code}: {resp.text[:300]}")
        else:
            data = resp.json()
        self.usage.add(units_for(len(src), len(tgt)), key=self.key)
        return parse_routes(data, order, starts)


# ── Пробник: сверить 2ГИС с OSRM на нескольких точках региона ───────────────

DEFAULT_PICK = {
    # Центральные заявки зон Юго-востока (сетка ячеек из листа «Архив пробок»).
    "yugo-vostok": {
        "sources": ["office", "20055", "19216"],
        # Кашира и Ступино (85—95 км от офиса) демо-ключ не считает: предел 50 км.
        "targets": ["1287", "32066", "13583", "7258"],
    }
}


def next_weekday(weekday: int, today: date | None = None) -> date:
    """Ближайший будущий день недели (0 — понедельник)."""
    today = today or datetime.now(MSK).date()
    return today + timedelta(days=(weekday - today.weekday()) % 7 or 7)


def probe(args: argparse.Namespace) -> int:
    from .matrices import DATASETS_DIR, MATRICES_DIR, points_of

    dataset = json.loads((DATASETS_DIR / f"{args.dataset}.json").read_text(encoding="utf-8"))
    ids, coords = points_of(dataset)
    index = {name: i for i, name in enumerate(ids)}
    pick = DEFAULT_PICK.get(args.dataset, {})
    src_names = args.sources.split(",") if args.sources else pick.get("sources", ids[:3])
    tgt_names = args.targets.split(",") if args.targets else pick.get("targets", ids[3:7])
    sources = [index[n] for n in src_names]
    targets = [index[n] for n in tgt_names]
    day = date.fromisoformat(args.date) if args.date else next_weekday(1)
    hours = [int(h) for h in args.hours.split(",")]
    starts = [msk_to_rfc3339(day, h) for h in hours]
    profiles = args.profiles.split(",")

    cost = sum(units_for(len(sources), len(targets), len(starts)) for _ in profiles)
    key, budget = load_key()
    usage = Usage()
    print(f"{args.dataset}: {len(sources)} × {len(targets)} пар, часы {hours} МСК {day}, "
          f"профили {profiles} → {cost} единиц; по ключу израсходовано {usage.spent_by(key or '')} из {budget}")
    if args.dry_run or not key:
        if not key:
            print("Ключа нет: положите его в ~/.bee-ltzp/2gis.json или DGIS_API_KEY.")
        body, _ = build_body(coords, sources, targets, profiles[0], starts, args.mode)
        print(json.dumps(body, ensure_ascii=False, indent=1))
        return 0

    client = DgisMatrix(key, budget, usage)
    for profile in profiles:
        osrm_profile = {"scooter": "bike", "taxi": "car"}.get(profile, profile)
        osrm_path = MATRICES_DIR / f"{args.dataset}-{osrm_profile}.json"
        osrm = json.loads(osrm_path.read_text(encoding="utf-8")) if osrm_path.exists() else None
        legs = client.matrix(coords, sources, targets, profile, starts, args.mode)
        print(f"\n{profile}: минуты 2ГИС по часам старта МСК; OSRM — свободная сеть")
        print("откуда → куда".ljust(24) + "OSRM".rjust(6) + "".join(f"{h:>6}" for h in hours))
        by_pair: dict[tuple[int, int], dict[str, Leg]] = {}
        for leg in legs:
            by_pair.setdefault((leg.source, leg.target), {})[leg.start or ""] = leg
        for (s, t), per_start in by_pair.items():
            base = osrm["duration_min"][s][t] if osrm else None
            cells = []
            for start in starts:
                leg = per_start.get(start)
                cells.append(f"{leg.minutes:6.0f}" if leg and leg.minutes is not None
                             else f"{(leg.status[:5] if leg else '—'):>6}")
            label = f"{ids[s]} → {ids[t]}"[:23].ljust(24)
            print(label + (f"{base:6}" if base is not None else "     —") + "".join(cells))
    print(f"\nПо ключу {key[:4]}… израсходовано {client.usage.spent_by(key)} из {budget}. "
          "Пробник ответов не сохраняет.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bee_routing.dgis", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("usage", help="сколько единиц израсходовано")
    p = sub.add_parser("probe", help="сверить 2ГИС с OSRM на точках региона")
    p.add_argument("--dataset", default="yugo-vostok")
    p.add_argument("--sources", help="id точек через запятую; office — офис")
    p.add_argument("--targets")
    p.add_argument("--date", help="ГГГГ-ММ-ДД; по умолчанию ближайший вторник")
    p.add_argument("--hours", default="13,19")
    p.add_argument("--profiles", default="car")
    p.add_argument("--mode", default="statistics", choices=["statistics", "jam", "shortest"])
    p.add_argument("--dry-run", action="store_true", help="показать запрос и цену, в сеть не ходить")
    args = parser.parse_args(argv)
    if args.cmd == "usage":
        usage = Usage()
        for key, budget in load_keys():
            print(f"Ключ {key[:4]}…: израсходовано {usage.spent_by(key)} из {budget}")
        print(f"Всего израсходовано {usage.spent}; осталось на ключах {total_left(usage=usage)}; "
              f"запросов {usage.data['requests']}; по дням {usage.data['by_day']}")
        return 0
    return probe(args)


if __name__ == "__main__":
    raise SystemExit(main())
