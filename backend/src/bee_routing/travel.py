"""Дорога между двумя точками: какой транспорт взять на переезд и сколько это займёт.

У исполнителя набор видов транспорта (`Engineer.transports`), а не один:
инженер с машиной ходит пешком в соседний дом, «пешеход» едет
на автобусе. Вид выбирается на каждый переезд — тот, что быстрее, —
и записывается в остановку маршрута (`Stop.mode`), чтобы диспетчер видел
и мог переключить.

Время OSRM считается по свободной сети, а исполнитель ездит по живому
городу. Поправки сняты 16.09.2026 с 2ГИС на 12 парах Юго-востока
(лист «Архив пробок и время в пути», разд. 5): автомобиль ×1,3,
велосипед ×1,09, пешком ×0,87, общественный транспорт ×0,78 к нашей
модели «18 км/ч + 8 минут». Автомобилю прибавляется парковка: эксперт
16.09.2026 велел закладывать её во время на дорогу.

Числа живут в `assumptions.json` (`travel`), здесь их нет.

**Переезд считается один раз на запрос.** Примерка заявки в маршрут
перестраивает маршрут целиком на каждое место, и на тысяче заявок
`leg` зовётся миллионы раз за один расчёт — с одним и тем же ответом.
Кэш живёт, пока живут настройки запроса (`settings.merged()` — один
объект на запрос) и та же матрица; сменился любой из них — кэш пустой.
Ключ — набор транспорта, две точки, час выезда и тип дня (час нужен
автомобилю и общественному транспорту при почасовом трафике, иначе
в ключе ноль).
"""

from __future__ import annotations

from dataclasses import dataclass

from . import settings
from .matrices import Matrices
from .models import Engineer, Transport


def hour_profile(day_type: str = "workday") -> dict[int, float]:
    """Множитель часа к дневному плато будней для типа дня (см. `day_profile`)."""
    from .day_profile import profile

    return profile(day_type)


def resolve_day_type(matrices: Matrices | None) -> str:
    """Тип дня расчёта: из настройки, а при `auto` — по дате набора."""
    chosen = settings.option("day_type") or "auto"
    if chosen != "auto":
        return str(chosen)
    return getattr(matrices, "day_type", None) or "workday"


def hour_factor(mode: str, depart_min: int | None, day_type: str = "workday") -> float:
    """Множитель часа и дня: автомобилю — пробки, общественному транспорту — расписание.

    Пешком и на велосипеде от часа не зависит. Без часа выезда (решатель
    внутри поиска) — средний уровень дня: суббота легче будней весь день,
    а транспорт в выходные ходит реже.
    """
    if mode not in ("car", "transit") or not settings.option("hourly_traffic"):
        return 1.0
    from .day_profile import day_level, transit_level, transit_profile

    if mode == "transit":
        if depart_min is None:
            return transit_level(day_type)
        return transit_profile(day_type).get((depart_min // 60) % 24, 1.0)

    if depart_min is None:
        return day_level(day_type)
    return hour_profile(day_type).get((depart_min // 60) % 24, 1.0)


DEFAULT_TRAVEL = {
    "car": {"factor": 1.0, "extra_min": 0},
    "bike": {"factor": 1.0, "extra_min": 0},
    "foot": {"factor": 1.0, "extra_min": 0},
    "transit": {"factor": 1.0, "extra_min": 0},
}


_cache: dict = {"tree": None, "matrices": None, "conf": None, "legs": {}, "hourly": None}


def _scope(matrices: Matrices | None) -> dict:
    """Кэш переездов текущего запроса; другой запрос или другая матрица — кэш заново."""
    tree = settings.merged()
    if _cache["tree"] is not tree or _cache["matrices"] is not matrices:
        _cache.update(tree=tree, matrices=matrices, conf=None, legs={}, hourly=None)
    return _cache


def travel_conf() -> dict:
    """Поправки к OSRM по видам транспорта; без учёта трафика — свободная дорога."""
    scope = _scope(_cache["matrices"])
    if scope["conf"] is None:
        conf = DEFAULT_TRAVEL if not settings.option("traffic") else {
            **DEFAULT_TRAVEL, **settings.section("travel")
        }
        # Сезон и погода — общий множитель дороги поверх поправок вида (`options.season_factor`):
        # снег и гололёд замедляют и машину, и пешехода, поэтому действует и без учёта трафика.
        season = float(settings.option("season_factor") or 1.0)
        if season != 1.0:
            conf = {mode: ({**part, "factor": float(part.get("factor", 1.0)) * season} if isinstance(part, dict)
                           else part) for mode, part in conf.items()}
        scope["conf"] = conf
    return scope["conf"]


@dataclass(frozen=True)
class Leg:
    """Один переезд: чем ехать, сколько минут и километров."""

    mode: Transport
    minutes: int
    km: float


def adjusted(mode: str, raw_min: int, raw_km: float, depart_min: int | None = None,
             day_type: str = "workday") -> tuple[int, float]:
    """Минуты OSRM → минуты по живому городу с поправкой вида, надбавкой и часом выезда."""
    if raw_min == 0 and raw_km == 0:
        return 0, 0.0
    conf = travel_conf().get(mode, DEFAULT_TRAVEL["car"])
    minutes = round(raw_min * float(conf.get("factor", 1.0)) * hour_factor(mode, depart_min, day_type)
                    + int(conf.get("extra_min", 0)))
    return max(minutes, 1), raw_km


def leg(engineer: Engineer, prev_id: str, target_id: str, matrices: Matrices | None,
        depart_min: int | None = None) -> Leg:
    """Лучший переезд из точки в точку среди видов транспорта бригады.

    `depart_min` — час выезда: с ним автомобиль едет по профилю часа,
    без него — по среднему дню (так считает решатель внутри поиска).
    """
    modes = engineer.transports or [engineer.transport]
    if matrices is None:
        return Leg(mode=modes[0], minutes=0, km=0.0)
    scope = _scope(matrices)
    hourly = scope.get("hourly")
    if hourly is None:
        # Опция и тип дня — одни на запрос; `leg` зовут сотни тысяч раз за расчёт.
        hourly = scope["hourly"] = (bool(settings.option("hourly_traffic")), resolve_day_type(matrices))
    hour = (depart_min // 60) % 24 if depart_min is not None and hourly[0] else None
    day_type = hourly[1]
    key = (tuple(modes), prev_id, target_id, hour, day_type)
    legs = scope["legs"]
    found = legs.get(key)
    if found is not None:
        return found
    best: Leg | None = None
    for mode in modes:
        raw_min, raw_km = matrices.travel(mode.value, prev_id, target_id)
        minutes, km = adjusted(mode.value, raw_min, raw_km, depart_min, day_type)
        if best is None or minutes < best.minutes:
            best = Leg(mode=mode, minutes=minutes, km=km)
    legs[key] = best  # modes непустой по валидатору модели
    return best
