"""Web app server: a JSON API over the knowledge graph plus the compiled web UI (web/dist).

    .venv/bin/python -m kgdemo.server            # http://localhost:8501
    .venv/bin/python -m kgdemo.server --port 8600

The API mirrors the demo flow: source data -> semantic model -> unstructured to graph -> Cypher (with a hand-off
to Neo4j Browser) -> Graph-RAG -> business value. Everything is read-only except POST /api/extract/write, which MERGEs one document
and its extraction into Neo4j (pasted notes get a DOC-LIVE- id and disappear on the next build).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import re
import threading
import time
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config, queries, rag, viz
from . import neo4j_client as db
from . import world as w
from .ontology import load_ontology

WEB_DIST = config.ROOT / "web" / "dist"
DOC_TYPE_ORDER = ["Meeting Notes", "CRM Note", "Research Report", "Email", "IC Memo", "Due Diligence"]
SYSTEM_TABLES = {
    "CRM": ["clients.csv", "contacts.csv", "advisors.csv"],
    "Portfolio accounting": ["accounts.csv", "holdings.csv"],
    "Order management": ["transactions.csv"],
    "Security master": ["funds.csv", "fund_nav.csv", "companies.csv", "fund_holdings.csv", "company_themes.csv"],
    "HR directory": ["people.csv"],
    "IC decision log": ["ic_decisions.csv"],
}
TABLE_DESCRIPTIONS = {
    "clients.csv": "Client relationships: type, segment, risk profile, advisor",
    "contacts.csv": "Client contacts and external contacts at borrowers and advisers",
    "advisors.csv": "Wealth advisors and their offices",
    "accounts.csv": "Custodial accounts, registrations and model portfolios",
    "holdings.csv": "Positions as of the snapshot date: shares, NAV, market value, cost basis",
    "transactions.csv": "Trades and cash flows with trade and settlement dates",
    "funds.csv": "Fund reference data: ticker, strategy, benchmark, expense ratio, NAV",
    "fund_nav.csv": "Daily NAV pricing feed (quarterly marks for the private credit fund)",
    "companies.csv": "Security master: issuers and private borrowers",
    "fund_holdings.csv": "Fund look-through: company weights inside each fund",
    "company_themes.csv": "Research tagging: company exposure to each investment theme",
    "people.csv": "Firm employees, departments and committee seats",
    "ic_decisions.csv": "Investment Committee decision log",
}
SCHEMA_LAYOUT = {  # fixed positions for the ontology diagram
    "Committee": (-350, -255), "Meeting": (-110, -255), "Document": (155, -255), "Concept": (480, -255),
    "Advisor": (-480, -50), "Person": (-250, -95), "Theme": (335, -80),
    "Client": (-285, 95), "Fund": (0, 95), "Company": (270, 100),
    "Account": (-285, 280), "Transaction": (-40, 280), "Decision": (185, 280),
}
DOC_CONTEXT_QUERY = """MATCH (d:Document {id: $id})
CALL (d) {
  MATCH p = (d)-[:RECORDS|MENTIONS|ABOUT|PROPOSES|CITES|REFERENCES]->() RETURN p
  UNION
  MATCH p = (d)<-[:AUTHORED|SENT]-(:Person) RETURN p
  UNION
  MATCH p = (d)-[:RECORDS]->(:Meeting)<-[:ATTENDED]-(:Person) RETURN p
  UNION
  MATCH p = (d)-[:RECORDS]->(:Meeting)-[:HELD_BY]->(:Committee) RETURN p
  UNION
  MATCH p = (d)-[:MENTIONS]->(:Concept)-[:BROADER]->(:Theme) RETURN p
  UNION
  MATCH p = (d)-[:MENTIONS]->(:Company)<-[:INVESTED_IN]-(:Fund)<-[:OWNS]-(:Client {id: $client}) RETURN p
}
RETURN p LIMIT 150"""
UI_QUERIES = [  # the queries shown in the app (the full pack is in neo4j/demo_queries.cypher)
    ("brief-1-theme-documents", "From the brief"), ("brief-2-people-nvidia", "From the brief"),
    ("brief-3-investment-impact", "From the brief"), ("brief-sample-path", "From the brief"),
    ("client-theme-impact", "Beyond the brief"), ("look-through-exposure", "Beyond the brief"),
    ("hidden-nvidia-exposure", "Beyond the brief"), ("decision-implementation", "Beyond the brief"),
]

app = FastAPI(title="Knowledge Graph Demo", docs_url="/api/docs", openapi_url="/api/openapi.json")
_cache_lock = threading.Lock()
_cache: dict[str, tuple[float, Any]] = {}


# =============================================================================
# helpers
# =============================================================================
def _cached(key: str, ttl: float, fn):
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
    value = fn()
    with _cache_lock:
        _cache[key] = (now, value)
    return value


def _clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


def _graph(query: str, params: dict | None = None) -> dict:
    nodes, edges = db.run_graph(query, params or {})
    return viz.graph_payload(nodes, edges)


def _neo4j_status() -> dict:
    try:
        info = db.ping()
        nodes = db.run("MATCH (n) RETURN count(n) AS n")[0]["n"]
        rels = db.run("MATCH ()-[r]->() RETURN count(r) AS n")[0]["n"]
        return {"ok": True, **info, "nodes": nodes, "rels": rels}
    except Exception as exc:          # reported to the UI
        return {"ok": False, "error": str(exc)}


def _require_graph() -> None:
    status = _cached("status", 5, _neo4j_status)
    if not status["ok"]:
        raise HTTPException(503, "Neo4j is not reachable. Start it with scripts/neo4j_start.sh, then build the graph "
                                 f"with .venv/bin/python -m kgdemo.build. ({status['error']})")
    if status["nodes"] == 0:
        raise HTTPException(503, "Neo4j is running but the graph is empty. Build it with "
                                 ".venv/bin/python -m kgdemo.build.")


def _cypher_literal(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_cypher_literal(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{" + ", ".join(f"`{k}`: {_cypher_literal(v)}" for k, v in value.items()) + "}"
    return "'" + str(value).replace("\\", "\\\\").replace("'", "\\'") + "'"


def _inline_params(cypher: str, params: dict) -> str:
    """Cypher with parameters written in as literals, so it runs as-is in Neo4j Browser."""
    for name in sorted(params, key=len, reverse=True):
        literal = _cypher_literal(params[name])
        cypher = re.sub(rf"\${re.escape(name)}\b", lambda _m: literal, cypher)
    return cypher


def _caption_value(value: Any) -> Any:
    """Query results for tables: nodes become their name/title/id, lists are joined."""
    if isinstance(value, dict) and "_labels" in value:
        return value.get("name") or value.get("title") or value.get("id")
    if isinstance(value, list):
        return ", ".join(str(_caption_value(v)) for v in value)
    return value


@lru_cache(maxsize=1)
def _structured_tables() -> dict[str, dict]:
    tables = {}
    for path in sorted(config.STRUCTURED_DIR.glob("*.csv")):
        with path.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            rows = list(reader)
            tables[path.name] = {"columns": list(reader.fieldnames or []), "rows": rows}
    return tables


def _documents() -> dict[str, Any]:
    from .ingest import ingest_all

    def load():
        return {r.doc_id: r for r in ingest_all()}
    return _cached("documents", 3600, load)


def _doc_summary(r) -> dict:
    raw = config.ROOT / r.source_path.split("#")[0]
    return {"doc_id": r.doc_id, "doc_type": r.doc_type, "title": r.title, "date": r.date,
            "source_system": r.source_system, "source_path": r.source_path,
            "file_name": raw.name, "file_ext": raw.suffix.lstrip(".")}


# =============================================================================
# status + overview
# =============================================================================
@app.get("/api/status")
def status() -> dict:
    return {
        "neo4j": _cached("status", 5, _neo4j_status),
        "llm": {"available": config.llm_available(), "model": config.LLM_MODEL},
        "as_of": config.AS_OF_DATE.isoformat(),
        "firm": config.FIRM_NAME,
        "hero": {"client_id": config.HERO_CLIENT_ID, "client_name": w.client_by_id(config.HERO_CLIENT_ID)["name"],
                 "doc_id": config.HERO_DOC_ID, "theme": "AI Infrastructure"},
        "browser_url": config.NEO4J_BROWSER_URL,
        "neo4j_user": config.NEO4J_USER,
    }


@app.get("/api/overview")
def overview() -> dict:
    tables = _structured_tables()
    holdings = tables.get("holdings.csv", {"rows": []})["rows"]
    book = {
        "clients": len(tables.get("clients.csv", {"rows": []})["rows"]),
        "accounts": len(tables.get("accounts.csv", {"rows": []})["rows"]),
        "transactions": len(tables.get("transactions.csv", {"rows": []})["rows"]),
        "aum_usd": round(sum(float(h["market_value"]) for h in holdings), 2),
        "documents": len(_documents()),
    }
    graph: dict = {"ok": False}
    st = _cached("status", 5, _neo4j_status)
    if st["ok"] and st["nodes"]:
        labels = {r["label"]: r["n"] for r in db.run("MATCH (n) UNWIND labels(n) AS label RETURN label, count(*) AS n")}
        graph = {"ok": True, "labels": labels, "nodes": st["nodes"], "rels": st["rels"]}
    return {"book": book, "graph": graph}


# =============================================================================
# 1. source data
# =============================================================================
@app.get("/api/structured")
def structured() -> dict:
    tables = _structured_tables()
    systems = []
    for system, files in SYSTEM_TABLES.items():
        entries = [{"name": f, "rows": len(tables[f]["rows"]), "columns": tables[f]["columns"],
                    "description": TABLE_DESCRIPTIONS.get(f, "")} for f in files if f in tables]
        systems.append({"system": system, "tables": entries, "rows": sum(e["rows"] for e in entries)})
    return {"systems": systems, "hero_client": w.client_by_id(config.HERO_CLIENT_ID)["name"]}


@app.get("/api/structured/{name}")
def structured_table(name: str, hero: bool = False) -> dict:
    tables = _structured_tables()
    if name not in tables:
        raise HTTPException(404, f"no table {name}")
    table = tables[name]
    rows = table["rows"]
    if hero:
        hero_accounts = {a["id"] for a in tables["accounts.csv"]["rows"] if a["client_id"] == config.HERO_CLIENT_ID}
        if "client_id" in table["columns"]:
            rows = [r for r in rows if r["client_id"] == config.HERO_CLIENT_ID]
        elif "account_id" in table["columns"]:
            rows = [r for r in rows if r["account_id"] in hero_accounts]
        elif name == "clients.csv":
            rows = [r for r in rows if r["id"] == config.HERO_CLIENT_ID]
    return {"name": name, "columns": table["columns"], "rows": rows, "total": len(table["rows"]),
            "filtered": hero and len(rows) != len(table["rows"])}


@app.get("/api/documents")
def documents() -> dict:
    docs = sorted(_documents().values(), key=lambda r: (r.date, r.doc_id), reverse=True)
    counts = {t: sum(1 for d in docs if d.doc_type == t) for t in DOC_TYPE_ORDER}
    return {"types": DOC_TYPE_ORDER, "counts": counts, "documents": [_doc_summary(d) for d in docs],
            "hero_doc_id": config.HERO_DOC_ID}


@app.get("/api/documents/{doc_id}")
def document(doc_id: str) -> dict:
    record = _documents().get(doc_id)
    if record is None:
        if doc_id.startswith("DOC-LIVE-"):
            rows = db.run("MATCH (d:Document {id: $id}) RETURN d.id AS id, d.title AS title, d.doc_type AS type, "
                          "toString(d.date) AS date, d.source_system AS system, d.text AS text", {"id": doc_id})
            if rows:
                r = rows[0]
                return {"doc_id": r["id"], "doc_type": r["type"], "title": r["title"], "date": r["date"],
                        "source_system": r["system"], "source_path": "pasted in the app", "file_name": "",
                        "file_ext": "", "text": r["text"], "body_offset": 0, "metadata": {}}
        raise HTTPException(404, f"no document {doc_id}")
    return {**_doc_summary(record), "text": record.text, "body_offset": record.body_offset,
            "metadata": record.metadata}


@app.get("/api/documents/{doc_id}/original")
def document_original(doc_id: str):
    record = _documents().get(doc_id)
    if record is None:
        raise HTTPException(404, f"no document {doc_id}")
    path = (config.ROOT / record.source_path.split("#")[0]).resolve()
    if not path.is_file() or config.UNSTRUCTURED_DIR.resolve() not in path.parents:
        raise HTTPException(404, "original file not found")
    return FileResponse(path, filename=path.name)


@app.get("/api/documents/{doc_id}/graph")
def document_graph(doc_id: str) -> dict:
    _require_graph()
    params = {"id": doc_id, "client": config.HERO_CLIENT_ID}
    return {**_graph(DOC_CONTEXT_QUERY, params), "browser_cypher": _inline_params(DOC_CONTEXT_QUERY, params)}


# =============================================================================
# 2. semantic model
# =============================================================================
@app.get("/api/model")
def model() -> dict:
    onto = load_ontology()
    entities = [e for e in onto.entities.values() if not e.technical and e.label in SCHEMA_LAYOUT]
    labels = {e.label for e in entities}
    nodes = [{"id": e.label, "label": e.label, "labels": [e.label], "caption": e.display_name,
              "properties": {"description": e.description},
              "position": {"x": SCHEMA_LAYOUT[e.label][0], "y": SCHEMA_LAYOUT[e.label][1]}} for e in entities]
    edges = [{"id": f"{a}-{r.type}-{b}", "source": a, "target": b, "type": r.type,
              "properties": {"origin": r.origin, "description": r.description}, "inferred": r.origin == "derived"}
             for r in onto.relationships.values() if not r.technical
             for a in r.from_labels for b in r.to_labels if a in labels and b in labels]
    themes = []
    for t in onto.themes.values():
        themes.append({"id": t.id, "name": t.name, "definition": t.definition, "synonyms": list(t.synonyms),
                       "concepts": [{"name": onto.concepts[c].name, "synonyms": list(onto.concepts[c].synonyms)}
                                    for c in t.concept_ids]})
    return {"schema": {"nodes": nodes, "edges": edges}, "themes": themes}


@app.get("/api/model/keyword-vs-semantic")
def keyword_vs_semantic() -> dict:
    _require_graph()
    q = queries.by_id("keyword-vs-semantic")
    rows = db.run(q.cypher, q.params)
    keyword_total = db.run("CALL db.index.fulltext.queryNodes('documentText', $p) YIELD node RETURN count(node) AS n",
                           {"p": q.params["phrase"]})[0]["n"]
    missed = [{"doc_id": r["doc_id"], "date": r.get("date", ""), "title": r["title"], "type": r["type"],
               "via": r["matched_via_concepts"]} for r in rows if not r["found_by_keyword"]]
    return {"phrase": q.params["phrase"].strip('"'), "keyword_total": keyword_total, "semantic_total": len(rows),
            "missed_total": len(missed), "missed": missed, "cypher": q.cypher}


# =============================================================================
# 3. unstructured -> graph
# =============================================================================
class ExtractRequest(BaseModel):
    doc_id: str | None = None
    text: str | None = Field(default=None, max_length=20000)
    engine: str = "rules"


def _record_for(req: ExtractRequest):
    from .ingest import parse_meeting_notes
    if req.text is not None:
        doc_id = "DOC-LIVE-" + hashlib.sha1(req.text.encode()).hexdigest()[:8].upper()
        try:
            return parse_meeting_notes(req.text, doc_id, "pasted")
        except Exception as exc:
            raise HTTPException(422, f"Could not parse the note: {exc}")
    record = _documents().get(req.doc_id or "")
    if record is None:
        raise HTTPException(404, f"no document {req.doc_id}")
    return record


def _run_extraction(req: ExtractRequest):
    from .extraction import build_title_index, extract_record
    if req.engine not in ("rules", "claude"):
        raise HTTPException(422, "engine must be 'rules' or 'claude'")
    if req.engine == "claude" and not config.llm_available():
        raise HTTPException(422, "Claude is not configured (ANTHROPIC_API_KEY)")
    record = _record_for(req)
    index = _cached("title-index", 3600, lambda: build_title_index(list(_documents().values())))
    return record, extract_record(record, engine=req.engine, title_index=index)


@app.get("/api/extract/sources")
def extract_sources() -> dict:
    docs = sorted(_documents().values(), key=lambda r: (DOC_TYPE_ORDER.index(r.doc_type), r.date))
    hero = _documents().get(config.HERO_DOC_ID)
    return {"documents": [_doc_summary(d) for d in docs], "default_doc_id": config.HERO_DOC_ID,
            "paste_sample": hero.text if hero else "", "engines": (["claude"] if config.llm_available() else [])
            + ["rules"], "llm_model": config.LLM_MODEL}


@app.post("/api/extract")
def extract(req: ExtractRequest) -> dict:
    record, ex = _run_extraction(req)
    names = {e.key: e for e in ex.entities}
    doc_key = f"Document:{ex.doc_id}"
    title = ex.document.get("title", ex.doc_id)

    def name_of(key: str) -> str:
        if key == doc_key:
            return f"Document ({title[:40]})"
        e = names.get(key)
        return f"{e.name} ({e.label})" if e else key

    nodes = [{"id": doc_key, "label": "Document", "labels": ["Document"],
              "caption": viz.caption_for("Document", {"title": title, "doc_type": record.doc_type}),
              "properties": {"id": ex.doc_id, "title": title, "doc_type": record.doc_type}}]
    for e in ex.entities:
        nodes.append({"id": e.key, "label": e.label, "labels": [e.label], "caption": viz.short(e.name),
                      "properties": {"id": e.id, "name": e.name, "identified by": e.origin,
                                     "found as": ", ".join(dict.fromkeys(e.mentions)) or "-"}})
    keys = {n["id"] for n in nodes}
    edges = [{"id": f"r{i}", "source": r.source, "target": r.target, "type": r.type,
              "properties": {"evidence": r.evidence, "method": r.method, **r.properties},
              "inferred": bool(r.properties.get("inferred"))}
             for i, r in enumerate(ex.relationships) if r.source in keys and r.target in keys]
    how = {"header": "document structure", "text": "text mention", "inferred": "semantic model inference"}
    return {
        "doc_id": ex.doc_id, "engine": ex.engine, "warnings": ex.warnings,
        "record": {"doc_id": record.doc_id, "title": record.title, "doc_type": record.doc_type, "date": record.date,
                   "text": record.text, "body_offset": record.body_offset},
        "entities": [{"key": e.key, "label": e.label, "id": e.id, "name": e.name,
                      "identified_by": how.get(e.origin, e.origin), "mentions": list(dict.fromkeys(e.mentions)),
                      "spans": e.spans} for e in ex.entities],
        "relationships": [{"source": name_of(r.source), "type": r.type, "target": name_of(r.target),
                           "evidence": r.evidence, "inferred": bool(r.properties.get("inferred")),
                           "via": r.properties.get("via")} for r in ex.relationships],
        "graph": {"nodes": nodes, "edges": edges},
        "in_graph": bool(_cached("status", 5, _neo4j_status)["ok"]
                         and db.run("MATCH (d:Document {id: $id}) RETURN count(d) AS n", {"id": ex.doc_id})[0]["n"]),
    }


@app.post("/api/extract/write")
def extract_write(req: ExtractRequest) -> dict:
    from .graph_load import load_documents, load_extractions
    _require_graph()
    record, ex = _run_extraction(req)
    load_documents([record])
    result = load_extractions([ex])
    _clear_cache()
    return {"doc_id": record.doc_id, "relationships": result.get("relationships", {}),
            "warnings": result.get("warnings", [])}


# =============================================================================
# 5. queries
# =============================================================================
@app.get("/api/queries")
def query_list() -> dict:
    out = []
    for qid, group in UI_QUERIES:
        q = queries.by_id(qid)
        out.append({"id": q.id, "title": q.title.replace(" (from the brief)", ""), "question": q.question,
                    "cypher": q.cypher, "params": q.params, "shows": q.shows, "group": group,
                    "browser_cypher": _inline_params(q.graph_cypher or q.cypher, q.params)})
    return {"queries": out, "browser_url": config.NEO4J_BROWSER_URL}


class QueryRun(BaseModel):
    params: dict[str, str] = Field(default_factory=dict)


@app.post("/api/queries/{query_id}/run")
def query_run(query_id: str, body: QueryRun) -> dict:
    _require_graph()
    if query_id not in dict(UI_QUERIES):
        raise HTTPException(404, f"no query {query_id}")
    q = queries.by_id(query_id)
    params = {k: body.params.get(k, str(v)) for k, v in q.params.items()}
    out: dict = {"id": q.id, "params": params}
    t0 = time.perf_counter()
    try:
        if q.shows in ("table", "both"):
            rows = [{k: _caption_value(v) for k, v in r.items()} for r in db.run(q.cypher, params)]
            out["columns"] = list(rows[0]) if rows else []
            out["rows"] = rows
        if q.shows in ("graph", "both"):
            nodes, edges = db.run_graph(q.graph_cypher or q.cypher, params)
            if nodes and not edges:
                edges = db.connect_nodes(nodes)           # like Neo4j Browser's "connect result nodes"
            out["graph"] = viz.graph_payload(nodes, edges)
    except Exception as exc:
        raise HTTPException(400, f"Query failed: {exc}")
    out["ms"] = round(1000 * (time.perf_counter() - t0))
    return out


# =============================================================================
# 6. Graph-RAG
# =============================================================================
class RagRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    use_llm: bool = False


def _rag_payload(res: rag.RagResult) -> dict:
    d = asdict(res)
    d["graph"] = viz.graph_payload(res.nodes, res.edges) if res.nodes else {"nodes": [], "edges": []}
    d.pop("nodes"), d.pop("edges")
    d["queries"] = [{**q, "browser_cypher": _inline_params(q["cypher"], q["params"])} for q in d["queries"]]
    for c in d["chunks"]:
        c.pop("embedding", None)
    return d


@app.get("/api/rag/presets")
def rag_presets() -> dict:
    return {"questions": rag.PRESET_QUESTIONS, "llm": {"available": config.llm_available(), "model": config.LLM_MODEL},
            "strategy_labels": rag.STRATEGY_LABELS}


@app.post("/api/rag")
def rag_compare(req: RagRequest) -> dict:
    _require_graph()
    use_llm = req.use_llm and config.llm_available()
    std = rag.standard_rag(req.question, use_llm=use_llm)
    gr = rag.graph_rag(req.question, use_llm=use_llm)
    items = rag.key_facts(gr)
    cov_std, cov_gr = rag.coverage(items, std.context), rag.coverage(items, gr.context)
    return {
        "standard": _rag_payload(std),
        "graph": _rag_payload(gr),
        "strategy_label": rag.STRATEGY_LABELS.get(gr.strategy, gr.strategy),
        "coverage": {"items": [{"label": it["label"], "standard": a, "graph": b}
                               for it, a, b in zip(items, cov_std, cov_gr)],
                     "standard": sum(cov_std), "graph": sum(cov_gr), "total": len(items)},
    }


# =============================================================================
# 7. business value
# =============================================================================
def _value_proof() -> dict:
    q = queries.by_id("keyword-vs-semantic")
    rows = db.run(q.cypher, q.params)
    proof: dict = {"missed": sum(1 for r in rows if not r["found_by_keyword"]), "semantic": len(rows)}
    proof["systems"] = db.run("MATCH (d:Document) RETURN count(DISTINCT d.source_system) AS n")[0]["n"]
    proof["docs"] = db.run("MATCH (d:Document) WHERE NOT d.id STARTS WITH 'DOC-LIVE' RETURN count(d) AS n")[0]["n"]
    experts = queries.by_id("theme-experts")
    proof["experts"] = [r["person"] for r in db.run(experts.cypher, experts.params)][:3]
    ev_q = queries.by_id("evidence")
    ev = db.run(ev_q.cypher, ev_q.params)
    hero = [r for r in ev if r["source_document"] == config.HERO_DOC_ID]
    proof["evidence"] = (hero or ev or [None])[0]
    std = rag.standard_rag(rag.PRESET_QUESTIONS[0], use_llm=False)
    gr = rag.graph_rag(rag.PRESET_QUESTIONS[0], use_llm=False)
    items = rag.key_facts(gr)
    proof["coverage"] = {"standard": sum(rag.coverage(items, std.context)),
                         "graph": sum(rag.coverage(items, gr.context)), "total": len(items)}
    return proof


@app.get("/api/value")
def value() -> dict:
    _require_graph()
    proof = _cached("value", 300, _value_proof)
    ev = proof["evidence"]
    cov = proof["coverage"]
    return {"cards": [
        {"title": "Better discovery", "claim": "Find what keyword search misses.",
         "proof": f"{proof['missed']} of {proof['semantic']} AI Infrastructure documents never use the phrase - the "
                  "semantic model found them through concepts like GPU capacity and liquid cooling."},
        {"title": "Explainability", "claim": "Show why an answer was returned.",
         "proof": (f"“{ev['evidence'][:110]}” - {ev['source_document']}, {ev['meeting']} ({ev['date']})"
                   if ev else "Every relationship keeps its source document and sentence.")},
        {"title": "Data integration", "claim": "Connect CRM, documents, market data and operational systems.",
         "proof": f"CRM, portfolio accounting, order management, the security master and the IC decision log, plus "
                  f"{proof['docs']} documents from {proof['systems']} content systems - one model, linked by shared "
                  "identities."},
        {"title": "AI readiness", "claim": "Grounding for Copilot and Graph-RAG.",
         "proof": f"For the Hartwell question, Graph-RAG put {cov['graph']}/{cov['total']} key facts in front of the "
                  f"LLM; vector search found {cov['standard']}/{cov['total']}. Every fact carries a citation an "
                  "advisor can verify."},
        {"title": "Institutional knowledge", "claim": "Preserve relationships between people, decisions and content.",
         "proof": f"Who knows AI Infrastructure best: {', '.join(proof['experts']) or '-'} - inferred from what they "
                  "wrote and discussed."},
    ]}


# =============================================================================
# web UI (compiled single-page app)
# =============================================================================
@app.get("/api/{path:path}", include_in_schema=False)
def api_not_found(path: str):
    return JSONResponse({"detail": f"no endpoint /api/{path}"}, status_code=404)


if (WEB_DIST / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    index = WEB_DIST / "index.html"
    if not index.is_file():
        return JSONResponse({"detail": "The web UI is not built. Run: cd web && npm install && npm run build"},
                            status_code=503)
    candidate = (WEB_DIST / path).resolve()
    if path and candidate.is_file() and WEB_DIST.resolve() in candidate.parents:
        return FileResponse(candidate)
    return FileResponse(index, headers={"Cache-Control": "no-cache"})


def main(argv: list[str] | None = None) -> int:
    import uvicorn
    parser = argparse.ArgumentParser(prog="python -m kgdemo.server", description="Run the demo web app.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8501)
    args = parser.parse_args(argv)
    print(f"Knowledge Graph Demo: http://localhost:{args.port}  (API docs: http://localhost:{args.port}/api/docs)")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
