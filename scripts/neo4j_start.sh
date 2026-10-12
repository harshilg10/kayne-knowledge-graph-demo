#!/usr/bin/env bash
# Starts the local Neo4j server (Homebrew install) and waits until it answers.
set -euo pipefail
NEO4J_BIN="${NEO4J_BIN:-$(command -v neo4j || echo /opt/homebrew/opt/neo4j/bin/neo4j)}"
if "$NEO4J_BIN" status >/dev/null 2>&1; then
  echo "Neo4j is already running."
else
  "$NEO4J_BIN" start
fi
for _ in $(seq 1 60); do
  if curl -s -o /dev/null http://localhost:7474; then
    echo "Neo4j is up - Browser: http://localhost:7474/browser/  (Bolt: bolt://localhost:7687)"
    exit 0
  fi
  sleep 2
done
echo "Neo4j did not become ready in time. Try: $NEO4J_BIN console" >&2
exit 1
