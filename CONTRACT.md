# Контракт данных: сервер ↔ клиент

Единицы: время `HH:MM` (день один), длительность и время в пути — минуты
(целые), расстояние — километры (float, 1 знак), координаты — широта/долгота
(float). Идентификаторы — строки. Справочники: навык `skill` ∈ `local`
(локальные работы), `connect` (подключение и дозаказы), `emergency`
(аварийные); транспорт `transport` ∈ `car`, `foot`, `bike`, `transit`;
приоритет `priority` ∈ `normal`, `urgent`. Имена полей — по словарю
Яндекс Маршрутизации там, где есть аналог.

## Dataset  `GET /datasets` → `[{id, name, date, requests_count, engineers_count}]`;  `GET /datasets/{id}` → Dataset

```json
{
  "id": "yugo-vostok", "name": "Юго-восток", "date": "2026-08-17",
  "office": {"address": "…", "lat": 55.596, "lon": 37.660},
  "requests": [{
    "id": "67472", "type_bk": "Подключение", "type_hd": "Конвергенция абонента",
    "address": "Домодедово, проезд Советский 1-й, 1А", "district": "Домодедово",
    "lat": 55.44, "lon": 37.76, "geo_quality": "house|street|district",
    "duration_min": 90, "window_start": "16:00", "window_end": "18:00",
    "priority": "normal", "skill": "connect", "transport": null,
    "households": null,               // у аварии — сколько квартир задето; синтетика от id, если не прислано
    "building": null                  // у аварии — private | lowrise | five | highrise
  }],
  "engineers": [{
    "id": "lebedev", "name": "Лебедев", "start": {"lat": 55.596, "lon": 37.660},
    "shift_start": "10:00", "shift_end": "22:00",
    "skills": ["connect", "local"],
    "transport": "car",                  // основной вид — первый в наборе
    "transports": ["car", "foot"]        // все виды, доступные бригаде; вид на переезд выбирается из них
  }],
  "events": [ Event, … ]          // готовые сценарии для демо
}
```

## Event
```json
{"id": "e1", "type": "urgent", "time": "14:00", "request": Request}      // срочная заявка, priority=urgent; ставится директивно
{"id": "e2", "type": "cancel", "time": "13:30", "request_id": "84466"}
{"id": "e3", "type": "engineer_off", "time": "13:00", "engineer_id": "lebedev"}
{"id": "e4", "type": "new_request", "time": "12:45", "request": Request, "policy": "offer"}   // заявка день в день; offer — предложить, direct — отдать лучшей
{"id": "e5", "type": "reschedule", "time": "11:25", "request_id": "40698", "window_start": "14:00", "window_end": "16:00"}
{"id": "e6", "type": "no_show", "time": "13:12", "request_id": "52041", "note": "unreachable"}  // note: waiting|unreachable|absent|partial|cancelled_on_site|client_moved|we_moved
{"id": "e7", "type": "delay", "time": "12:00", "engineer_id": "kozlov", "delay_min": 30}
```

Правила пересчёта (`options`): `replan_mode` — `local` (порядок визитов прежний, времена
новые, выпавшее и новое встаёт дешёвой вставкой; авария, не вставшая локально, добивается
полным пересчётом) или `full` (решатель ищет лучший план хвоста дня); `lock_horizon_min` —
визиты, до которых меньше стольких минут, не двигаются; `max_shift_min` и `max_advance_min` —
насколько позже и раньше обещанного может начаться остальное; `no_show_wait_min` — ожидание
у закрытой двери; `offer_timeout_min` — срок ответа бригады. Новая заявка, которую сегодня
никому не вставить, уходит в `deferred` с причиной словами.

