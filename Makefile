PY := .venv/bin/python

.PHONY: setup neo4j-start neo4j-stop build build-claude app web test queries

setup:            ## create the virtualenv and install dependencies
	python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

neo4j-start:      ## start Neo4j and wait until it is ready
	scripts/neo4j_start.sh

neo4j-stop:
	scripts/neo4j_stop.sh

build:            ## structured data -> documents -> extraction -> Neo4j -> embeddings
	$(PY) -m kgdemo.build

build-claude:     ## same, extracting with Claude (needs ANTHROPIC_API_KEY)
	$(PY) -m kgdemo.build --engine claude

app:              ## run the demo app at http://localhost:8501
	$(PY) -m kgdemo.server

web:              ## rebuild the web UI (web/dist); needs Node.js
	cd web && npm install && npm run build

test:             ## run the test suite (expects a built graph)
	$(PY) -m pytest -q

queries:          ## regenerate the Neo4j Browser query pack
	$(PY) -m kgdemo.export_queries
