.PHONY: clean format install test

clean:
	rm -rf .venv
	rm -f actup.duckdb
	rm -rf build dist

format:
	uv run prek run --all-files

install:
	uv sync --extra=dev

test:
	uv run pytest \
		-c ./tests \
		--junitxml=coverage.xml \
		--cov-report=term-missing:skip-covered \
		--cov=src/actup/ \
		--numprocesses 5 \
		./tests