## Plan  `POST /plan {dataset_id, algorithm: "solver"|"baseline", start: "office"|"home"}` → Plan;
## `POST /replan {plan_id, event: Event}` → Plan (с полем `diff`);
## `POST /plan/{id}/assign {request_id, engineer_id, insert_after?}` → Plan (с `diff`, event.type = "manual"; 409 с причиной словами, если не встаёт);
## `GET /datasets/{id}/control` → Plan с `algorithm: "control"` — распределение заказчика, порядок по окнам, дорога наша

## Приложение бригады и контроль
`GET /plan/latest` → последний план основной ветки дня (планы имитации сюда не попадают);
`GET /plan/{id}/crew/{engineer_id}` → `{plan_id, engineer, route, requests, marks, offers: [{request_id, address, window, duration_min, arrive, delta_travel_min, bonus_rub, text, expires_in_min}], earnings: {day_rub, bonus_planned_rub, bonus_confirmed_rub, norm_day_min, norm_planned_min, norm_confirmed_min, over_norm_min}, next_request_id}`;
`POST /plan/{id}/marks {mark: {engineer_id, request_id, kind: depart|arrive|start|done|no_show, time, lat?, lon?}}` → `{plan_id, marks, flags}`;
`GET /plan/{id}/fraud` → `{plan_id, marks, flags: [{engineer_id, request_id?, code: too_fast|far_from_address|overlap|idle_gap|teleport|no_show_streak|declines|low_load, severity: info|warn|alert, text, action}]}`;
`POST /plan/{id}/offers/respond {response: {request_id, engineer_id, accepted, reason?, time?}}` → `{plan, text}` —
принято: заявка в маршруте; отказ: предложение уходит следующему кандидату, отказались все — заявка в `deferred`.
Бонус по факту (`bonus_confirmed_rub`) считается только по визитам с отметкой `done`.

## Имитация дня  `POST /simulate {dataset_id, seed, new_requests, cancels, no_shows, reschedules, delays, engineer_off, policy: offer|direct|static, accept_prob, settings?, time_limit_s}` → `{spec, events: [Event], runs: [{policy, timeline: [{time, type, request_id?, engineer_id?, outcome, outcome_code, changed_requests, kpis}], kpis: {intraday_total, intraday_served, deferred, changed_total, on_time, late, unassigned, utilization_pct, distance_km, bonus_rub, net_rub, offers_sent, offers_accepted}, plan}], kpi_labels}`;
прогонов два: `static` (всё новое на завтра) и выбранное правило на тех же событиях.
CLI: `uv run python -m bee_routing.simulate <регион> --seed N --policy offer` → `data/simulation/`.

