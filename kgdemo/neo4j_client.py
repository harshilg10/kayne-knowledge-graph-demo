"""Thin Neo4j access layer shared by the pipeline, tests and the app."""
from __future__ import annotations

from typing import Any

from neo4j import GraphDatabase, RoutingControl
from neo4j.graph import Node, Path, Relationship
from neo4j.time import Date, DateTime

from . import config

_driver = None


def driver():
    global _driver
    if _driver is None:
        _driver = GraphDatabase.driver(config.NEO4J_URI, auth=(config.NEO4J_USER, config.NEO4J_PASSWORD))
    return _driver


def close() -> None:
    global _driver
    if _driver is not None:
        _driver.close()
        _driver = None


def ping() -> dict:
    """Returns server version info; raises if Neo4j is unreachable."""
    records, _, _ = driver().execute_query(
        "CALL dbms.components() YIELD name, versions, edition RETURN name, versions[0] AS version, edition",
        database_=config.NEO4J_DATABASE, routing_=RoutingControl.READ)
    r = records[0]
    return {"name": r["name"], "version": r["version"], "edition": r["edition"]}


def run_records(query: str, params: dict | None = None, write: bool = False):
    records, _, _ = driver().execute_query(
        query, params or {}, database_=config.NEO4J_DATABASE,
        routing_=RoutingControl.WRITE if write else RoutingControl.READ)
    return records


def run(query: str, params: dict | None = None, write: bool = False) -> list[dict]:
    """Executes a query and returns plain Python dicts (nodes -> property dicts, dates -> ISO strings)."""
    return [{k: to_py(v) for k, v in r.items()} for r in run_records(query, params, write)]


def write(query: str, params: dict | None = None) -> list[dict]:
    return run(query, params, write=True)


def to_py(value: Any) -> Any:
    if isinstance(value, (Date, DateTime)):
        return value.iso_format()
    if isinstance(value, Node):
        props = {k: to_py(v) for k, v in value.items() if k != "embedding"}
        return {"_labels": sorted(value.labels), **props}
    if isinstance(value, Relationship):
        return {"_type": value.type, **{k: to_py(v) for k, v in value.items()}}
    if isinstance(value, Path):
        return [to_py(n) for n in value.nodes]
    if isinstance(value, list):
        return [to_py(v) for v in value]
    if isinstance(value, dict):
        return {k: to_py(v) for k, v in value.items()}
    return value


def records_to_graph(records) -> tuple[list[dict], list[dict]]:
    """Collects every node and relationship found in query results (including inside paths/lists)."""
    nodes: dict[str, dict] = {}
    edges: dict[str, dict] = {}

    def add_node(n: Node):
        if n.element_id not in nodes:
            props = {k: to_py(v) for k, v in n.items() if k not in ("embedding", "text")}
            nodes[n.element_id] = {"element_id": n.element_id, "labels": sorted(n.labels), "properties": props}

    def add_rel(r: Relationship):
        add_node(r.start_node)
        add_node(r.end_node)
        if r.element_id not in edges:
            edges[r.element_id] = {"element_id": r.element_id, "type": r.type,
                                   "source": r.start_node.element_id, "target": r.end_node.element_id,
                                   "properties": {k: to_py(v) for k, v in r.items()}}

    def visit(v):
        if isinstance(v, Node):
            add_node(v)
        elif isinstance(v, Relationship):
            add_rel(v)
        elif isinstance(v, Path):
            for n in v.nodes:
                add_node(n)
            for r in v.relationships:
                add_rel(r)
        elif isinstance(v, (list, tuple)):
            for x in v:
                visit(x)
        elif isinstance(v, dict):
            for x in v.values():
                visit(x)

    for record in records:
        for value in record.values():
            visit(value)
    return list(nodes.values()), list(edges.values())


def run_graph(query: str, params: dict | None = None) -> tuple[list[dict], list[dict]]:
    return records_to_graph(run_records(query, params))


def connect_nodes(nodes: list[dict], limit: int = 1000) -> list[dict]:
    """Relationships among the given nodes, like Neo4j Browser's "connect result nodes"."""
    ids = [n["element_id"] for n in nodes]
    if len(ids) < 2:
        return []
    records = run_records(
        "MATCH (a)-[r]->(b) WHERE elementId(a) IN $ids AND elementId(b) IN $ids RETURN r LIMIT $limit",
        {"ids": ids, "limit": limit})
    _, edges = records_to_graph(records)
    return edges
