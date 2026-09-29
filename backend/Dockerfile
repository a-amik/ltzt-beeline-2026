# Образ backend: Python 3.12 + uv.
# TODO: добавить .dockerignore при необходимости уменьшить контекст сборки.
FROM python:3.12-slim

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml uv.lock* ./
RUN uv sync --no-install-project

COPY . .
RUN uv sync

EXPOSE 8000
CMD ["uv", "run", "uvicorn", "bee_routing.api:app", "--host", "0.0.0.0", "--port", "8000"]
