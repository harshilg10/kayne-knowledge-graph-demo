#!/usr/bin/env bash
# Stops the local Neo4j server.
set -euo pipefail
NEO4J_BIN="${NEO4J_BIN:-$(command -v neo4j || echo /opt/homebrew/opt/neo4j/bin/neo4j)}"
"$NEO4J_BIN" stop
