.PHONY: setup gen test eval demo docs-check clean

PY := python

setup:
	$(PY) -m venv .venv
	.venv/Scripts/pip install -e .[dev]

gen:
	$(PY) scripts/gen.py

test:
	$(PY) -m pytest -q

eval:
	$(PY) -m evalharness.run

demo:
	$(PY) scripts/demo.py

docs-check:
	$(PY) scripts/docs_check.py

clean:
	rm -rf data eval/report.md .pytest_cache
