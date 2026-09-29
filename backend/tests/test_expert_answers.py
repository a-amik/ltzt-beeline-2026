"""Письменные ответы эксперта Билайна (п. 11—15): прототип работает так, как сказано.

Каждый тест — один ответ. Формулировки ответов — в листе «Сессия вопросов
и ответов», разд. «Письменные ответы Билайна».
"""

from collections import Counter

from bee_routing import settings
from bee_routing.baseline import start_point
from bee_routing.economy import request_value, skip_penalty, tariffs
from bee_routing.loadgen import EXPERT_MIX, kind_of, synthesize
from bee_routing.loader import load_dataset
from bee_routing.replan import default_policy
from bee_routing.solver import solve

from .conftest import REGIONS, needs_data

CONTROL_CREWS = {"vostok": 12, "yugo-vostok": 12, "yugocentr": 11}


@needs_data
def test_11_synthetic_mix_is_40_40_10_10():
    """Синтетика по долям Билайна: 40 % локальных, 40 % подключений, 10 % аварий, 10 % дозаказов."""
    for base in REGIONS:
        data = synthesize(base, 2000, 20, seed=3)
        kinds = Counter(kind_of(r) for r in data["requests"])
        for kind, share in EXPERT_MIX.items():
            got = kinds[kind] / len(data["requests"])
            assert abs(got - share) < 0.03, f"{base}: {kind} {got:.3f} против {share}"
    # Доли настоящего дня по-прежнему доступны.
    region = synthesize("yugocentr", 500, 5, seed=3, mix="region")
    assert not any(kind_of(r) == "accident" for r in region["requests"]), "у Югоцентра аварий нет"


@needs_data
def test_12_crews_match_control(region):
    """Число бригад — как в контрольном распределении: 12, 12 и 11."""
    data, _ = region
    import re

    base_id = re.sub(r"-\d{4}-\d{2}-\d{2}$", "", data.id)  # дополнительный день региона — те же бригады
    assert len(data.engineers) == CONTROL_CREWS[base_id]
    in_control = {c.engineer_id for c in data.control if c.engineer_id}
    assert {e.id for e in data.engineers} >= in_control


@needs_data
def test_13_remote_crews_start_in_their_town():
    """Кашира, Ступино и Домодедово: день начинается в своём городе даже при старте из офиса."""
    data = load_dataset("yugo-vostok")
    with settings.use({"options": {"start": "office", "zone_start": True}}):
        engineers = settings.effective_engineers(data.engineers)
        starts = {e.id: start_point(e, "office") for e in engineers}
    towns = {}
    for row in data.control:
        req = next((r for r in data.requests if r.id == row.request_id), None)
        if req is None or not row.engineer_id:
            continue
        town = req.address.split(",")[1].strip() if req.address.startswith("Московская") else "Москва"
        towns.setdefault(row.engineer_id, Counter())[town] += 1
    for eng in engineers:
        main_town = towns.get(eng.id, Counter({"Москва": 1})).most_common(1)[0][0]
        if main_town in ("Кашира", "Ступино", "Домодедово"):
            assert starts[eng.id] == f"home:{eng.id}", f"{eng.id} работает в {main_town}, а стартует из офиса"
        else:
            assert starts[eng.id] == "office", f"{eng.id} работает в Москве, а стартует не из офиса"
    remote = [e for e in engineers if starts[e.id] != "office"]
    assert len(remote) >= 3, "Домодедово теперь тоже подучасток"


@needs_data
def test_14_transit_is_used_by_crews_without_car():
    """Бригада без машины ездит общественным транспортом по усреднённому времени."""
    data = load_dataset("yugo-vostok")
    from bee_routing.loader import load_matrices

    matrices = load_matrices("yugo-vostok")
    with settings.use({"options": {"time_limit_s": 2, "portfolio": False}}):
        plan, _ = solve(data, matrices, plan_id="p14")
    modes = Counter(s.mode.value for r in plan.routes for s in r.stops if s.mode)
    assert modes["transit"] > 0, modes
    no_car = {e.id for e in data.engineers if "car" not in [t.value for t in e.transports]}
    assert no_car and all(
        s.mode.value != "car" for r in plan.routes if r.engineer_id in no_car for s in r.stops if s.mode
    )


