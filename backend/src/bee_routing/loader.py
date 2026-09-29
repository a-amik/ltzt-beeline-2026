"""Загрузка готовых датасетов и матриц с диска.

Сырые CSV разбирает `prepare.py` — один раз, заранее. Сервису достаются
уже собранные `app/data/datasets/*.json` и `app/data/matrices/*.json`,
поэтому запуск API не зависит ни от сети, ни от OSRM.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from .geocode import DATA_DIR
from .matrices import MATRICES_DIR, Matrices
from .models import Dataset, DatasetInfo

DATASETS_DIR = DATA_DIR / "datasets"
# Синтетические регионы генератора нагрузки (`loadgen.py`) живут отдельно:
# в списке `/datasets` их нет, но по идентификатору они загружаются как свои.
SCALE_DIR = DATA_DIR / "scale"
SCALE_DATASETS_DIR = SCALE_DIR / "datasets"
SCALE_MATRICES_DIR = SCALE_DIR / "matrices"
# Свои файлы диспетчера (`upload.py`): в списке `/datasets` они есть, помечены
# источником upload, и переживают перезапуск сервиса; в git не входят.
UPLOAD_DIR = DATA_DIR / "uploads"
UPLOAD_DATASETS_DIR = UPLOAD_DIR / "datasets"
UPLOAD_MATRICES_DIR = UPLOAD_DIR / "matrices"


def dataset_ids(directory: Path | None = None) -> list[str]:
    """Идентификаторы собранных датасетов."""
    directory = directory or DATASETS_DIR
    if not directory.exists():
        return []
    return sorted(path.stem for path in directory.glob("*.json"))


def _dirs(dataset_id: str) -> tuple[Path, Path]:
    """Где лежит регион: данные заказчика, загруженный файл или синтетика нагрузки."""
    for datasets_dir, matrices_dir in (
        (DATASETS_DIR, MATRICES_DIR),
        (UPLOAD_DATASETS_DIR, UPLOAD_MATRICES_DIR),
        (SCALE_DATASETS_DIR, SCALE_MATRICES_DIR),
    ):
        if (datasets_dir / f"{dataset_id}.json").exists():
            return datasets_dir, matrices_dir
    return DATASETS_DIR, MATRICES_DIR


# Часть набора из нескольких участков: `moskva@vostok` — участок «Восток» набора «Вся Москва».
# Так её узнают процессы портфеля и фоновой доводки, которым передают только идентификатор.
PART = "@"


def sector_part(dataset: Dataset, sector_id: str) -> Dataset:
    """Один участок набора «Вся Москва»: свои заявки, свои бригады, свой офис; матрицы — общие."""
    sector = next(s for s in dataset.sectors if s.id == sector_id)
    return dataset.model_copy(update={
        "id": f"{dataset.id}{PART}{sector_id}",
        "sectors": [],
        "office": sector.office,
        "requests": [r for r in dataset.requests if r.sector == sector_id],
        "engineers": [e for e in dataset.engineers if e.sector == sector_id],
        "events": [e for e in dataset.events if e.request is None or e.request.sector == sector_id],
        "control": [c for c in dataset.control if any(e.id == c.engineer_id and e.sector == sector_id
                                                      for e in dataset.engineers)],
    })


@lru_cache(maxsize=16)
def load_dataset(dataset_id: str) -> Dataset:
    """Прочитать датасет региона."""
    if PART in dataset_id:
        base, sector_id = dataset_id.split(PART, 1)
        return sector_part(load_dataset(base), sector_id)
    path = _dirs(dataset_id)[0] / f"{dataset_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"Нет датасета {dataset_id}; сперва `python -m bee_routing.prepare`")
    return Dataset.model_validate_json(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=16)
def load_matrices(dataset_id: str) -> Matrices:
    """Прочитать матрицы региона и привязать к ним координаты его точек."""
    dataset_id = dataset_id.split(PART, 1)[0]  # у участка набора матрицы общие с набором
    matrices = Matrices.load(dataset_id, _dirs(dataset_id)[1])
    matrices.bind(load_dataset(dataset_id))
    return matrices


def dataset_infos() -> list[DatasetInfo]:
    """Список датасетов для витрины: регионы заказчика, затем загруженные файлы."""
    out = []
    for source, directory in (("customer", DATASETS_DIR), ("upload", UPLOAD_DATASETS_DIR)):
        for dataset_id in dataset_ids(directory):
            data = load_dataset(dataset_id)
            out.append(
                DatasetInfo(
                    id=data.id,
                    name=data.name,
                    date=data.date,
                    requests_count=len(data.requests),
                    engineers_count=len(data.engineers),
                    source=source,
                )
            )
    return out


def read_json(path: Path) -> dict:
    """Прочитать JSON-файл проекта."""
    return json.loads(path.read_text(encoding="utf-8"))
