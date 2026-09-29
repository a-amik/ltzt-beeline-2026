"""Буфер и риск окна: насколько план хрупок к отклонениям дороги и работы.

План считается минута в минуту: дорога ровно по матрице, работа ровно
по нормативу. В жизни ни того, ни другого не бывает, и первое опоздание
на дороге тянет за собой цепочку визитов. Задание называет прогноз опозданий
дополнительной возможностью, отчёт о решении — пятым ограничением
методологии. Здесь и то и другое: каждый визит получает риск срыва окна,
план — ожидаемое число таких визитов.

Как считается. Маршрут бригады проживается `runs` раз (по умолчанию 200)
со случайным шумом: время каждого переезда и каждой работы умножается
на логнормальный множитель со средним 1 и разбросом `spread_travel`
и `spread_work` из допущений. Приехал раньше окна — ждёт, как и в плане;
начал позже конца окна — визит сорван в этом прогоне. Обед берётся там,
где он стоит в плане, — **по месту в маршруте, а не по часам**: перед тем
визитом, перед которым он стоит. До 19.09.2026 он брался по часам («как
только часы прогона дошли до планового начала обеда»), и у бригады, идущей
раньше плана, обед переезжал за следующий визит: полчаса, которые в плане
съедало ожидание окна, ложились на тесный визит после него. Риск визита — доля прогонов, где начало вышло
за окно; `arrive_p90` — приезд, которого не превысят девять прогонов
из десяти. У плана: `risk_late` — сумма рисков (ожидаемое число сорванных
окон), `risky_stops` — визитов с риском не ниже порога.

Буфер. Риск меряет план после расчёта; чтобы решатель строил план, который
риск выдержит, у каждого визита считается **приезд с запасом**: к плановому
времени прибавляется накопленный запас — доля от дороги и от работы,
пройденных с последнего ожидания. Правило одно для решателя (второе
измерение времени, `solver.py`) и для вставки с перестройкой маршрута
(`insertion.rebuild`), и оно же объясняет отказ: «окно не удержать при
разбросе дороги и работы». Запас — `z · (σ_дороги · минуты дороги +
σ_работы · минуты работы)`; ожидание начала окна его съедает: приехал
с запасом раньше окна — дальше цепочка идёт от начала окна, разброс утра
ничего не значит. Сумма запасов строже честного p90 цепочки (независимый
шум частично гасит сам себя), поэтому `z` меньше табличных 1,28 и подобран
замером: уровни `RELIABILITY`.

Четыре вещи, которые нельзя ломать:

0. **Запас считается одной функцией** (`Buffer`), и зовут её и решатель,
   и перестройка маршрута. Разойдутся — решатель поставит визит, который
   вставка сочтёт недопустимым, и пересчёт дня выбросит его из маршрута.
1. **Шум посеян, а не случаен.** Зерно — регион, бригада и порядок её
   визитов: тот же план даёт тот же риск при любом пересчёте, иначе
   цифра на карточке прыгала бы при каждом открытии.
2. **Маршрут не перестраивается.** Риск меряет план как он есть; что
   диспетчер сделает с сорванным окном — отдельный вопрос пересчёта.
3. **Контроль и базовый меряются тем же шумом** (`benchmark.kpis`):
   сравнение робастности честное только при одном разбросе у всех.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import numpy as np

from . import settings
from .checks import to_clock, to_min
from .models import Plan, Request

DEFAULTS = {"spread_travel": 0.25, "spread_work": 0.2, "runs": 200, "threshold": 0.2}

# Уровни надёжности окон: множитель z к разбросу. Подобраны замером на трёх
# регионах (см. лист «Три улучшения»): сумма запасов строже честного p90.
RELIABILITY = {"off": 0.0, "medium": 0.6, "high": 1.0}

LATE_TEXT = "Окно не удержать при разбросе дороги и работы: приезд с запасом позже конца окна"


@dataclass(frozen=True)
class Buffer:
    """Запас к плановому времени: доля дороги и доля работы с последнего ожидания."""

    travel: float
    work: float

    @property
    def on(self) -> bool:
        return self.travel > 0 or self.work > 0

    def road(self, minutes: float) -> float:
        return self.travel * minutes

    def job(self, minutes: float) -> float:
        return self.work * minutes

    def after_start(self, acc: float, arrive: int, begin: int) -> float:
        """Запас после начала работы: ожидание окна его съедает."""
        return max(0.0, arrive + acc - begin)


def buffer() -> Buffer:
    """Запас текущего запроса; надёжность выключена — нулевой."""
    z = RELIABILITY.get(str(settings.option("reliability") or "off"), 0.0)
    cfg = conf()
    return Buffer(travel=z * float(cfg["spread_travel"]), work=z * float(cfg["spread_work"]))


def conf() -> dict:
    """Настройки риска текущего запроса поверх умолчаний."""
    return {**DEFAULTS, **settings.section("risk")}


def _seed(plan: Plan, engineer_id: str, stop_ids: list[str]) -> int:
    digest = hashlib.sha1(f"{plan.dataset_id}|{engineer_id}|{','.join(stop_ids)}".encode()).hexdigest()
    return int(digest[:8], 16)


def _noise(rng: np.random.Generator, spread: float, size: int) -> np.ndarray:
    """Логнормальный множитель со средним 1: exp(σz − σ²/2)."""
    if spread <= 0:
        return np.ones(size)
    return np.exp(rng.standard_normal(size) * spread - spread * spread / 2)


def annotate(plan: Plan, requests: dict[str, Request]) -> Plan:
    """Проставить риск каждому визиту и плану; выключенная опция обнуляет поля."""
    enabled = bool(settings.option("risk"))
    cfg = conf()
    runs, threshold = int(cfg["runs"]), float(cfg["threshold"])
    s_travel, s_work = float(cfg["spread_travel"]), float(cfg["spread_work"])
    total, risky = 0.0, 0
    for route in plan.routes:
        stops = route.stops
        if not enabled or not stops:
            for stop in stops:
                stop.late_risk, stop.arrive_p90 = 0.0, None
            continue
        rng = np.random.default_rng(_seed(plan, route.engineer_id, [s.request_id for s in stops]))
        clock = np.full(runs, float(to_min(stops[0].depart_prev)))
        brk = (to_min(route.break_start), to_min(route.break_end) - to_min(route.break_start)) \
            if route.break_start and route.break_end else None
        # Обед стоит перед первым визитом, который по плану начинается после него.
        brk_before = next((i for i, s in enumerate(stops) if brk and to_min(s.start) >= brk[0] + brk[1]), None)
        for i, stop in enumerate(stops):
            req = requests.get(stop.request_id)
            if brk is not None and i == brk_before:
                clock = clock + brk[1]
            arrive = clock + stop.travel_min * _noise(rng, s_travel, runs)
            if req is None:
                clock = arrive
                stop.late_risk, stop.arrive_p90 = 0.0, None
                continue
            start = np.maximum(arrive, float(to_min(req.window_start)))
            late = start > float(to_min(req.window_end))
            duration = 0.0 if stop.status == "no_show" else float(req.duration_min)
            clock = start + duration * _noise(rng, s_work, runs)
            stop.late_risk = round(float(late.mean()), 3)
            stop.arrive_p90 = to_clock(int(round(float(np.percentile(arrive, 90)))))
            total += stop.late_risk
            if stop.late_risk >= threshold:
                risky += 1
    plan.metrics.risk_late = round(total, 2)
    plan.metrics.risky_stops = risky
    return plan
