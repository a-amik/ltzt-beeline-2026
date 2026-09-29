"""HTTP API планировщика — ровно то, что описано в `app/CONTRACT.md`.

GET  /health          — жив ли сервис
GET  /datasets        — список регионов
GET  /datasets/{id}   — регион целиком: офис, заявки, бригады, сценарии
POST /plan            — построить план (algorithm, start: office | home)
POST /replan          — пересчитать план после события
POST /plan/{id}/assign — отдать заявку бригаде руками или принять предложение
GET  /settings        — форма настроек: тарифы, обед, скорости, что учитывать
GET  /rules           — общие правила дня: их задаёт руководитель, под расчёт ложатся всем
PUT  /rules           — заменить общие правила; только с заголовком X-Bee-Role: manager
POST /compare         — контроль, базовый и наш план на регионе с показателями
GET  /datasets/{id}/control — контрольное распределение заказчика как план
GET  /plan/latest     — последний посчитанный план (для приложения бригады)
GET  /plan/{id}/crew/{engineer_id} — день бригады: маршрут, предложения, заработок
GET  /plan/{id}/crew/{engineer_id}/transit?request_id= — на чём ехать: путь по расписанию 2ГИС
POST /plan/{id}/marks — отметка бригады по визиту; в ответе журнал и флаги контроля
GET  /plan/{id}/fraud — флаги контроля по журналу отметок
POST /plan/{id}/offers/respond — ответ бригады на предложение: принять или отказаться
POST /simulate        — имитация операционного дня с событиями
POST /plan/{id}/defer — перенести неназначенную заявку на следующий день
GET  /geocode?q=      — координаты адреса (Nominatim с кэшем) для дома бригады
GET  /ready           — готовые планы: что посчитано заранее и что считается сейчас
POST /datasets/upload — свой набор: CSV заказчика или JSON по контракту текстом файла
GET  /auth/me, POST /auth/login, /auth/logout — гостевой режим стенда и вход (`access.py`)

Утренний план решателем не считается по нажатию: он лежит готовым
(`ready.py`) — прогрет при старте сервиса, доведён в фоне, и `POST /plan`
с теми же настройками отдаёт его за время ответа сети. Первая загрузка
экрана оттого не ждёт решателя.
GET  /plan/{id}/deficit — карта дефицита: районы × окна, давление, подсказки сервисным отделам
POST /deficit {plan}  — то же по присланному плану
POST /replan/variants {plan_id, events} — варианты ответа на пачку событий
POST /plan/{id}/adopt — принятый вариант становится планом дня

Приложение бригады для показа (`crew_app.py`), без учётных записей:
GET|PUT /crew/{регион}/{бригада}/profile — адреса и адрес старта следующего дня
GET  /plan/{id}/crew/{бригада}/ways?request_id= — как доехать: время и цена по способам, прокат рядом
GET  /crew/vehicles?lat=&lon= — синтетический прокат вокруг точки
POST /plan/{id}/crew/{бригада}/call — подменный номер для звонка клиенту
GET|POST /crew/{регион}/{бригада}/messages — переписка с диспетчером, «проблема», SOS
GET  /crew/{регион}/inbox — непрочитанное от бригад для диспетчера
POST /crew/{регион}/{бригада}/report, /shift — отчёт по заявке, события смены
GET  /crew/{регион}/{бригада}/history — смены и отзывы (синтетика)
GET  /route?profile=&coords= — линия пути по улицам (OSRM) для карты бригады

`algorithm: "solver"` — решатель OR-Tools (`solver.py`), `"baseline"` —
последовательный вариант по ТЗ (`baseline.py`). Пересчёт после события
идёт тем же алгоритмом, каким построен исходный план.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from contextlib import asynccontextmanager
from itertools import count
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import access, mornings, ready, risk, settings
from .baseline import build_baseline
from .benchmark import KPI_LABELS
from .benchmark import compare as run_compare
from .benchmark import kpis as run_kpis
from .control import control_plan
from .crew import crew_day, respond
from .deficit import deficit_map
from .economy import summarize
from .fraud import audit
from .geocode import Geocoder
from .insertion import assign as run_assign
from .loader import dataset_ids, dataset_infos, load_dataset, load_matrices
from .models import (
    AssignRequest,
    CompareRequest,
    Comparison,
    CrewDay,
    CustomEvent,
    Dataset,
    DatasetInfo,
    Deferred,
    DeferRequest,
    DeficitMap,
    Event,
    Mark,
    MarkRequest,
    OfferResponse,
    Plan,
    PlanRequest,
    ReplanRequest,
    RespondRequest,
    ScenarioSpec,
    SimulationResult,
    UploadRequest,
    VariantsRequest,
    VariantsResponse,
)
from .replan import replan as run_replan
from .reports import reports as build_reports
from .simulate import simulate as run_simulate
from .upload import UploadError
from .upload import from_text as upload_from_text
from .upload import save as upload_save
from .upload import summary as upload_summary
from .variants import variants as run_variants


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Прогрев готовых планов в отдельной нити: сервис отвечает сразу, планы доезжают следом.

    Память сервиса — планы, журнал отметок, ответы на предложения, переписка,
    отчёты и смены бригад — переживает перезапуск: при остановке она ложится
    в файл вне репозитория, при старте поднимается. Иначе правка кода посреди
    показа стирала план, и приложение бригады оставалось без смены.
    """
    _load_state()
    if ready.enabled():
        ready.warm_up(dataset_ids(), _next_id)
        # Утра «Живого дня» и «Имитации» для трёх стартов: первый сценарий не ждёт решателя.
        mornings.warm_up(dataset_ids())
    yield
    _save_state()
    _stop_pools()


def _stop_pools() -> None:
    """Закрыть пулы процессов решателя: иначе их рабочие переживают перезапуск.

    Так и было: каждый перезапуск по правке кода оставлял по четыре рабочих
    процесса портфеля, и к 19.09.2026 их накопилось 644 на 13 ГБ памяти —
    машина тормозила, приложение переставало отвечать.
    """
    from . import portfolio

    pools = list(getattr(portfolio, "_pools", {}).values())
    if getattr(portfolio, "_pool", None) is not None:
        pools.append(portfolio._pool)
    for pool in pools:
        workers = list(getattr(pool, "_processes", {}).values())
        pool.shutdown(wait=False, cancel_futures=True)
        for proc in workers:
            if proc.is_alive():
                proc.terminate()


STATE_PATH = Path.home() / ".bee-ltzp" / "api-state.json"
STATE_PLANS = 60


def _state_on() -> bool:
    if "pytest" in sys.modules and os.environ.get("BEE_KEEP_STATE") != "test":
        return False
    return settings.option("state_persist") is not False and os.environ.get("BEE_KEEP_STATE", "1") not in ("0", "false", "no")