## Бригады, очередь и адреса
`settings.crews` — словарь «бригада → {home: {lat, lon, address?}, transports: [car|foot|bike|transit], extra_load}`;
принимается вместе с остальными настройками, применяется поверх датасета, дом вне матрицы считается запасной оценкой по прямой.
`POST /plan/{id}/defer {request_id, reason?, time?}` → Plan: неназначенная заявка уходит в `deferred`; 409, если она не среди неназначенных.
`GET /geocode?q=&district=` → `{q, lat, lon, quality: house|street|district}`; 404, если адрес не нашёлся в Москве и области.

Новые опции: `start` по умолчанию `home`; `portfolio` — четыре стартовые стратегии решателя параллельно
за тот же бюджет, лучший по выполненным, потом по итогу; `balance` и `economy.balance_rub_per_min` —
разброс нормо-минут между бригадами в цели; `hourly_traffic` — автомобиль по профилю часа из архива
«Яндекс Пробок» (`data/traffic-profile.json`) при пересчёте и вставке; решатель внутри поиска считает средний день.
Показатель сравнения `norm_spread_min` — разброс нагрузки между бригадами.

## Показ: карта дефицита
`POST /deficit {plan}` (или `GET /plan/{id}/deficit`) → `{plan_id, windows: ["10:00–12:00", …],
areas: [{district, lat, lon, requests, slots: [{window, demand_min, served_min, free_min, unassigned, pressure, level: deficit|tight|ok|free}]}],
totals: [то же по региону], advice: [{district, window, level, text}]}`. Спрос — нормо-минуты заявок района
с окном, покрывающим слот (заявка на весь день делится поровну); закрыто — визиты района, начатые в слоте;
свободно — минуты бригад, стоящих в слоте в 7 км от центра района, поровну между районами. Давление = спрос / (закрыто + свободно).
У остановки плана `value_rub` — ценность заявки по тарифам: по ней показ считает деньги к минуте дня.

## Правила дня  `GET /rules` → `{rules: {...как settings}, version, updated_at}`; `PUT /rules {rules}` — только с заголовком `X-Bee-Role: manager` (и `X-Bee-Key`, если на сервере задан `BEE_MANAGER_KEY`), иначе 403 с причиной словами. Правила ложатся под каждый расчёт (`/plan`, `/compare`, `/simulate`): с `X-Bee-Role: dispatcher` из присланных `settings` берутся только `requests` (ручной приоритет) и `options.time_limit_s`; без роли — присланное поверх правил (тесты, замер, скрипты).
## `Plan.weights` — `{request_id: "Авария: затронуто ≈240 квартир (многоэтажка), вес ×2,2"}` у каждой аварии плана, под настройками плана.
## Настройки  `GET /settings` → `{schema: [{key, title, fields: [{path, type: bool|number|choice|multi|time, label, hint?, unit?, min?, max?, step?, choices?}]}], defaults: {...}}`
## Сравнение  `POST /compare {dataset_id, settings?}` → `{dataset_id, rows: [{key: control|baseline|solver, label, kpis: {on_time, late, unassigned, engineers_used, travel_min, …, net_rub}}], kpis: [{key, label, unit, less_is_better}]}`

`POST /plan` принимает `settings` — вложенный словарь по путям схемы
(`{"options": {"breaks": false}, "economy": {"bonus_multiplier": 2}}`); незнакомые
ключи отбрасываются, числа обрезаются диапазоном схемы. План возвращает
проверенные переопределения в `settings`; `/replan` и `/assign` считают с ними же.

Экономика (`economy`), предложения (`offers`) и обед (`break_start`/`break_end` у маршрута)
считаются из тарифной таблицы `data/assumptions.json` → `economy`, `breaks`; все числа оценочные.

```json
"start": "office",                       // откуда стартовали бригады: office | home
"economy": {"value_done_rub": 318000, "value_lost_rub": 6000, "payroll_rub": 84000, "bonus_rub": 5400,
            "travel_rub": 9900, "total_cost_rub": 99300, "net_rub": 218700,
            "deficit": [{"window": "18:00–20:00", "demand_min": 990, "capacity_min": 1440, "coef": 1.0}]},
"deferred": [{"request_id": "n1", "reason": "Сегодня взять некому: … Заявка переносится на следующий день", "since": "12:45"}],
"history": [Event, …],                   // события дня, по которым план пересчитан
"offers": [{"request_id": "78876", "coef": 1.0, "candidates": [
   {"engineer_id": "kozlov", "insert_after": "20055", "arrive": "11:40", "start": "11:40",
    "delta_travel_min": 12, "delta_norm_min": 90, "delta_shift_min": 0, "bonus_rub": 1620,
    "text": "Дёмин: после заявки 20055, приезд 11:40, +12 мин дороги, бонус 1620 ₽ за 90 нормо-минут сверх нормы"}]}],
"routes": [{ …, "break_start": "13:40", "break_end": "14:10",
             "norm_min": 560, "over_norm_min": 80, "bonus_rub": 1440, "earnings_rub": 8440 }]
