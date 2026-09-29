"""Пакет планировщика маршрутов выездных инженеров.

FastAPI-сервис принимает заявки (события) и инженеров, строит план
выездов через OR-Tools (VRP со временными окнами) и отдаёт назначения
с объяснением решения.
"""

from .api import app


def main() -> None:
    """Точка входа для `bee-routing-backend` — запуск uvicorn напрямую."""
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)


__all__ = ["app", "main"]
