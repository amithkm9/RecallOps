.PHONY: setup dev migrate test test-docker e2e build
setup:
	cd frontend && npm ci
	python3.12 -m venv backend/.venv
	backend/.venv/bin/python -m pip install -r backend/requirements.txt
migrate:
	backend/.venv/bin/alembic -c backend/alembic.ini upgrade head
dev:
	backend/.venv/bin/uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8080
build:
	cd frontend && npm run build
test:
	backend/.venv/bin/python scripts/test_database.py
	cd frontend && npm test
test-docker:
	docker compose run --rm -T --no-deps -v "$(CURDIR):/verify" app python /verify/scripts/container_tests.py
export RUN_BROWSER_TESTS BASE_URL BROWSER_ONLY INSTALL_TEST_BROWSER PLAYWRIGHT_BROWSERS_PATH
e2e:
	bash scripts/e2e.sh
