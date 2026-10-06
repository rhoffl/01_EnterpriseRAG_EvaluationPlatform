.PHONY: test lint up down
test:
	pytest -q
lint:
	ruff check packages services tests
up:
	cp -n .env.example .env || true
	docker compose up --build
down:
	docker compose down