def _save_state() -> None:
    """Память сервиса — в файл: последние планы, журналы, переписка, смены."""
    if not _state_on():
        return
    keep = list(PLANS)[-int(settings.option("state_keep_plans") or STATE_PLANS):]
    keep += [pid for pid in LATEST.values() if pid in PLANS and pid not in keep]
    state = {
        "plans": {pid: PLANS[pid].model_dump(mode="json") for pid in keep},
        "latest": {k: v for k, v in LATEST.items() if v in keep},
        "marks": {pid: [m.model_dump(mode="json") for m in MARKS.get(pid, [])] for pid in keep if MARKS.get(pid)},
        "responses": {pid: [r.model_dump(mode="json") for r in RESPONSES.get(pid, [])] for pid in keep if RESPONSES.get(pid)},
        "chats": {k: [m.model_dump(mode="json") for m in v] for k, v in CHATS.items()},
        "reports": {k: {r: rep.model_dump(mode="json") for r, rep in v.items()} for k, v in REPORTS.items()},
        "shifts": {k: [e.model_dump(mode="json") for e in v] for k, v in SHIFTS.items()},
        "queues": {k: [e.model_dump(mode="json") for e in v] for k, v in QUEUES.items()},
        "mainline": sorted(MAINLINE & set(keep)),
        "rules": settings.rules(),
    }
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        tmp.replace(STATE_PATH)
    except OSError:
        pass


def _load_state() -> None:
    """Поднять память сервиса после перезапуска; битый файл — начать с чистого."""
    global _counter, _msg_ids
    if not _state_on() or not STATE_PATH.exists():
        return
    try:
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        for pid, raw in state.get("plans", {}).items():
            PLANS[pid] = Plan(**raw)
        LATEST.update(state.get("latest", {}))
        for pid, rows in state.get("marks", {}).items():
            MARKS[pid] = [Mark(**r) for r in rows]
        for pid, rows in state.get("responses", {}).items():
            RESPONSES[pid] = [OfferResponse(**r) for r in rows]
        for key, rows in state.get("chats", {}).items():
            CHATS[key] = [crew_app.Message(**r) for r in rows]
        for key, rows in state.get("reports", {}).items():
            REPORTS[key] = {r: crew_app.Report(**rep) for r, rep in rows.items()}
        for key, rows in state.get("shifts", {}).items():
            SHIFTS[key] = [crew_app.ShiftEvent(**r) for r in rows]
        MAINLINE.update(state.get("mainline", []))
        for key, rows in state.get("queues", {}).items():
            QUEUES[key] = [Event(**r) for r in rows]
        saved = state.get("rules") or {}
        if saved.get("rules") or saved.get("version"):
            settings.set_rules(saved.get("rules"), saved.get("updated_at"), saved.get("version"))
    except (OSError, ValueError, TypeError) as err:
        print(f"Память сервиса не поднялась, начинаем с чистого: {err}")
        return
    # Номера планов и сообщений продолжаются, а не начинаются заново.
    top = max((int(pid[1:]) for pid in PLANS if pid[1:].isdigit()), default=0)
    _counter = count(top + 1)
    last_msg = max((m.id for rows in CHATS.values() for m in rows), default=0)
    _msg_ids = count(last_msg + 1)


app = FastAPI(title="bee-routing", description="Планировщик маршрутов выездных инженеров",
              lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(access.router)

# Тяжёлый расчёт (план, сравнение, имитация) занимает ядро на секунды, бюджет
# поиска — до минуты. Разом их идёт не больше BEE_HEAVY_SLOTS, лишний запрос
# сразу получает 429: иначе десяток анонимных «спланировать» кладёт сервер
# для всех (замер `bee_routing.loadtest`, 28.09.2026). Чтение не ограничено.
_heavy_slots = threading.BoundedSemaphore(int(os.environ.get("BEE_HEAVY_SLOTS", "3")))


def _heavy():
    if not _heavy_slots.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="Сервер занят расчётом, повторите через несколько секунд",
                            headers={"Retry-After": "5"})
    try:
        yield
    finally:
        _heavy_slots.release()


# План живёт в памяти процесса: прототип, базы у него нет.
PLANS: dict[str, Plan] = {}
# Журнал отметок бригад и ответов на предложения — по плану; новый план
# наследует журнал того, из которого вырос.
MARKS: dict[str, list[Mark]] = {}
RESPONSES: dict[str, list[OfferResponse]] = {}
_counter = count(1)


LATEST: dict[str, str] = {}
# Планы, которые были действующими: версии дня — они и выросшие из них варианты.
# Базовый план для сравнения и планы имитации версиями дня не считаются.
MAINLINE: set[str] = set()


def _with_risk(built: Plan) -> Plan:
    """Риск срыва окна у визитов и плана — на каждом плане, который уходит с сервера."""
    try:
        data = load_dataset(built.dataset_id)
    except FileNotFoundError:
        return built
    from .insertion import requests_of

    return risk.annotate(built, requests_of(data, built))


def _weights(built: Plan) -> dict[str, str]:
    """Масштаб аварий плана словами — под текущими настройками плана (`economy.weight_text`)."""
    from .economy import tariffs, weight_text
    from .insertion import requests_of

    conf = tariffs()
    out = {}
    for req in requests_of(load_dataset(built.dataset_id), built).values():
        line = weight_text(req, conf)
        if line:
            out[req.id] = line
    return out


def _role(raw: str | None) -> str | None:
    """Роль экрана из заголовка X-Bee-Role; незнакомая — как без роли."""
    role = (raw or "").strip().lower()
    return role if role in settings.ROLES else None


def _remember(built: Plan, parent: Plan | None = None, *, latest: bool = True) -> Plan:
    _with_risk(built)
    if not built.stock:
        # Первый план дня задаёт утренний запас устройств: маршрут плюс резерв из настроек.
        from . import stock

        try:
            with settings.use(built.settings):
                built.stock = stock.morning(built, load_dataset(built.dataset_id))
        except FileNotFoundError:
            pass
    try:
        # Подсказки и сводка, которые едут с каждым планом: точки ожидания и три числа порядка целей.
        from . import objective, standby

        with settings.use(built.settings):
            standby.annotate(built, load_dataset(built.dataset_id))
            built.objective = objective.summary(built)
            built.weights = _weights(built)
    except FileNotFoundError:
        pass
    PLANS[built.id] = built
    if parent is not None and built.parent_id is None and parent.id != built.id:
        built.parent_id = parent.id
    if parent is not None:
        MARKS[built.id] = list(MARKS.get(parent.id, []))
        RESPONSES[built.id] = list(RESPONSES.get(parent.id, []))
    if latest:
        # «Последний» ведётся по региону: план Югоцентра не подменяет день
        # бригадам Востока. Планы имитации сюда не попадают.
        LATEST[built.dataset_id] = built.id
        LATEST["*"] = built.id
        MAINLINE.add(built.id)
    _save_state()  # состояние дня пишется на каждой версии, а не только при остановке: падение его не теряет
    return built


