"""Модели данных по контракту `app/CONTRACT.md`.

Время — строка «HH:MM» в пределах одних суток, длительность и дорога —
целые минуты, расстояние — километры с одним знаком. Имена полей
повторяют контракт знак в знак: клиент разбирает ответ по ним.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, model_validator


class Priority(str, Enum):
    """Приоритет заявки."""

    NORMAL = "normal"
    URGENT = "urgent"


class Skill(str, Enum):
    """Требуемый навык: локальные работы, подключения, аварии."""

    LOCAL = "local"
    CONNECT = "connect"
    EMERGENCY = "emergency"


class Transport(str, Enum):
    """Способ передвижения."""

    CAR = "car"
    FOOT = "foot"
    BIKE = "bike"
    TRANSIT = "transit"


class GeoQuality(str, Enum):
    """Точность геокодирования адреса."""

    HOUSE = "house"
    STREET = "street"
    DISTRICT = "district"


class Office(BaseModel):
    """Офис региона — стартовая точка всех бригад."""

    address: str
    lat: float
    lon: float


class Request(BaseModel):
    """Заявка на выезд."""

    id: str
    type_bk: str
    type_hd: str
    address: str
    district: str
    lat: float
    lon: float
    geo_quality: GeoQuality
    duration_min: int = Field(gt=0)
    window_start: str
    window_end: str
    priority: Priority = Priority.NORMAL
    skill: Skill
    transport: Transport | None = None
    equipment: list[str] = Field(
        default_factory=list,
        description="Устройства, которые везёт инженер: router | tv_box | speaker; синтетика по типу заявки",
    )
    segment: str | None = Field(
        default=None,
        description="Сегмент клиента аварии: KA | A | B | C | D — по ежемесячному счёту за связь; у прочих заявок нет. "
                    "В данных заказчика сегмента нет — синтетика от номера заявки (`segments.py`), если не указан в наборе",
    )
    sector: str | None = Field(
        default=None, description="Участок заявки в наборе из нескольких участков (`moscow.py`); в наборе участка — нет",
    )

    @model_validator(mode="after")
    def _segment(self) -> Request:
        """Сегмент аварии считается при загрузке заявки, а не лежит в датасете: пересборка не нужна."""
        if self.skill == Skill.EMERGENCY and self.segment is None:
            from .segments import estimate

            self.segment = estimate(self.id)
        return self


class Point(BaseModel):
    """Точка старта бригады."""

    lat: float
    lon: float
    address: str | None = Field(
        default=None, description="Подпись точки: ближайший дом с номером (`homes.py`); координаты — прежние",
    )


class Engineer(BaseModel):
    """Бригада и её смена."""

    id: str
    name: str
    start: Point
    shift_start: str
    shift_end: str
    skills: list[Skill] = Field(default_factory=list)
    home: Point | None = Field(default=None, description="Дом бригады: старт по практике")
    anchor: Point | None = Field(default=None, description="Опорная точка района дальней бригады: условный старт в её городе")
    anchor_name: str | None = None
    remote_km: float = Field(
        default=0.0,
        description="Медиана расстояния визитов бригады в контроле от офиса, км: удалённый подучасток",
    )
    extra_load: bool = Field(default=True, description="Готова брать заявки сверх нормы дня за бонус")
    extra_limit_min: int = Field(default=240, description="Предел нормо-минут сверх нормы за день")
    transport: Transport = Transport.CAR
    transports: list[Transport] = Field(
        default_factory=list,
        description="Все виды транспорта, доступные бригаде; вид на переезд выбирается из них",
    )
    sector: str | None = Field(
        default=None,
        description="Участок бригады в наборе из нескольких участков: её офис и «свой» участок; выезд в чужой "
                    "стоит `economy.sector_cross_rub`",
    )

    @model_validator(mode="after")
    def _fill_transports(self) -> Engineer:
        """`transport` — основной вид; набор по умолчанию состоит из него одного."""
        if not self.transports:
            self.transports = [self.transport]
        elif self.transport not in self.transports:
            self.transport = self.transports[0]
        return self


class Event(BaseModel):
    """Сценарное событие для демонстрации перепланирования."""

    id: str
    type: str = Field(
        description="urgent | cancel | engineer_off | new_request | reschedule | no_show | manual"
    )
    time: str
    request: Request | None = None
    request_id: str | None = None
    engineer_id: str | None = None
    window_start: str | None = Field(default=None, description="reschedule: новое окно клиента")
    window_end: str | None = None
    policy: str | None = Field(
        default=None, description="new_request: offer — предложить бригадам, direct — отдать лучшей"
    )
    delay_min: int | None = Field(default=None, description="delay: на сколько минут бригада задерживается")
    note: str | None = Field(
        default=None,
        description="no_show: waiting | unreachable | absent | partial | cancelled_on_site | client_moved | we_moved",
    )
    comment: str | None = Field(default=None, description="Комментарий диспетчера к событию: едет с ним в историю плана")


class ControlRow(BaseModel):
    """Строка контрольного распределения: кому заявку отдали в реальности."""

    request_id: str
    engineer_id: str
    status: str


class Sector(BaseModel):
    """Участок в наборе из нескольких участков: свой офис, свои бригады."""

    id: str
    name: str
    office: Office


class Dataset(BaseModel):
    """Регион на один день: офис, заявки, бригады, сценарии, контрольное распределение."""

    id: str
    name: str
    date: str
    office: Office
    sectors: list[Sector] = Field(
        default_factory=list,
        description="Участки набора «Вся Москва»: у каждого свой офис; у набора одного участка — пусто",
    )
    requests: list[Request] = Field(default_factory=list)
    engineers: list[Engineer] = Field(default_factory=list)
    events: list[Event] = Field(default_factory=list)
    control: list[ControlRow] = Field(default_factory=list)


class DatasetInfo(BaseModel):
    """Строка списка датасетов."""

    id: str
    name: str
    date: str
    requests_count: int
    engineers_count: int
    source: str = Field(default="customer", description="customer — данные заказчика; upload — свой файл")


class Stop(BaseModel):
    """Одна остановка маршрута."""

    request_id: str
    seq: int
    depart_prev: str
    arrive: str
    start: str
    end: str
    travel_min: int
    travel_km: float
    wait_min: int
    late_min: int
    mode: Transport | None = Field(default=None, description="Вид транспорта на этом переезде")
    geometry: list[list[float]] = Field(default_factory=list)
    status: str = Field(default="planned", description="planned | no_show — клиента не оказалось на месте")
    value_rub: int = Field(default=0, description="Ценность заявки по тарифам плана: для счётчика денег в показе дня")
    late_risk: float = Field(default=0.0, description="Доля прогонов со случайным шумом, где начало вышло за окно")
    arrive_p90: str | None = Field(default=None, description="Приезд, которого не превысят 90 % прогонов")


class Route(BaseModel):
    """Маршрут одной бригады."""

    engineer_id: str
    distance_km: float
    travel_min: int
    work_min: int
    stops: list[Stop] = Field(default_factory=list)
    break_start: str | None = Field(default=None, description="Обед: начало, если поставлен")
    break_end: str | None = None
    norm_min: int = Field(default=0, description="Выполнено нормо-минут: норматив с дорогой")
    over_norm_min: int = Field(default=0, description="Нормо-минут сверх нормы дня")
    bonus_rub: int = 0
    earnings_rub: int = 0


class Unassigned(BaseModel):
    """Заявка, которая не влезла в план, и причина по-русски."""

    request_id: str
    reason: str
    reason_code: str


class Deferred(BaseModel):
    """Заявка, явно перенесённая на следующий день: сегодня её некому взять."""

    request_id: str
    reason: str
    since: str = Field(description="Время события, после которого решили переносить")


class Check(BaseModel):
    """Одна проверка ограничения: навык, транспорт, окно, смена, дорога."""

    kind: str
    ok: bool
    text: str


class Alternative(BaseModel):
    """Другая бригада: взялась бы или нет и какой ценой."""

    engineer_id: str
    feasible: bool
    delta_km: float | None = None
    reason_code: str | None = None
    text: str


class Explanation(BaseModel):
    """Объяснение назначения одной заявки."""

    engineer_id: str
    checks: list[Check] = Field(default_factory=list)
    alternatives: list[Alternative] = Field(default_factory=list)


class Metrics(BaseModel):
    """Метрики плана."""

    engineers_used: int
    distance_km: float
    travel_min: int
    unassigned: int
    late: int
    changed_requests: int = 0
    risk_late: float = Field(default=0.0, description="Ожидаемое число визитов с началом позже окна при шуме дороги и работы")
    risky_stops: int = Field(default=0, description="Визитов с риском срыва окна не ниже порога")


class ChangedRequest(BaseModel):
    """Заявка, у которой после события сменился исполнитель или время."""

    request_id: str
    from_engineer: str | None = None
    to_engineer: str | None = None
    from_start: str | None = None
    to_start: str | None = None


class Diff(BaseModel):
    """Что изменилось после события."""

    event: Event
    changed_requests: list[ChangedRequest] = Field(default_factory=list)
    changed_routes: list[str] = Field(default_factory=list)
    frozen_requests: list[str] = Field(default_factory=list)


class Deficit(BaseModel):
    """Дефицит бригад в окне: спрос нормо-минут против предложения."""

    window: str
    demand_min: int
    capacity_min: int
    coef: float


class Economy(BaseModel):
    """Экономика плана в рублях."""

    value_done_rub: int
    value_lost_rub: int
    payroll_rub: int
    bonus_rub: int
    travel_rub: int
    wait_rub: int = Field(default=0, description="Ожидание у клиентов: минуты простоя по ставке минуты")
    sector_rub: int = Field(
        default=0, description="Выезды бригад в чужой участок по цене `economy.sector_cross_rub`: нерациональная логистика",
    )
    sector_entries: int = Field(default=0, description="Сколько раз бригады въезжали в чужой участок")
    total_cost_rub: int
    net_rub: int
    deficit: list[Deficit] = Field(default_factory=list)


class OfferCandidate(BaseModel):
    """Кому и за сколько предложить заявку сверх плана."""

    engineer_id: str
    insert_after: str | None = Field(default=None, description="id заявки, после которой встанет; null — первой")
    arrive: str
    start: str
    delta_travel_min: int
    delta_norm_min: int
    delta_shift_min: int = Field(default=0, description="На сколько позже сдвинется самый задетый следующий визит")
    bonus_rub: int
    text: str


class Offer(BaseModel):
    """Предложение по неназначенной заявке: кандидаты по цене вставки."""

    request_id: str
    coef: float
    candidates: list[OfferCandidate] = Field(default_factory=list)


class Standby(BaseModel):
    """Точка ожидания бригады в окне без визитов."""

    engineer_id: str
    after_request_id: str
    before_request_id: str | None = None
    start: str
    end: str
    lat: float
    lon: float
    district: str
    km: float = 0.0
    share_pct: int = Field(default=0, description="На сколько процентов переезд приближает свободные бригады к вероятным заявкам")
    text: str


class Plan(BaseModel):
    """Готовый план."""

    id: str
    dataset_id: str
    algorithm: str
    created_at: str
    start: str = Field(default="office", description="Откуда стартуют бригады: office | home | hybrid")
    settings: dict = Field(default_factory=dict, description="Переопределения, с которыми план посчитан")
    routes: list[Route] = Field(default_factory=list)
    unassigned: list[Unassigned] = Field(default_factory=list)
    metrics: Metrics
    explanations: dict[str, Explanation] = Field(default_factory=dict)
    diff: Diff | None = None
    economy: Economy | None = None
    offers: list[Offer] = Field(default_factory=list)
    deferred: list[Deferred] = Field(default_factory=list)
    history: list[Event] = Field(default_factory=list, description="События дня, по которым план пересчитан")
    day_type: str = Field(default="workday", description="Тип дня дороги: workday | friday | saturday | sunday | holiday")
    standby: list[Standby] = Field(default_factory=list, description="Где ждать бригадам в окнах без визитов")
    parent_id: str | None = Field(default=None, description="Версия дня, из которой выросла эта")
    objective: dict = Field(default_factory=dict, description="Порядок целей и три его числа: вовремя, бригады, итог")
    weights: dict[str, str] = Field(
        default_factory=dict,
        description="Сегмент и цена аварии словами: заявка → «Авария у клиента A (крупный, 250 000 ₽ в месяц): цена 620 000 ₽, восстановить за 2 ч»")
    stock: dict[str, dict[str, int]] = Field(
        default_factory=dict, description="Утренний запас устройств: бригада → устройство → штук; едет через пересчёты дня")
    timing: dict[str, float] = Field(
        default_factory=dict,
        description="Секунды расчёта: подготовка, первое решение, последнее улучшение, поиск, всего",
    )


class PlanRequest(BaseModel):
    """Тело POST /plan."""

    dataset_id: str
    algorithm: str = "baseline"
    start: str | None = Field(default=None, description="office — по регламенту, home — по практике")
    settings: dict | None = Field(default=None, description="Переопределения тарифов и правил из интерфейса")
    remember_latest: bool = Field(default=True, description="Считать этот план «последним» для приложения бригады")
    fresh: bool = Field(default=False, description="Считать заново, минуя готовый план по тем же настройкам")


class UploadRequest(BaseModel):
    """Тело POST /datasets/upload: свой набор заявок текстом файла."""

    # Границы — защита сервера: файл ложится на диск и геокодируется построчно.
    # 2 млн знаков — с запасом на 2000 заявок, самый большой замер масштаба.
    filename: str = Field(max_length=200, description="Имя файла: .csv — формат заказчика, .json — датасет по контракту")
    content: str = Field(max_length=2_000_000, description="Содержимое файла как текст")
    name: str | None = Field(default=None, max_length=80, description="Как назвать регион в списке")
    engineers: int | None = Field(default=None, ge=1, le=300, description="Сколько бригад завести, если в файле их нет")


class CompareRequest(BaseModel):
    """Тело POST /compare: регион и настройки, с которыми считать наш план."""

    dataset_id: str
    settings: dict | None = None


class PlanSummary(BaseModel):
    """Один план в сравнении: чей он и его показатели."""

    key: str
    label: str
    kpis: dict[str, float]


class Comparison(BaseModel):
    """Контрольное распределение, базовый вариант и наш план на одном регионе."""

    dataset_id: str
    rows: list[PlanSummary]


class AssignRequest(BaseModel):
    """Тело POST /plan/{id}/assign: ручная замена или принятое предложение."""

    request_id: str
    engineer_id: str
    insert_after: str | None = Field(default=None, description="после какой заявки; null — лучшее место")


class ReplanRequest(BaseModel):
    """Тело POST /replan."""

    plan_id: str
    event: Event


class VariantsRequest(BaseModel):
    """Тело POST /replan/variants: план и пачка событий, сохранённых диспетчером."""

    plan_id: str
    events: list[Event] = Field(min_length=1)
    keys: list[str] | None = Field(default=None, description="Какие варианты считать; пусто — все")


class VariantRequest(BaseModel):
    """Что стало с новой заявкой пачки в этом варианте."""

    request_id: str
    time: str
    outcome: str
    code: str = Field(description="assigned | offered | deferred")


class ReplanVariant(BaseModel):
    """Один ответ на пачку событий и его цена."""

    key: str = Field(description="keep | full | tomorrow")
    title: str
    hint: str
    plan: Plan
    placed: int = Field(description="Новых заявок пачки встало в маршруты сегодня")
    offered: int = Field(description="Новых заявок предложено бригадам, ждём ответа")
    deferred: int = Field(description="Новых заявок ушло на завтра")
    changed: int = Field(description="Визитов сдвинуто против плана до пачки")
    unassigned: int
    net_rub: int
    net_delta_rub: int
    same_as: str | None = Field(default=None, description="Вариант, который дал тот же план")
    requests: list[VariantRequest] = Field(default_factory=list)


class VariantsResponse(BaseModel):
    """Ответ POST /replan/variants."""

    plan_id: str
    variants: list[ReplanVariant]


# ── Приложение бригады, отметки визитов и контроль ──


class Mark(BaseModel):
    """Отметка бригады по визиту: выехала, прибыла, начала, закончила, клиента нет."""

    engineer_id: str
    request_id: str
    kind: str = Field(description="depart | arrive | start | done | no_show")
    time: str
    lat: float | None = None
    lon: float | None = None


class OfferResponse(BaseModel):
    """Ответ бригады на предложение: берёт или отказывается."""

    request_id: str
    engineer_id: str
    accepted: bool
    time: str = "00:00"
    reason: str | None = Field(default=None, description="Причина отказа словами бригады")


class Earnings(BaseModel):
    """Заработок бригады за день: оклад, бонус и норма — по плану и по подтверждённому."""

    day_rub: int
    bonus_planned_rub: int
    bonus_confirmed_rub: int
    norm_day_min: int
    norm_planned_min: int
    norm_confirmed_min: int
    over_norm_min: int


class CrewOffer(BaseModel):
    """Предложение, адресованное этой бригаде: что, куда, когда и за сколько."""

    request_id: str
    address: str
    window: str
    duration_min: int
    arrive: str
    delta_travel_min: int
    bonus_rub: int
    text: str
    expires_in_min: int


class CrewDay(BaseModel):
    """День бригады глазами её приложения."""

    plan_id: str
    engineer: Engineer
    route: Route
    requests: list[Request]
    marks: list[Mark] = Field(default_factory=list)
    offers: list[CrewOffer] = Field(default_factory=list)
    earnings: Earnings
    next_request_id: str | None = None
    kit: dict[str, int] = Field(default_factory=dict, description="Что взять утром: устройство → сколько")
    stock: dict[str, int] = Field(default_factory=dict, description="Утренний запас бригады: маршрут плюс резерв")
    stock_left: dict[str, int] = Field(default_factory=dict, description="Свободный остаток сверх стоящих визитов")


class FraudFlag(BaseModel):
    """Признак недобросовестности по отметкам: что заметили и что с этим делать."""

    engineer_id: str
    request_id: str | None
    code: str
    severity: str = Field(description="info | warn | alert")
    text: str
    action: str


class MarkRequest(BaseModel):
    """Тело POST /plan/{id}/marks."""

    mark: Mark


class DeferRequest(BaseModel):
    """Тело POST /plan/{id}/defer."""

    request_id: str
    reason: str | None = None
    time: str | None = None


class RespondRequest(BaseModel):
    """Тело POST /plan/{id}/offers/respond."""

    response: OfferResponse


# ── Имитация дня ──


class InjectedRequest(BaseModel):
    """Заявка, которую диспетчер вбросил в имитацию сам: когда позвонили, где и в какое окно."""

    time: str = Field(description="Во сколько позвонил клиент")
    lat: float
    lon: float
    address: str = "Точка на карте"
    duration_min: int = 60
    window_start: str
    window_end: str
    skill: str = "connect"


class CustomEvent(BaseModel):
    """Событие, которое задали руками: что, во сколько и с кем — без случайности."""

    type: str = Field(pattern="^(new_request|cancel|no_show|reschedule|delay|engineer_off)$")
    time: str = Field(pattern="^([01]\\d|2[0-3]):[0-5]\\d$", description="Во сколько случится")
    request_id: str | None = Field(
        default=None, description="cancel, no_show, reschedule — какая заявка; new_request — с чьего адреса звонок")
    engineer_id: str | None = Field(default=None, description="delay, engineer_off — какая бригада")
    delay_min: int = Field(default=30, ge=5, le=240, description="delay: на сколько минут")


class ScenarioSpec(BaseModel):
    """Что случится за день: сколько и каких событий, каким правилом отвечаем.

    Границы у счётчиков — защита сервера: сценарий на десять тысяч заявок
    держал ядро дольше двух минут (замер `bee_routing.loadtest`, 28.09.2026).
    """

    dataset_id: str
    seed: int = Field(default=1, ge=0, le=1_000_000)
    new_requests: int | None = Field(
        default=None, ge=0, le=60,
        description="Заявок день в день; не задано — доля региона из настройки intraday_share_pct")
    cancels: int = Field(default=2, ge=0, le=30)
    no_shows: int = Field(default=2, ge=0, le=30)
    reschedules: int = Field(default=1, ge=0, le=30)
    engineer_off: int = Field(default=0, ge=0, le=5)
    delays: int = Field(default=1, ge=0, le=30)
    policy: str = Field(default="offer", description="offer — предложить, direct — отдать, static — на завтра")
    accept_prob: float = Field(default=0.7, ge=0, le=1, description="Доля принятых предложений в имитации")
    settings: dict | None = None
    time_limit_s: int = Field(default=3, ge=1, le=10)
    injected: list[InjectedRequest] = Field(
        default_factory=list, max_length=20,
        description="Заявки, вброшенные руками: в свою минуту дня, поверх событий симулятора")
    custom: list[CustomEvent] = Field(
        default_factory=list, max_length=12, description="События, заданные руками, поверх остальных")
    events_from: str = Field(
        default="random", pattern="^(random|data)$",
        description="random — события по зерну и счётчикам; data — события, заложенные в набор участка")


class SimEvent(BaseModel):
    """Одно событие дня и что с ним стало."""

    time: str
    type: str
    request_id: str | None = None
    engineer_id: str | None = None
    outcome: str
    outcome_code: str = Field(description="assigned | offered | accepted | declined | deferred | removed | shifted")
    changed_requests: int = 0
    kpis: dict[str, float] = Field(default_factory=dict)


class SimulationRun(BaseModel):
    """Итог одной имитации: что было, чем кончилось."""

    policy: str
    timeline: list[SimEvent]
    kpis: dict[str, float]
    plan: Plan


class SimulationResult(BaseModel):
    """Имитация дня: динамический пересчёт против «всё новое — на завтра»."""

    spec: ScenarioSpec
    events: list[Event]
    runs: list[SimulationRun]
    kpi_labels: list[dict]


# ── Карта дефицита ──


class DeficitSlot(BaseModel):
    """Один район в одном окне: спрос, чем закрыт, сколько свободно рядом."""

    window: str
    demand_min: int = Field(description="Нормо-минуты заявок, чьё окно покрывает слот, поровну по слотам окна")
    served_min: int = Field(description="Нормо-минуты визитов района, начатых в этом слоте")
    free_min: int = Field(description="Свободные минуты бригад, которые в этом слоте рядом с районом")
    unassigned: int = Field(description="Неназначенных заявок района с этим окном")
    pressure: float = Field(description="Спрос к мощности: больше 1 — дефицит")
    level: str = Field(description="deficit | tight | ok | free")


class DeficitArea(BaseModel):
    """Район: где он, сколько заявок и как он чувствует себя по окнам."""

    district: str
    lat: float
    lon: float
    requests: int
    slots: list[DeficitSlot]


class DeficitAdvice(BaseModel):
    """Подсказка сервисному отделу: что делать с окном в районе."""

    district: str
    window: str
    level: str
    text: str


class DeficitMap(BaseModel):
    """Карта дефицита по плану: районы × окна и подсказки сервисным отделам."""

    plan_id: str
    windows: list[str]
    areas: list[DeficitArea]
    totals: list[DeficitSlot]
    advice: list[DeficitAdvice]
