.PHONY: install api web dev scan test clean

install:
	uv pip install -e ".[dev]"
	cd web && pnpm install

api:
	.venv/bin/uvicorn src.api:app --host 127.0.0.1 --port 8000 --reload

web:
	cd web && pnpm dev

dev:
	@command -v concurrently >/dev/null 2>&1 || { echo "installing concurrently..."; cd web && pnpm add -D concurrently; }
	@cd web && pnpm exec concurrently -k \
		-n "api,web" -c "cyan,magenta" \
		"cd .. && .venv/bin/uvicorn src.api:app --host 127.0.0.1 --port 8000 --reload" \
		"pnpm dev"

scan:
	.venv/bin/python -m src.cli scan-cmd

test:
	.venv/bin/pytest -v

clean:
	rm -rf data/cache
	rm -rf .venv
	rm -rf web/.next web/node_modules
