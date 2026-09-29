.PHONY: setup dev-api dev-web test bench lint

setup: ## поставить зависимости backend и frontend
	cd backend && uv sync
	cd frontend && npm install

dev-api: ## поднять API в режиме разработки
	cd backend && uv run python main.py

dev-web: ## поднять фронтенд в режиме разработки
	cd frontend && npm run dev

test: ## прогнать тесты backend (сравнение с контролем — отдельно, make bench)
	cd backend && uv run pytest --ignore=tests/test_benchmark.py

bench: ## сравнение с контролем и базовым вариантом: в общем прогоне ему не хватает процессора
	cd backend && uv run pytest tests/test_benchmark.py

lint: ## проверить backend линтером
	cd backend && uv run ruff check .

