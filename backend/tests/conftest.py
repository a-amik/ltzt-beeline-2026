"""Общие приспособления тестов: собранные датасеты и матрицы."""

import os

import pytest

# Прогрев готовых планов при старте приложения тестам ни к чему: он занял бы
# все ядра на минуту, а планы тесты считают сами.
os.environ.setdefault("BEE_WARM_UP", "0")
os.environ.setdefault("BEE_REFINE_LNS_S", "0")  # фоновая минута LNS отнимала бы процессор у тестов с бюджетом в секунды

from bee_routing.loader import dataset_ids, load_dataset, load_matrices

# Регионы — наборы участков заказчика. «Вся Москва» (`moscow.py`) сложена из них,
# у неё свои проверки (`test_moscow.py`): тесты данных заказчика к ней не относятся.
REGIONS = [i for i in dataset_ids() if not load_dataset(i).sectors]
needs_data = pytest.mark.skipif(not REGIONS, reason="датасеты не собраны: python -m bee_routing.prepare")

from bee_routing.prepare import RAW_DIR

# Исходные CSV заказчика конфиденциальны и в публичный репозиторий не входят.
needs_raw = pytest.mark.skipif(not any(RAW_DIR.glob("*-zayavki.csv")), reason="нет исходных CSV в data/raw/")


@pytest.fixture(params=REGIONS or ["нет данных"])
def region(request):
    """Каждый регион по очереди: датасет и его матрицы."""
    if not REGIONS:
        pytest.skip("датасеты не собраны")
    return load_dataset(request.param), load_matrices(request.param)


@pytest.fixture(autouse=True)
def _fresh_api_state():
    """Словари API живут в памяти процесса: тест не должен видеть планы соседа."""
    from bee_routing import api, ready, settings

    settings.clear_rules()  # общие правила дня руководителя тоже живут в памяти процесса
    ready.clear()
    api.PLANS.clear()
    api.MARKS.clear()
    api.RESPONSES.clear()
    api.LATEST.clear()
    api.MAINLINE.clear()
    yield