def _plan_or_404(plan_id: str, dataset_id: str | None = None) -> Plan:
    if plan_id == "latest":
        key = dataset_id or "*"
        if key not in LATEST:
            raise HTTPException(status_code=404, detail="Планов ещё нет")
        return PLANS[LATEST[key]]
    base = PLANS.get(plan_id)
    if base is None:
        raise HTTPException(status_code=404, detail=f"План {plan_id} не найден")
    return base


def _next_id() -> str:
    """Следующий идентификатор плана."""
    return f"p{next(_counter)}"


@app.get("/health")
def health() -> dict:
    """Проверка живости сервиса."""
    return {"status": "ok", "datasets": dataset_ids()}


@app.get("/datasets")
def datasets() -> list[DatasetInfo]:
    """Список регионов с числом заявок и бригад."""
    return dataset_infos()


@app.post("/datasets/upload", dependencies=[Depends(_heavy)])
def upload(body: UploadRequest) -> dict:
    """Свой набор заявок: разобрать, положить рядом с регионами, вернуть сводку."""
    try:
        data = upload_from_text(body.filename, body.content, name=body.name, engineers=body.engineers)
    except UploadError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    upload_save(data)
    return upload_summary(data)


@app.get("/datasets/{dataset_id}")
def dataset(dataset_id: str) -> Dataset:
    """Регион целиком."""
    try:
        return load_dataset(dataset_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.post("/plan", dependencies=[Depends(_heavy)])
def plan(body: PlanRequest, x_bee_role: str | None = Header(default=None)) -> Plan:
    """Построить план решателем или базовым вариантом.

    Под расчёт ложатся общие правила дня (`settings.for_role`): от экрана
    диспетчера берётся только оперативное — ручной приоритет заявок.
    """
    try:
        data = load_dataset(body.dataset_id)
        matrices = load_matrices(body.dataset_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    from .crew_app import with_profiles

    body.settings = settings.for_role(body.settings, _role(x_bee_role))
    # Адрес старта, выбранный бригадой в приложении, входит в новый план —
    # и только в новый: пересчёт по событиям идёт с настройками плана.
    body.settings = with_profiles(body.dataset_id, body.settings)
    with settings.use(body.settings):
        start = body.start or settings.option("start") or "office"
        start = start if start in ("office", "home", "hybrid") else "office"
        if body.algorithm == "solver":
            budget = int(settings.option("time_limit_s") or 4)
            built = ready.get_or_build(body.dataset_id, start, settings.current(), budget, _next_id,
                                       fresh=body.fresh)
        else:
            built, _ = build_baseline(
                data, matrices, plan_id=_next_id(), algorithm="baseline", start=start
            )
            built.economy = summarize(built, data)
    return _remember(built, latest=body.remember_latest)


@app.get("/ready")
def ready_status() -> dict:
    """Готовые планы: ключи, бюджеты, замеры; и что считается прямо сейчас."""
    return ready.status()


@app.get("/settings")
def settings_schema() -> dict:
    """Форма настроек: группы полей с подписями, единицами и диапазонами, значения по умолчанию."""
    return {"schema": settings.SCHEMA, "defaults": settings.defaults()}


class RulesBody(BaseModel):
    """Тело PUT /rules: общие правила дня целиком, в форме настроек."""

    rules: dict = {}


@app.get("/rules")
def rules_get() -> dict:
    """Общие правила дня: что задал руководитель поверх допущений, версия и время правки."""
    return settings.rules()


@app.put("/rules")
def rules_put(body: RulesBody, x_bee_role: str | None = Header(default=None),
              x_bee_key: str | None = Header(default=None)) -> dict:
    """Заменить общие правила дня. Только экран руководителя: роль в заголовке `X-Bee-Role`.

    Входа у прототипа нет, и роль — это экран, а не учётная запись: заголовок
    отделяет экран диспетчера от экрана руководителя, но от того, кто пишет
    запросы руками, не защищает. На стенде для показа можно задать ключ
    `BEE_MANAGER_KEY` в окружении — тогда без заголовка `X-Bee-Key` с тем же
    ключом правила не меняются. В бою роль даёт вход через SSO заказчика.
    """
    if _role(x_bee_role) != "manager":
        raise HTTPException(status_code=403, detail="Общие правила дня задаёт руководитель — на своём экране")
    key = os.environ.get("BEE_MANAGER_KEY")
    if key and x_bee_key != key:
        raise HTTPException(status_code=403, detail="Ключ руководителя не подошёл")
    from datetime import UTC, datetime

    out = settings.set_rules(body.rules, datetime.now(UTC).isoformat(timespec="seconds"))
    _save_state()
    return out


@app.post("/compare", dependencies=[Depends(_heavy)])
def compare(body: CompareRequest, x_bee_role: str | None = Header(default=None)) -> dict:
    """Контрольное распределение, базовый вариант и наш план с настройками — показатели рядом."""
    body.settings = settings.for_role(body.settings, _role(x_bee_role))
    try:
        data = load_dataset(body.dataset_id)
        matrices = load_matrices(body.dataset_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    # Экран не ждёт минуту доводки: «наш план» берётся готовым (он доведён в фоне),
    # а строка «с запасом» считается быстро. Готового нет — быстрый расчёт без доводки.
    with settings.use(body.settings):
        start = str(settings.option("start") or "office")
    lying = ready.peek(body.dataset_id, start, body.settings) if ready.enabled() else None
    result: Comparison = run_compare(data, matrices, body.settings, ours=lying, lns_s=0)
    labels = [
        {"key": key, "label": label, "unit": unit, "less_is_better": less}
        for key, (label, unit, less) in KPI_LABELS.items()
    ]
    return {**result.model_dump(), "kpis": labels}


@app.get("/reports")
def reports() -> dict:
    """Отчёты о прогонах: сравнение с контролем, имитация дня, масштаб — из файлов `data/`."""
    return build_reports()


@app.get("/datasets/{dataset_id}/control")
def control(dataset_id: str) -> Plan:
    """Контрольное распределение заказчика как план — ориентир для сравнения."""
    try:
        data = load_dataset(dataset_id)
        matrices = load_matrices(dataset_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return _with_risk(control_plan(data, matrices))


@app.post("/plan/{plan_id}/assign")
def assign(plan_id: str, body: AssignRequest) -> Plan:
    """Ручная замена исполнителя или принятое предложение: заявка встаёт в маршрут бригады."""
    base = PLANS.get(plan_id)
    if base is None:
        raise HTTPException(status_code=404, detail=f"План {plan_id} не найден")
    data = load_dataset(base.dataset_id)
    matrices = load_matrices(base.dataset_id)
    with settings.use(base.settings):
        built, why = run_assign(
            base, data, matrices, body.request_id, body.engineer_id, body.insert_after,
            plan_id=_next_id(),
        )
    if built is None:
        raise HTTPException(status_code=409, detail=why)
    return _remember(built, base)


@app.post("/replan")
def replan(body: ReplanRequest) -> Plan:
    """Пересчитать план после события, заморозив уже начатые визиты."""
    base = PLANS.get(body.plan_id)
    if base is None:
        raise HTTPException(status_code=404, detail=f"План {body.plan_id} не найден")
    data = load_dataset(base.dataset_id)
    matrices = load_matrices(base.dataset_id)
    with settings.use(base.settings):
        built = run_replan(base, data, matrices, body.event, plan_id=_next_id())
    return _remember(built, base)


@app.post("/replan/variants", dependencies=[Depends(_heavy)])
def replan_variants(body: VariantsRequest) -> VariantsResponse:
    """Пачка событий → варианты ответа: сохранить порядок, перестроить, новое на завтра."""
    base = _plan_or_404(body.plan_id)
    data = load_dataset(base.dataset_id)
    matrices = load_matrices(base.dataset_id)
    found = run_variants(base, data, matrices, body.events, _next_id, body.keys)
    for item in found:
        _remember(item.plan, base, latest=False)
    return VariantsResponse(plan_id=base.id, variants=found)


@app.post("/plan/{plan_id}/adopt")
def adopt(plan_id: str) -> Plan:
    """Диспетчер принял вариант: он становится планом дня, и его видят бригады."""
    built = _plan_or_404(plan_id)
    return _remember(built)


@app.get("/plan/latest")
def latest_plan(dataset_id: str | None = None) -> Plan:
    """Последний план основной ветки дня — региона, если он назван, иначе любого."""
    return _plan_or_404("latest", dataset_id)


@app.get("/plan/{plan_id}/crew/{engineer_id}")
def crew(plan_id: str, engineer_id: str, dataset_id: str | None = None) -> CrewDay:
    """День бригады: маршрут, ближайший визит, предложения ей, заработок, её отметки."""
    base = _plan_or_404(plan_id, dataset_id)
    data = load_dataset(base.dataset_id)
    if engineer_id not in {eng.id for eng in data.engineers}:
        raise HTTPException(status_code=404, detail=f"Бригады {engineer_id} в регионе нет")
    with settings.use(base.settings):
        return crew_day(base, data, engineer_id, MARKS.get(base.id, []))


@app.get("/plan/{plan_id}/crew/{engineer_id}/transit")
def crew_transit(plan_id: str, engineer_id: str, request_id: str, dataset_id: str | None = None):
    """На чём ехать к заявке общественным транспортом: варианты пути и отправления по расписанию 2ГИС."""
    from .dgis import DgisError
    from .transit_trip import trip

    base = _plan_or_404(plan_id, dataset_id)
    data = load_dataset(base.dataset_id)
    try:
        with settings.use(base.settings):
            return trip(base, data, engineer_id, request_id)
    except KeyError as err:
        raise HTTPException(status_code=404, detail=str(err).strip("'\"")) from err
    except DgisError as err:
        raise HTTPException(status_code=502, detail=str(err)) from err


@app.post("/plan/{plan_id}/marks")
def add_mark(plan_id: str, body: MarkRequest) -> dict:
    """Отметка по визиту: в журнал и сразу через контроль."""
    base = _plan_or_404(plan_id)
    data = load_dataset(base.dataset_id)
    if body.mark.engineer_id not in {eng.id for eng in data.engineers}:
        raise HTTPException(status_code=404, detail=f"Бригады {body.mark.engineer_id} в регионе нет")
    known = {s.request_id for r in base.routes for s in r.stops} | {o.request_id for o in base.offers}
    if body.mark.request_id not in known:
        raise HTTPException(status_code=409, detail=f"Заявки {body.mark.request_id} нет в маршруте бригады и в предложениях")
    if any(m.kind == body.mark.kind and m.request_id == body.mark.request_id and m.engineer_id == body.mark.engineer_id
           for m in MARKS.get(base.id, [])):
        raise HTTPException(status_code=409, detail="Такая отметка по заявке уже есть")
    journal = MARKS.setdefault(base.id, [])
    journal.append(body.mark)
    _save_state()  # отметка бригады — часть состояния дня
    with settings.use(base.settings):
        flags = audit(base, data, journal, RESPONSES.get(base.id, []))
    return {"plan_id": base.id, "marks": journal, "flags": flags}


@app.get("/plan/{plan_id}/fraud")
def fraud(plan_id: str) -> dict:
    """Флаги контроля по журналу отметок плана."""
    base = _plan_or_404(plan_id)
    data = load_dataset(base.dataset_id)
    with settings.use(base.settings):
        flags = audit(base, data, MARKS.get(base.id, []), RESPONSES.get(base.id, []))
    return {"plan_id": base.id, "marks": MARKS.get(base.id, []), "flags": flags}


@app.post("/plan/{plan_id}/offers/respond")
def respond_offer(plan_id: str, body: RespondRequest) -> dict:
    """Бригада приняла или отклонила предложение: новый план и итог словами."""
    base = _plan_or_404(plan_id)
    data = load_dataset(base.dataset_id)
    matrices = load_matrices(base.dataset_id)
    with settings.use(base.settings):
        built, text = respond(base, data, matrices, body.response, plan_id=_next_id())
    if built.id != base.id:
        _remember(built, base)
    RESPONSES.setdefault(built.id, []).append(body.response)
    return {"plan": built, "text": text}


@app.post("/plan/{plan_id}/defer")
def defer(plan_id: str, body: DeferRequest) -> Plan:
    """Диспетчер переносит заявку на следующий день: из неназначенных в очередь с причиной."""
    base = _plan_or_404(plan_id)
    if not any(u.request_id == body.request_id for u in base.unassigned):
        raise HTTPException(status_code=409, detail=f"Заявка {body.request_id} не среди неназначенных")
    built = base.model_copy(deep=True)
    built.id = _next_id()
    built.unassigned = [u for u in built.unassigned if u.request_id != body.request_id]
    built.offers = [o for o in built.offers if o.request_id != body.request_id]
    built.metrics.unassigned = len(built.unassigned)
    built.deferred.append(Deferred(
        request_id=body.request_id, since=body.time or "00:00",
        reason=body.reason or "Перенесено диспетчером на следующий день: сегодня взять некому",
    ))
    return _remember(built, base)


@app.get("/plan/{plan_id}/deficit")
def deficit(plan_id: str, dataset_id: str | None = None) -> DeficitMap:
    """Карта дефицита по плану: где и в какие окна спрос выше мощности бригад."""
    base = _plan_or_404(plan_id, dataset_id)
    data = load_dataset(base.dataset_id)
    with settings.use(base.settings):
        return deficit_map(base, data)


class DeficitRequest(BaseModel):
    """Тело POST /deficit: план целиком — карта не зависит от памяти сервера."""

    plan: Plan


@app.post("/deficit")
def deficit_of_plan(body: DeficitRequest) -> DeficitMap:
    """Карта дефицита по присланному плану."""
    try:
        data = load_dataset(body.plan.dataset_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    with settings.use(body.plan.settings):
        return deficit_map(body.plan, data)


_geocoder: Geocoder | None = None


@app.get("/geocode")
def geocode(q: str, district: str = "") -> dict:
    """Координаты адреса для дома бригады: Nominatim с кэшем, только Москва и область."""
    global _geocoder
    if _geocoder is None:
        _geocoder = Geocoder()
    try:
        lat, lon, quality = _geocoder.locate(q, district)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    _geocoder.save()
    return {"q": q, "lat": lat, "lon": lon, "quality": quality}


@app.post("/simulate", dependencies=[Depends(_heavy)])
def simulate(body: ScenarioSpec, x_bee_role: str | None = Header(default=None)) -> SimulationResult:
    """Имитация дня: утренний план, события, статическое и динамическое правило рядом."""
    body.settings = settings.for_role(body.settings, _role(x_bee_role))
    try:
        data = load_dataset(body.dataset_id)
        matrices = load_matrices(body.dataset_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    result = run_simulate(data, matrices, body)
    for run in result.runs:
        _remember(run.plan, latest=False)
    return result


@app.get("/race")
def race() -> dict:
    """Гонка планов для экрана «Имитация»: контроль, базовый и наш на одних событиях — из `data/race/`."""
    from . import race as race_mod

    data = race_mod.load()
    if data is None:
        raise HTTPException(status_code=404, detail="Гонка не посчитана: uv run python -m bee_routing.race")
    return data


@app.post("/race/day", dependencies=[Depends(_heavy)])
def race_day(body: ScenarioSpec, x_bee_role: str | None = Header(default=None)) -> dict:
    """День по сценарию для «Живого дня»: контроль по правилу п. 2.3 и наш план на одних событиях."""
    from . import race as race_mod

    body.settings = settings.for_role(body.settings, _role(x_bee_role))
    if body.dataset_id not in dataset_ids():
        raise HTTPException(status_code=404, detail=f"Нет набора {body.dataset_id}")
    return race_mod.day(body.dataset_id, body)


class SetsQuery(BaseModel):
    """Какие наборы описать: участок, тип дня, старт бригад и настройки экрана."""

    dataset_id: str
    kind: str = Field(pattern="^(normal|hard)$")
    start: str = Field(default="office", pattern="^(office|hybrid|home)$")
    settings: dict | None = None


class CustomRaceQuery(BaseModel):
    """День «Имитации» со своими событиями: участок, старт бригад и события."""

    dataset_id: str
    start: str = Field(default="office", pattern="^(office|hybrid|home)$")
    custom: list[CustomEvent] = Field(min_length=1, max_length=12)


@app.post("/race/custom", dependencies=[Depends(_heavy)])
def race_custom(body: CustomRaceQuery) -> dict:
    """Прогон дня со своими событиями для «Имитации»: три плана, как у готовых дней гонки."""
    from . import race as race_mod

    if body.dataset_id not in dataset_ids():
        raise HTTPException(status_code=404, detail=f"Нет набора {body.dataset_id}")
    return race_mod.run_one(body.dataset_id, race_mod.CUSTOM_MODE, 0, body.start, body.custom)


class MorningQuery(BaseModel):
    """Чьё утро проверить: участок, старт, настройки экрана и бюджет поиска."""

    dataset_id: str
    start: str = Field(default="office", pattern="^(office|hybrid|home)$")
    settings: dict | None = None
    time_limit_s: int = Field(default=3, ge=1, le=10)


@app.post("/race/morning")
def race_morning(body: MorningQuery, x_bee_role: str | None = Header(default=None)) -> dict:
    """Посчитано ли утро сценария: экран предупреждает, что первый расчёт дольше."""
    from . import race as race_mod

    if body.dataset_id not in dataset_ids():
        raise HTTPException(status_code=404, detail=f"Нет набора {body.dataset_id}")
    overrides = settings.for_role(body.settings, _role(x_bee_role))
    return {"ready": race_mod.morning_ready(body.dataset_id, body.start, overrides, body.time_limit_s)}


# Лёгкий запрос (доля секунды): без очереди тяжёлых — иначе он ждёт, пока считается сам день.
@app.post("/race/sets")
def race_sets(body: SetsQuery, x_bee_role: str | None = Header(default=None)) -> list[dict]:
    """Что случится в каждом из двадцати наборов событий: время и вид события."""
    from . import race as race_mod

    if body.dataset_id not in dataset_ids():
        raise HTTPException(status_code=404, detail=f"Нет набора {body.dataset_id}")
    return race_mod.sets(body.dataset_id, body.kind, body.start, settings.for_role(body.settings, _role(x_bee_role)))


# ── Приложение бригады для показа ─────────────────────────────────────────

from . import crew_app

CHATS: dict[str, list[crew_app.Message]] = {}
REPORTS: dict[str, dict[str, crew_app.Report]] = {}
SHIFTS: dict[str, list[crew_app.ShiftEvent]] = {}
_msg_ids = count(1)


def _crew_key(dataset_id: str, engineer_id: str) -> tuple[str, Dataset]:
    try:
        data = load_dataset(dataset_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    if engineer_id not in {e.id for e in data.engineers}:
        raise HTTPException(status_code=404, detail=f"Бригады {engineer_id} в регионе нет")
    return f"{dataset_id}/{engineer_id}", data


def _post(key: str, message: crew_app.Message) -> crew_app.Message:
    CHATS.setdefault(key, []).append(message)
    return message


@app.get("/crew/{dataset_id}/{engineer_id}/profile")
def crew_profile(dataset_id: str, engineer_id: str) -> crew_app.CrewProfile:
    """Адреса бригады и откуда она начнёт следующий день."""
    _, data = _crew_key(dataset_id, engineer_id)
    return crew_app.get_profile(data, engineer_id)


@app.put("/crew/{dataset_id}/{engineer_id}/profile")
def crew_profile_save(dataset_id: str, engineer_id: str, body: crew_app.CrewProfile) -> crew_app.CrewProfile:
    """Сохранить адреса. Новый адрес старта войдёт в следующий план, сегодняшний не меняется."""
    _, data = _crew_key(dataset_id, engineer_id)
    body.engineer_id = engineer_id
    body.addresses = [a for a in body.addresses if 54 <= a.lat <= 57 and 35 <= a.lon <= 40][:8]
    return crew_app.save_profile(data, body, LATEST.get(dataset_id))


@app.get("/plan/{plan_id}/crew/{engineer_id}/ways")
def crew_ways(plan_id: str, engineer_id: str, request_id: str) -> crew_app.Ways:
    """Как доехать до заявки: своя машина, транспорт, каршеринг, самокат, велосипед, пешком."""
    base = _plan_or_404(plan_id)
    data = load_dataset(base.dataset_id)
    try:
        with settings.use(base.settings):
            return crew_app.ways(base, data, load_matrices(base.dataset_id), engineer_id, request_id)
    except (KeyError, StopIteration) as err:
        raise HTTPException(status_code=404, detail="Заявки нет в маршруте бригады") from err


@app.get("/crew/vehicles")
def crew_vehicles(lat: float, lon: float) -> list[crew_app.Vehicle]:
    """Синтетический прокат вокруг точки: демо, открытых данных у операторов нет."""
    return crew_app.vehicles_near((lat, lon))


class CallRequest(BaseModel):
    request_id: str


@app.post("/plan/{plan_id}/crew/{engineer_id}/call")
def crew_call(plan_id: str, engineer_id: str, body: CallRequest) -> crew_app.CallOut:
    """Подменный номер для звонка клиенту; в переписку ложится факт звонка, не номер."""
    base = _plan_or_404(plan_id)
    key, data = _crew_key(base.dataset_id, engineer_id)
    if body.request_id not in {r.id for r in data.requests}:
        raise HTTPException(status_code=404, detail="Заявки нет в регионе")
    out = crew_app.proxy_call(base, data, engineer_id, body.request_id)
    _post(key, crew_app.Message(id=next(_msg_ids), author="crew", kind="call", time=crew_app.now_clock(),
                                request_id=body.request_id, text="Звонок клиенту через подменный номер"))
    return out


@app.get("/crew/{dataset_id}/{engineer_id}/messages")
def crew_messages(dataset_id: str, engineer_id: str) -> list[crew_app.Message]:
    key, _ = _crew_key(dataset_id, engineer_id)
    return CHATS.get(key, [])


@app.post("/crew/{dataset_id}/{engineer_id}/messages")
def crew_message_post(dataset_id: str, engineer_id: str, body: crew_app.MessageIn) -> crew_app.Message:
    """Сообщение бригады диспетчеру или ответ диспетчера; «проблема» и SOS — те же сообщения с видом."""
    key, _ = _crew_key(dataset_id, engineer_id)
    author = body.author if body.author in ("crew", "dispatcher") else "crew"
    kind = body.kind if body.kind in ("text", "problem", "sos", "report") else "text"
    text = body.text.strip()[:500]
    if not text:
        raise HTTPException(status_code=422, detail="Пустое сообщение")
    return _post(key, crew_app.Message(id=next(_msg_ids), author=author, kind=kind, text=text,
                                       time=body.time or crew_app.now_clock(), request_id=body.request_id))


@app.post("/crew/{dataset_id}/{engineer_id}/messages/read")
def crew_messages_read(dataset_id: str, engineer_id: str, reader: str = "dispatcher") -> dict:
    """Прочитано: диспетчер читает сообщения бригады, бригада — диспетчера."""
    key, _ = _crew_key(dataset_id, engineer_id)
    other = "crew" if reader == "dispatcher" else "dispatcher"
    for message in CHATS.get(key, []):
        if message.author == other:
            message.read = True
    return {"ok": True}


@app.get("/crew/{dataset_id}/inbox")
def crew_inbox(dataset_id: str) -> dict:
    """Непрочитанное от бригад региона: число, последнее и есть ли SOS."""
    out = {}
    for key, messages in CHATS.items():
        region, _, engineer_id = key.partition("/")
        if region != dataset_id:
            continue
        unread = [m for m in messages if m.author == "crew" and not m.read and m.kind != "call"]
        if unread:
            out[engineer_id] = {"unread": len(unread), "last": unread[-1].model_dump(),
                                "sos": any(m.kind == "sos" for m in unread),
                                "problem": any(m.kind == "problem" for m in unread)}
    return out


@app.post("/crew/{dataset_id}/{engineer_id}/report")
def crew_report(dataset_id: str, engineer_id: str, body: crew_app.Report) -> crew_app.Report:
    """Отчёт по заявке: чек-лист, фото до и после, выданное оборудование, подпись клиента."""
    key, _ = _crew_key(dataset_id, engineer_id)
    REPORTS.setdefault(key, {})[body.request_id] = body
    return body


@app.get("/crew/{dataset_id}/{engineer_id}/reports")
def crew_reports(dataset_id: str, engineer_id: str) -> dict[str, crew_app.Report]:
    key, _ = _crew_key(dataset_id, engineer_id)
    return REPORTS.get(key, {})


@app.get("/crew/{dataset_id}/{engineer_id}/shift")
def crew_shift(dataset_id: str, engineer_id: str) -> list[crew_app.ShiftEvent]:
    key, _ = _crew_key(dataset_id, engineer_id)
    return SHIFTS.get(key, [])


@app.post("/crew/{dataset_id}/{engineer_id}/shift")
def crew_shift_post(dataset_id: str, engineer_id: str, body: crew_app.ShiftEvent) -> list[crew_app.ShiftEvent]:
    """Смена: начать, пауза, продолжить, завершить. Последовательность проверяется."""
    key, _ = _crew_key(dataset_id, engineer_id)
    events = SHIFTS.setdefault(key, [])
    state = events[-1].kind if events else None
    allowed = {None: {"start"}, "start": {"pause", "end"}, "resume": {"pause", "end"},
               "pause": {"resume", "end"}, "end": {"start"}}
    if body.kind not in allowed.get(state, set()):
        raise HTTPException(status_code=409, detail=f"Нельзя «{body.kind}» после «{state or 'ничего'}»")
    if body.kind == "start" and state == "end":
        events.clear()
    events.append(body)
    return events


@app.get("/crew/{dataset_id}/{engineer_id}/history")
def crew_history(dataset_id: str, engineer_id: str) -> crew_app.History:
    _, data = _crew_key(dataset_id, engineer_id)
    return crew_app.history(data, engineer_id)


@app.get("/route")
def route_line(profile: str, coords: str) -> dict:
    """Линия пути по улицам через OSRM; не ответил — прямыми, и об этом сказано."""
    import httpx

    from .geocode import load_assumptions

    points = []
    for pair in coords.split(";")[:25]:
        try:
            lon, lat = (float(x) for x in pair.split(","))
        except ValueError as err:
            raise HTTPException(status_code=422, detail="coords: lon,lat;lon,lat") from err
        points.append([lon, lat])
    if len(points) < 2:
        raise HTTPException(status_code=422, detail="Нужно две точки и больше")
    mode = {"transit": "foot", "scooter": "bike", "ebike": "bike", "carsharing": "car"}.get(profile, profile)
    conf = load_assumptions()["osrm"]
    if mode not in ("car", "bike", "foot"):
        mode = "car"
    url = (f"{conf[mode]}/route/v1/{conf['profile_path'][mode]}/"
           + ";".join(f"{p[0]:.6f},{p[1]:.6f}" for p in points)
           + "?overview=full&geometries=geojson")
    try:
        answer = httpx.get(url, timeout=5).json()
        line = answer["routes"][0]["geometry"]["coordinates"]
        return {"coordinates": line, "source": "osrm"}
    except (httpx.HTTPError, KeyError, IndexError, ValueError):
        return {"coordinates": points, "source": "straight"}


# ── Волна заявок, версии дня, сигнал «задерживаюсь», экран руководителя ────────

QUEUES: dict[str, list[Event]] = {}


class EventIn(BaseModel):
    plan_id: str
    event: Event


class FlushIn(BaseModel):
    dataset_id: str
    now: str | None = None


def _queue_view(dataset_id: str) -> dict:
    from . import wave

    queue = QUEUES.get(dataset_id, [])
    return {"queue": [e.model_dump(mode="json") for e in queue],
            "due": wave.due(queue[0].time) if queue else None, "window_min": wave.window()}


@app.post("/events")
def post_event(body: EventIn) -> dict:
    """Событие дня: срочное пересчитывается сразу, обычное ждёт границы отрезка волны (`wave.py`)."""
    from . import wave

    base = _plan_or_404(body.plan_id)
    with settings.use(base.settings):
        now = wave.window() <= 0 or wave.is_urgent(body.event)
    if now:
        data, matrices = load_dataset(base.dataset_id), load_matrices(base.dataset_id)
        with settings.use(base.settings):
            built = run_replan(base, data, matrices, body.event, plan_id=_next_id())
        return {"applied": True, "plan": _remember(built, base), **_queue_view(base.dataset_id)}
    QUEUES.setdefault(base.dataset_id, []).append(body.event)
    _save_state()
    with settings.use(base.settings):
        return {"applied": False, "plan": None, **_queue_view(base.dataset_id)}


@app.get("/events/queue")
def events_queue(dataset_id: str) -> dict:
    """Что ждёт ближайшей волны и когда она уйдёт в пересчёт."""
    base = _plan_or_404("latest", dataset_id)
    with settings.use(base.settings):
        return _queue_view(dataset_id)


@app.post("/events/flush")
def events_flush(body: FlushIn) -> dict:
    """Пересчитать волну: все события очереди одним заходом, минутой пересчёта."""
    from . import wave
    from .variants import _run

    base = _plan_or_404("latest", body.dataset_id)
    queue = QUEUES.get(body.dataset_id, [])
    if not queue:
        return {"applied": False, "plan": None, **_queue_view(body.dataset_id)}
    data, matrices = load_dataset(base.dataset_id), load_matrices(base.dataset_id)
    with settings.use(base.settings):
        moment = body.now or wave.due(queue[0].time)
        key = "full" if (settings.option("replan_mode") or "local") == "full" else "keep"
        built = _run(base, data, matrices, wave.stamp(queue, moment), key, _next_id)
    QUEUES[body.dataset_id] = []
    return {"applied": True, "plan": _remember(built, base), **_queue_view(body.dataset_id)}


@app.get("/day/{dataset_id}/versions")
def day_versions(dataset_id: str) -> list[dict]:
    """Версии плана дня: от первого плана до действующего, с событием, которое породило версию."""
    from . import objective

    current = LATEST.get(dataset_id)
    line, cursor = set(), current
    while cursor and cursor in PLANS and cursor not in line:
        line.add(cursor)
        cursor = PLANS[cursor].parent_id
    out = []
    shown: set[str] = set()
    for plan in PLANS.values():
        if plan.dataset_id != dataset_id or plan.id.startswith("sim-"):
            continue
        if plan.id not in MAINLINE and plan.id not in line and plan.parent_id not in shown:
            continue  # базовый план для сравнения — не версия дня
        shown.add(plan.id)
        last = plan.history[-1] if plan.history else None
        what = "Утренний план" if last is None else {
            "new_request": "Новая заявка", "urgent": "Авария", "cancel": "Отмена", "reschedule": "Перенос окна",
            "no_show": "Клиента нет", "delay": "Бригада задерживается", "engineer_off": "Бригада выбыла",
            "manual": "Ручная замена"}.get(last.type, last.type)
        with settings.use(plan.settings):
            numbers = plan.objective or objective.summary(plan)
        out.append({"id": plan.id, "parent_id": plan.parent_id, "created_at": plan.created_at,
                    "algorithm": plan.algorithm, "what": what, "time": last.time if last else None,
                    "events": len(plan.history), "unassigned": len(plan.unassigned), "deferred": len(plan.deferred),
                    "on_time": numbers.get("on_time"), "crews": numbers.get("crews"), "net_rub": numbers.get("net_rub"),
                    "current": plan.id == current, "on_line": plan.id in line})
    return out


@app.post("/plan/{plan_id}/restore")
def restore_version(plan_id: str) -> Plan:
    """Вернуть версию дня: она становится действующим планом региона, отметки бригад при ней свои."""
    return _remember(_plan_or_404(plan_id))


class DelayIn(BaseModel):
    minutes: int
    time: str | None = None
    request_id: str | None = None


@app.post("/plan/{plan_id}/crew/{engineer_id}/delay")
def crew_delay(plan_id: str, engineer_id: str, body: DelayIn) -> dict:
    """Сигнал бригады «задерживаюсь»: запись в переписку и, от порога из настроек, пересчёт хвоста её дня."""
    base = _plan_or_404(plan_id)
    key, data = _crew_key(base.dataset_id, engineer_id)
    minutes = max(1, min(int(body.minutes), 480))
    moment = body.time or crew_app.now_clock()
    with settings.use(base.settings):
        auto = settings.option("delay_auto_replan") is not False and minutes >= int(settings.option("delay_auto_min") or 0)
    _post(key, crew_app.Message(id=next(_msg_ids), author="crew", kind="delay", time=moment,
                                request_id=body.request_id, text=f"Задерживаюсь на {minutes} мин"))
    if not auto:
        _save_state()
        return {"replanned": False, "plan_id": base.id, "changed": 0,
                "text": "Диспетчер получил сигнал; план не менялся"}
    event = Event(id=f"delay-{engineer_id}-{moment}", type="delay", time=moment, engineer_id=engineer_id,
                  delay_min=minutes)
    with settings.use(base.settings):
        built = run_replan(base, data, load_matrices(base.dataset_id), event, plan_id=_next_id())
    _remember(built, base)
    changed = built.metrics.changed_requests
    dropped = len(built.unassigned) - len(base.unassigned)
    text = (f"Хвост дня пересчитан: сдвинуто визитов {changed}" + (f", ушло другим или в неназначенные {dropped}" if dropped > 0 else ""))
    _post(key, crew_app.Message(id=next(_msg_ids), author="dispatcher", kind="text", time=moment, text=text))
    return {"replanned": True, "plan_id": built.id, "changed": changed, "text": text}


@app.get("/manager/overview")
def manager_overview() -> dict:
    """Экран руководителя: регионы дня одной таблицей — цели, бригады, сигналы."""
    from . import objective
    from .fraud import audit as flags_of

    regions = []
    for dataset_id, plan_id in LATEST.items():
        if dataset_id == "*" or plan_id not in PLANS:
            continue
        plan = PLANS[plan_id]
        data = load_dataset(dataset_id)
        with settings.use(plan.settings):
            figures = run_kpis(plan, data)
            targets = {"on_time_pct": float(settings.option("manager_on_time_target_pct") or 0),
                       "utilization_pct": float(settings.option("manager_utilization_target_pct") or 0)}
            numbers = objective.summary(plan)
            marks = MARKS.get(plan.id, [])
            flags = flags_of(plan, data, marks, RESPONSES.get(plan.id, []))
        total = len([s for r in plan.routes for s in r.stops]) + len(plan.unassigned) + len(plan.deferred)
        done = {m.request_id for m in marks if m.kind == "done"}
        chats = {k.partition("/")[2]: v for k, v in CHATS.items() if k.startswith(dataset_id + "/")}
        crews = []
        for route in plan.routes:
            eng = next((e for e in data.engineers if e.id == route.engineer_id), None)
            mine = chats.get(route.engineer_id, [])
            crews.append({
                "id": route.engineer_id, "name": eng.name if eng else route.engineer_id,
                "visits": len(route.stops), "done": sum(1 for s in route.stops if s.request_id in done),
                "late": sum(1 for s in route.stops if s.late_min > 0), "norm_min": route.norm_min,
                "bonus_rub": route.bonus_rub, "km": route.distance_km,
                "flags": sum(1 for f in flags if f.engineer_id == route.engineer_id),
                "sos": any(m.kind == "sos" and not m.read for m in mine),
                "delays": sum(1 for m in mine if m.kind == "delay"),
            })
        on_time_pct = round(100 * numbers["on_time"] / total, 1) if total else 0.0
        regions.append({
            "dataset_id": dataset_id, "name": data.name, "date": data.date, "plan_id": plan.id,
            "requests": total, "on_time": numbers["on_time"], "on_time_pct": on_time_pct,
            "crews_used": numbers["crews"], "crews_total": len(data.engineers), "net_rub": numbers["net_rub"],
            "unassigned": len(plan.unassigned), "deferred": len(plan.deferred),
            "utilization_pct": figures.get("utilization_pct", 0), "distance_km": figures.get("distance_km", 0),
            "late": figures.get("late", 0), "events": len(plan.history), "queue": len(QUEUES.get(dataset_id, [])),
            "flags": len(flags), "versions": len(day_versions(dataset_id)),
            "targets": targets,
            "ok": {"on_time": on_time_pct >= targets["on_time_pct"],
                   "utilization": float(figures.get("utilization_pct", 0)) >= targets["utilization_pct"]},
            "crews": crews,
        })
    return {"regions": sorted(regions, key=lambda r: r["name"]), "order": objective.order()}



@app.get("/manager/dashboard")
def manager_dashboard(dataset_id: str = "moskva") -> dict:
    """Сводка руководителя: итоги, день по часам, нагрузка, бригады, экономика, сигналы — по одному плану.

    План — действующий у диспетчера; нет его — готовый утренний (`ready`), а если
    и его нет, строится тот же утренний план, что увидит диспетчер.
    """
    from .dashboard import dashboard

    try:
        data = load_dataset(dataset_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    with settings.use(None):
        start = str(settings.option("start") or "office")
        plan_id = LATEST.get(dataset_id)
        plan = PLANS.get(plan_id) if plan_id else None
        if plan is None:
            plan = ready.peek(dataset_id, start, None) or ready.get_or_build(
                dataset_id, start, None, int(settings.option("time_limit_s") or 4), _next_id)
    with settings.use(plan.settings):
        targets = {"on_time_pct": float(settings.option("manager_on_time_target_pct") or 0),
                   "utilization_pct": float(settings.option("manager_utilization_target_pct") or 0)}
        feed = crew_feed(dataset_id)["items"]
        return dashboard(plan, data, MARKS.get(plan.id, []), feed, targets, start)


@app.get("/crew/{dataset_id}/feed")
def crew_feed(dataset_id: str) -> dict:
    """Лента от бригад региона для диспетчера: сообщения, проблемы, SOS, задержки, звонки, вопросы контроля.

    Новое сверху. Непрочитанное — то, что бригада написала, а диспетчер ещё
    не открывал; вопросы контроля идут по действующему плану региона.
    """
    try:
        data = load_dataset(dataset_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    names = {e.id: e.name for e in data.engineers}
    items = []
    for key, messages in CHATS.items():
        region, _, engineer_id = key.partition("/")
        if region != dataset_id:
            continue
        for m in messages:
            items.append({"id": f"m{m.id}", "kind": m.kind, "author": m.author, "engineer_id": engineer_id,
                          "engineer": names.get(engineer_id, engineer_id), "time": m.time, "text": m.text,
                          "request_id": m.request_id, "unread": m.author == "crew" and not m.read and m.kind != "call"})
    plan_id = LATEST.get(dataset_id)
    if plan_id in PLANS:
        plan = PLANS[plan_id]
        with settings.use(plan.settings):
            flags = audit(plan, data, MARKS.get(plan.id, []), RESPONSES.get(plan.id, []))
        for i, f in enumerate(flags):
            items.append({"id": f"f{i}-{f.engineer_id}-{f.request_id}", "kind": "flag", "author": "control",
                          "engineer_id": f.engineer_id, "engineer": names.get(f.engineer_id, f.engineer_id),
                          "time": getattr(f, "time", None) or "", "text": f"{f.text}. {f.action}", "request_id": f.request_id,
                          "unread": False, "severity": f.severity})
    items.sort(key=lambda x: (x["time"] or "", x["id"]), reverse=True)
    urgent = sum(1 for x in items if x["unread"] and x["kind"] in ("sos", "problem", "delay"))
    return {"items": items[:200], "unread": sum(1 for x in items if x["unread"]), "urgent": urgent}