@needs_data
def test_15_priority_order_in_prices(region):
    """Авария → подключение → ремонт / дозаказ: так стоят цены пропуска; «Информация» — не авария."""
    data, _ = region
    conf = tariffs()
    tiers = {}
    for req in data.requests:
        # Порядок держит цена пропуска целиком: мелкая авария (сегмент D, 2 800 ₽) дешевле
        # подключения, и выше его её ставит надбавка ступени (`priority_bonus_rub`).
        tiers.setdefault(kind_of(req.model_dump(mode="json")), set()).add(skip_penalty(req, conf))
    accident, connect = max(tiers.get("accident", {0})), min(tiers.get("connect", {10**9}))
    rest = tiers.get("local", set()) | tiers.get("upsell", set())
    assert not tiers.get("accident") or accident > connect
    assert connect > max(rest)
    for req in data.requests:
        if req.type_bk == "Глобальная проблема" and req.type_hd == "Информация":
            assert req.skill.value != "emergency"
            assert default_policy(req) == "offer", "информационный визит не встаёт директивно"
        if req.type_hd == "Авария":
            assert default_policy(req) == "direct", "авария среди дня ставится директивно"


STRICT = {"economy": {"priority_bonus_rub": {"emergency": 200000, "connect": 20000}}}
OFF = {"economy": {"priority_bonus_rub": {"emergency": 0, "connect": 0}}}


@needs_data
def test_15_priority_is_a_setting():
    """Приоритет задают настройки: с 22.09.2026 надбавка ступени включена по умолчанию.

    Решение команды после третьего повторения порядка организатором (18, 19 и 21.09.2026).
    Надбавку по-прежнему можно снять настройкой — тогда порядок задаёт одна ценность заявки.
    """
    from bee_routing.settings import SCHEMA

    data = load_dataset("yugo-vostok")
    accident = next(r for r in data.requests if r.skill.value == "emergency")
    with settings.use({}):
        assert skip_penalty(accident) == request_value(accident) + 200000, "надбавка включена по умолчанию"
    with settings.use(OFF):
        assert skip_penalty(accident) == request_value(accident), "надбавку можно снять настройкой"
    with settings.use(STRICT):
        assert skip_penalty(accident) == request_value(accident) + 200000
    paths = {f["path"] for g in SCHEMA for f in g["fields"]}
    assert {"economy.priority_bonus_rub.emergency", "economy.priority_bonus_rub.connect",
            "economy.emergency_segments.A.bill_rub", "economy.request_value_rub.upsell",
            "options.priority_order"} <= paths


@needs_data
def test_15_hard_ladder_puts_tier_above_money():
    """Жёсткий режим: авария не оценивается деньгами вовсе, ступени идут лесенкой.

    Одна заявка старшей ступени дороже тысячи заявок младшей, поэтому обменять
    аварию на ближние дешёвые заявки решатель не может ни при каком раскладе.
    Числа надбавок в этом режиме не участвуют.
    """
    from bee_routing.economy import skip_penalty, tariffs

    data = load_dataset("yugo-vostok")
    accident = next(r for r in data.requests if r.skill.value == "emergency")
    local = next(r for r in data.requests if r.skill.value == "local")
    hard = {"options": {"priority_order": "strict"}, **OFF}
    with settings.use(hard):
        conf = tariffs()
        cheap = min(int(v) for v in conf["request_value_rub"].values())
        assert skip_penalty(local, conf) == request_value(local, conf), "нижняя ступень без надбавки"
        assert skip_penalty(accident, conf) > 1000 * skip_penalty(local, conf), "авария дороже тысячи ремонтов"
        assert skip_penalty(accident, conf) == request_value(accident, conf) + cheap * 1000 ** 2


@needs_data
def test_15_scarcity_takes_accidents_then_connections():
    """Надбавка приоритета включена настройкой — порядок строгий: аварии, затем подключения, последними ремонт и дозаказ."""
    from bee_routing.loader import load_matrices

    data = load_dataset("yugo-vostok")
    matrices = load_matrices("yugo-vostok")
    full = [e for e in data.engineers if {s.value for s in e.skills} >= {"local", "connect", "emergency"}]
    few = data.model_copy(update={"engineers": full[:3]})
    with settings.use({**STRICT, "options": {"time_limit_s": 3, "portfolio": False, "start": "home"}}):
        plan, _ = solve(few, matrices, plan_id="p15")
    served = {s.request_id for r in plan.routes for s in r.stops}
    share = {}
    for kind in ("accident", "connect", "local", "upsell"):
        pool = [r for r in data.requests if kind_of(r.model_dump(mode="json")) == kind]
        if pool:
            share[kind] = sum(r.id in served for r in pool) / len(pool)
    # Ремонт и дозаказ — одна ступень, и считаются вместе: дозаказов четыре, и одна взятая
    # в просвет заявка давала бы «25 %» против 22 % у подключений.
    rest = [r for r in data.requests if kind_of(r.model_dump(mode="json")) in ("local", "upsell")]
    share["rest"] = sum(r.id in served for r in rest) / len(rest)
    assert share["accident"] >= share["connect"] >= share["rest"], share
    assert share["local"] < 1, "бригад должно не хватать, иначе проверять нечего"