```

Инженер: `home {lat, lon}` — старт по практике; `extra_load` — готов брать сверх нормы дня за бонус;
`extra_limit_min` — предел сверх нормы. Датасет: `control: [{request_id, engineer_id, status}]`.

```json
{
  "id": "p1", "dataset_id": "yugo-vostok", "algorithm": "solver", "created_at": "…",
  "routes": [{
    "engineer_id": "lebedev", "distance_km": 41.2, "travel_min": 96, "work_min": 420,
    "stops": [{
      "request_id": "67472", "seq": 1,
      "depart_prev": "15:40", "arrive": "16:05", "start": "16:05", "end": "17:35",
      "travel_min": 25, "travel_km": 12.3, "wait_min": 0, "late_min": 0,
      "mode": "car",                       // чем ехали на этом переезде: car | foot | bike | transit
      "status": "planned",                 // planned | no_show — клиента не оказалось, время ожидания
      "geometry": [[lon, lat], …]          // ломаная по дорогам от предыдущей точки; может быть пустой
    }]
  }],
  "unassigned": [{"request_id": "31495", "reason": "Работа 120 мин не помещается в окно 20:00–22:00 ни у кого с учётом дороги", "reason_code": "no_fit_window"}],
  "metrics": {"engineers_used": 9, "distance_km": 312.4, "travel_min": 840, "unassigned": 1, "late": 0, "changed_requests": 0},
  "explanations": {
    "67472": {
      "engineer_id": "lebedev",
      "checks": [{"kind": "skill|transport|window|shift|distance", "ok": true, "text": "Навык «подключение и дозаказы» есть у бригады Лебедев"}],
      "alternatives": [{"engineer_id": "orlov", "feasible": true, "delta_km": 9.0, "text": "Орлов успевал, но добавил бы 9 км"},
                       {"engineer_id": "frolov", "feasible": false, "reason_code": "no_skill", "text": "У Фролова нет навыка «подключение и дозаказы»"}]
    }
  },
  "diff": {                                  // только у ответа /replan
    "event": Event,
    "changed_requests": [{"request_id": "14416", "from_engineer": "lebedev", "to_engineer": "orlov", "from_start": "16:20", "to_start": "16:50"}],
    "changed_routes": ["lebedev", "orlov"],
    "frozen_requests": ["66944", "23807"]     // начатые до времени события, не трогались
  }
}
```

Коды причин `reason_code`: `no_skill`, `no_transport`, `no_fit_window`,
`no_fit_shift`, `all_busy`, `no_engineer`, `offered` (предложена бригадам, ждём ответа). У каждого кода — шаблон фразы
на русском в `explain.py`; текст всегда приходит готовым, клиент его
не собирает.

## Остальные ручки: живой день, имитация, приложение бригады, руководитель

Выше — ядро: наборы, план, пересчёт, объяснения. Ниже — всё, что зовут
экраны сверх обязательного уровня. Ответы — те же модели `Plan`, `Event`,
`Request`; где ответ свой, он назван. Ручки с пометкой «тяжёлая» считают
план и ограничены очередью: пятый одновременный расчёт получает `429`.

| Ручка | Зачем | Ответ |
|---|---|---|
| `GET /health` | живость сервиса | `{status, datasets}` |
| `POST /datasets/upload` (тяжёлая) | свой файл заявок: разобрать, геокодировать, положить рядом с наборами | сводка набора: поля, восстановленные значения, адреса без координат |
| `GET /ready` | готовые утренние планы: ключи, бюджеты, замеры; что считается сейчас | `{ready: [...], running: [...]}` |
| `GET /settings` | форма настроек: группы полей с подписями, единицами, границами и значениями по умолчанию | `SCHEMA` из `settings.py` |
| `GET /rules`, `PUT /rules` | общие правила дня поверх допущений; менять может только экран руководителя (заголовок `X-Bee-Role: manager`) | `{rules, version, updated_at}` |
| `GET /reports` | отчёты прогонов из `data/`: сравнение с контролем, имитация, масштаб | markdown и json отчётов |
| `POST /replan/variants` (тяжёлая) | пачка событий → три варианта ответа: сохранить порядок, перестроить, перенести на завтра | `[{variant, plan, summary}]` |
| `POST /plan/{id}/adopt` | диспетчер принял вариант: он становится планом дня, бригады видят его | `Plan` |
| `GET /day/{dataset}/versions` | версии плана дня от первого до действующего, с событием-причиной | `[{plan_id, created_at, event}]` |
| `POST /plan/{id}/restore` | вернуть версию дня действующим планом | `Plan` |
| `POST /events` | событие дня: срочное пересчитывается сразу, обычное ждёт волны (`wave.py`) | `{applied, plan, queue, due, window_min}` |
| `GET /events/queue`, `POST /events/flush` | что ждёт ближайшей волны и когда она уйдёт; пересчитать волну сейчас | очередь; `Plan` |
| `GET /route` | линия пути по улицам через OSRM; OSRM молчит — прямые, и об этом сказано | `{coordinates, source: osrm \| straight}` |
| `POST /simulate` (тяжёлая) | имитация дня: утренний план, события, статическое и динамическое правило рядом | сводка прогона |
| `GET /race` | гонка трёх планов на одних событиях для экрана «Имитация» — из `data/race/` | готовые дни гонки |
| `POST /race/day`, `POST /race/custom` (тяжёлые) | день по сценарию для «Живого дня»; прогон со своими событиями | три плана и их показатели |
| `POST /race/morning`, `POST /race/sets` | посчитано ли утро сценария; что случится в каждом из наборов событий | `{ready}`; `[{time, kind}]` |
| `GET /plan/{id}/crew/{eng}/transit` | общественный транспорт к заявке: варианты пути и отправления по расписанию | варианты пути |
| `GET /plan/{id}/crew/{eng}/ways` | как доехать: своя машина, транспорт, каршеринг, самокат, велосипед, пешком | `[{mode, minutes, cost}]` |
| `GET /crew/vehicles` | прокат вокруг точки — синтетика для показа | `[{kind, lat, lon}]` |
| `GET`/`PUT /crew/{dataset}/{eng}/profile` | адреса бригады и старт следующего дня; новый адрес входит в следующий план | профиль |
| `GET`/`POST /crew/{dataset}/{eng}/messages`, `POST …/messages/read` | переписка бригады и диспетчера; «проблема» и SOS — те же сообщения с видом | `[{at, from, kind, text}]` |
| `GET /crew/{dataset}/inbox`, `GET /crew/{dataset}/feed` | непрочитанное от бригад; лента событий бригад для диспетчера | сводка; лента |
| `POST /plan/{id}/crew/{eng}/call` | подменный номер для звонка клиенту; в переписку ложится факт звонка | `{number}` |
| `POST /plan/{id}/crew/{eng}/delay` | «задерживаюсь»: запись и, от порога из настроек, пересчёт хвоста дня бригады | `{plan?: Plan}` |
| `POST /crew/{dataset}/{eng}/report`, `GET …/reports` | отчёт по заявке: чек-лист, фото, оборудование, подпись клиента | отчёты |
| `GET`/`POST /crew/{dataset}/{eng}/shift` | смена: начать, пауза, продолжить, завершить; порядок проверяется | состояние смены |
| `GET /crew/{dataset}/{eng}/history` | прошлые дни бригады | `History` из `crew_app.py` |
| `GET /manager/overview` | экран руководителя: регионы дня одной таблицей — цели, бригады, сигналы | таблица регионов |
| `GET /manager/dashboard` | сводка по одному плану: итоги, день по часам, нагрузка, экономика, сигналы | сводка |

Точные поля ответов — в моделях `models.py` и в самих обработчиках `api.py`;
у каждой ручки есть строка-описание, и этот список собран из них.

## Матрицы  (внутреннее, сервер)
`data/matrices/{dataset}-{profile}.json`: `{"ids": ["office", "67472", …],
"duration_min": [[…]], "distance_km": [[…]]}` для профилей `car`, `bike`,
`foot`; `transit` = `foot` со скоростью 18 км/ч плюс 8 минут ожидания
(допущение, описано в README).
