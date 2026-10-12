"""Neo4j loader: schema, vocabulary, structured exports, documents, extractions and business rules.

    python -m kgdemo.graph_load --structured-only   # reset + schema + vocabulary + structured data + rules
    python -m kgdemo.graph_load                     # show node and relationship counts

The graph follows the contract in docs/ARCHITECTURE.md. Values always travel as query parameters;
labels and relationship types are interpolated into Cypher only after the semantic model
(ontology/semantic_model.yaml) has been checked to declare them. Writes are batched with UNWIND.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterator

from . import config
from . import neo4j_client as db
from .models import DocumentRecord, EntityRef, Extraction, split_key
from .ontology import Ontology, load_ontology

BATCH_SIZE = 1000
DELETE_BATCH_SIZE = 5000
INDEX_TIMEOUT_S = 300

OWNED_PREFIX = "kg_"                                   # constraints and range indexes created here
OWNED_INDEXES = ("documentText", "entityNames", "chunkEmbedding")
ENTITY_NAME_LABELS = ("Person", "Company", "Fund", "Client", "Theme", "Concept")
RANGE_INDEXES = (
    ("Person", "name"), ("Client", "name"), ("Fund", "name"), ("Company", "name"), ("Theme", "name"),
    ("Concept", "name"), ("Committee", "name"), ("Document", "title"), ("Meeting", "title"),
    ("Document", "date"), ("Meeting", "date"), ("Decision", "date"), ("Transaction", "date"),
)
STRUCTURED_FILES = ("people", "contacts", "advisors", "clients", "accounts", "funds", "companies", "fund_holdings",
                    "company_themes", "holdings", "ic_decisions", "transactions")
DECISION_ID = re.compile(r"(?<![A-Za-z0-9-])IC-\d{4}-\d{3}(?![0-9])")   # R-TXN-DECISION: IC-YYYY-NNN
EXTRACTED_REL_KEYS = ("origin", "engine", "method", "evidence", "doc_id")  # set by the loader, never by props

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


# =============================================================================
# Cypher building blocks
# =============================================================================
def _ident(name: str) -> str:
    """A backtick-quoted identifier, after a strict character check."""
    if not _IDENTIFIER.match(name):
        raise ValueError(f"unsafe Cypher identifier {name!r}")
    return f"`{name}`"


def _label(onto: Ontology, label: str) -> str:
    """Labels reach Cypher only when the semantic model declares them."""
    if label not in onto.entities:
        raise ValueError(f"label {label!r} is not declared in the semantic model")
    return _ident(label)


def _rel_type(onto: Ontology, rel_type: str) -> str:
    """Relationship types reach Cypher only when the semantic model declares them."""
    if rel_type not in onto.relationships:
        raise ValueError(f"relationship type {rel_type!r} is not declared in the semantic model")
    return _ident(rel_type)


def _batches(rows: list, size: int) -> Iterator[list]:
    for i in range(0, len(rows), size):
        yield rows[i:i + size]


def _write_rows(query: str, rows: list[dict]) -> int:
    """Runs a query that UNWINDs $rows and RETURNs `n`, batch by batch; returns the summed n."""
    return sum(db.write(query, {"rows": batch})[0]["n"] for batch in _batches(rows, BATCH_SIZE))


def _node(node_id: str, **props: Any) -> dict:
    return {"id": node_id, "props": props}


def _edge(src: str, dst: str, **props: Any) -> dict:
    return {"src": src, "dst": dst, "props": props}


def _merge_nodes(onto: Ontology, label: str, rows: list[dict]) -> int:
    """MERGE nodes by id and overwrite the given properties (None removes a property)."""
    query = (f"UNWIND $rows AS row MERGE (n:{_label(onto, label)} {{id: row.id}}) "
             "SET n += row.props RETURN count(*) AS n")
    return _write_rows(query, rows)


def _merge_rels(onto: Ontology, rel_type: str, src_label: str, dst_label: str, rows: list[dict]) -> int:
    """MERGE structured relationships between existing nodes; every endpoint must already be loaded."""
    if not onto.allows(rel_type, src_label, dst_label):
        raise ValueError(f"{src_label} -[{rel_type}]-> {dst_label} is not allowed by the semantic model")
    query = (f"UNWIND $rows AS row\n"
             f"MATCH (a:{_label(onto, src_label)} {{id: row.src}})\n"
             f"MATCH (b:{_label(onto, dst_label)} {{id: row.dst}})\n"
             f"MERGE (a)-[r:{_rel_type(onto, rel_type)}]->(b)\n"
             "SET r += row.props, r.origin = 'structured'\n"
             "RETURN count(*) AS n")
    n = _write_rows(query, rows)
    if n != len(rows):
        missing = ([f"{src_label}:{i}" for i in _missing_ids(onto, src_label, [r["src"] for r in rows])]
                   + [f"{dst_label}:{i}" for i in _missing_ids(onto, dst_label, [r["dst"] for r in rows])])
        raise ValueError(f"{rel_type}: {len(rows) - n} of {len(rows)} rows reference nodes that are not loaded: "
                         f"{', '.join(missing[:10])}")
    return n


def _missing_ids(onto: Ontology, label: str, ids: list[str]) -> list[str]:
    """The ids (sorted, distinct) that have no node with this label."""
    wanted = sorted(set(ids))
    rows = db.run(f"MATCH (n:{_label(onto, label)}) WHERE n.id IN $ids RETURN n.id AS id", {"ids": wanted})
    found = {r["id"] for r in rows}
    return [i for i in wanted if i not in found]


# =============================================================================
# reset + schema
# =============================================================================
def _owned(name: str) -> bool:
    return name.startswith(OWNED_PREFIX) or name in OWNED_INDEXES


def reset_graph() -> int:
    """Deletes every node and relationship, then drops the constraints and indexes this module owns.

    Returns the number of deleted nodes. Neo4j's built-in token lookup indexes are kept.
    """
    deleted = 0
    while True:
        n = db.write("MATCH (n) WITH n LIMIT $limit DETACH DELETE n RETURN count(*) AS n",
                     {"limit": DELETE_BATCH_SIZE})[0]["n"]
        deleted += n
        if n == 0:
            break
    for row in db.run("SHOW CONSTRAINTS YIELD name RETURN name"):
        if _owned(row["name"]):
            db.write(f"DROP CONSTRAINT {_ident(row['name'])} IF EXISTS")
    for row in db.run("SHOW INDEXES YIELD name, owningConstraint RETURN name, owningConstraint"):
        if _owned(row["name"]) and row["owningConstraint"] is None:
            db.write(f"DROP INDEX {_ident(row['name'])} IF EXISTS")
    return deleted


def create_schema(onto: Ontology | None = None) -> dict[str, list[str]]:
    """Creates (IF NOT EXISTS) uniqueness constraints, range indexes and full-text indexes, then waits for them.

    The vector index `chunkEmbedding` belongs to the embedding step (kgdemo.embed.build_chunks).
    """
    onto = onto or load_ontology()
    created: dict[str, list[str]] = {"constraints": [], "range_indexes": [], "fulltext_indexes": []}
    for label in dict.fromkeys(onto.labels(include_technical=False) + ["Chunk"]):
        name = f"{OWNED_PREFIX}{label.lower()}_id"
        db.write(f"CREATE CONSTRAINT {_ident(name)} IF NOT EXISTS "
                 f"FOR (n:{_label(onto, label)}) REQUIRE n.id IS UNIQUE")
        created["constraints"].append(name)
    for label, prop in RANGE_INDEXES:
        name = f"{OWNED_PREFIX}{label.lower()}_{prop}"
        db.write(f"CREATE INDEX {_ident(name)} IF NOT EXISTS FOR (n:{_label(onto, label)}) ON (n.{_ident(prop)})")
        created["range_indexes"].append(name)
    db.write(f"CREATE FULLTEXT INDEX documentText IF NOT EXISTS "
             f"FOR (d:{_label(onto, 'Document')}) ON EACH [d.title, d.text]")
    labels = "|".join(_label(onto, label) for label in ENTITY_NAME_LABELS)
    db.write(f"CREATE FULLTEXT INDEX entityNames IF NOT EXISTS FOR (n:{labels}) ON EACH [n.name]")
    created["fulltext_indexes"] += ["documentText", "entityNames"]
    db.write("CALL db.awaitIndexes($timeout)", {"timeout": INDEX_TIMEOUT_S})
    return created


# =============================================================================
# vocabulary (semantic model)
# =============================================================================
def load_vocabulary(onto: Ontology | None = None) -> dict[str, int]:
    """Themes, concepts (BROADER -> theme), theme links (RELATED_TO) and committees from the semantic model."""
    onto = onto or load_ontology()
    counts = {
        "Theme": _merge_nodes(onto, "Theme", [_node(t.id, name=t.name, definition=t.definition)
                                              for t in onto.themes.values()]),
        "Concept": _merge_nodes(onto, "Concept", [_node(c.id, name=c.name, theme_id=c.theme_id)
                                                  for c in onto.concepts.values()]),
        "Committee": _merge_nodes(onto, "Committee", [_node(c.id, name=c.name, charter=c.charter or None)
                                                      for c in onto.committees.values()]),
    }
    counts["BROADER"] = _merge_rels(onto, "BROADER", "Concept", "Theme",
                                    [_edge(c.id, c.theme_id) for c in onto.concepts.values()])
    counts["RELATED_TO"] = _merge_rels(onto, "RELATED_TO", "Theme", "Theme",
                                       [_edge(link["from"], link["to"], rationale=link.get("rationale"))
                                        for link in onto.theme_links])
    return counts


# =============================================================================
# structured exports (CSV)
# =============================================================================
def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _str(value: str | None) -> str | None:
    """Empty cells become missing properties rather than empty strings."""
    value = (value or "").strip()
    return value or None


def _date(value: str | date | None) -> date | None:
    """ISO 'YYYY-MM-DD' (a longer ISO timestamp is cut to its date) -> date; raises ValueError otherwise."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    value = (value or "").strip()
    return date.fromisoformat(value[:10]) if value else None


def _float(value: str | None) -> float | None:
    value = (value or "").strip()
    return float(value) if value else None


def _number(value: str | None) -> int | float | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return float(value)


def _pipe(value: str | None) -> list[str]:
    return [v.strip() for v in (value or "").split("|") if v.strip()]


def _committees(value: str | None) -> list[tuple[str, str | None]]:
    """'COM-IC:Chair|COM-RISK:Member' -> [('COM-IC', 'Chair'), ('COM-RISK', 'Member')]."""
    out = []
    for item in _pipe(value):
        committee_id, _, role = item.partition(":")
        out.append((committee_id.strip(), _str(role)))
    return out


def _read_structured(structured_dir: Path) -> dict[str, list[dict[str, str]]]:
    missing = [f"{name}.csv" for name in STRUCTURED_FILES if not (structured_dir / f"{name}.csv").exists()]
    if missing:
        raise FileNotFoundError(f"{structured_dir} lacks {', '.join(missing)}; "
                                "run python -m kgdemo.generate_structured")
    return {name: _read_csv(structured_dir / f"{name}.csv") for name in STRUCTURED_FILES}


def _load_people(onto: Ontology, data: dict) -> dict[str, int]:
    people = [_node(r["id"], name=_str(r["name"]), title=_str(r["title"]), department=_str(r["department"]),
                    person_type="employee", organization=config.FIRM_NAME, email=_str(r["email"]))
              for r in data["people"]]
    people += [_node(r["id"], name=_str(r["name"]), title=_str(r["title"]), department=None,
                     person_type=_str(r["contact_type"]), organization=_str(r["organization"]),
                     email=_str(r["email"]))
               for r in data["contacts"]]
    counts = {"Person": _merge_nodes(onto, "Person", people)}
    advisors = [_node(r["person_id"], office=_str(r["office"]), start_date=_date(r["start_date"]))
                for r in data["advisors"]]
    query = (f"UNWIND $rows AS row MATCH (n:{_label(onto, 'Person')} {{id: row.id}}) "
             f"SET n:{_label(onto, 'Advisor')}, n += row.props RETURN count(*) AS n")
    counts["Advisor"] = _write_rows(query, advisors)
    if counts["Advisor"] != len(advisors):
        missing = _missing_ids(onto, "Person", [a["id"] for a in advisors])
        raise ValueError(f"advisors.csv references people that are not loaded: Person {', '.join(missing)}")
    return counts


def _load_companies(onto: Ontology, data: dict) -> dict[str, int]:
    rows = [_node(r["id"], name=_str(r["name"]), legal_name=_str(r["legal_name"]), ticker=_str(r["ticker"]),
                  kind=_str(r["kind"]), sector=_str(r["sector"]), industry=_str(r["industry"]),
                  country=_str(r["country"]))
            for r in data["companies"]]
    return {"Company": _merge_nodes(onto, "Company", rows)}


def _load_clients(onto: Ontology, data: dict) -> dict[str, int]:
    rows = data["clients"]
    nodes = [_node(r["id"], name=_str(r["name"]), client_type=_str(r["client_type"]), segment=_str(r["segment"]),
                   risk_profile=_str(r["risk_profile"]), client_since=_date(r["client_since"]),
                   city=_str(r["city"]), notes=_str(r["notes"]))
             for r in rows]
    counts = {"Client": _merge_nodes(onto, "Client", nodes)}
    counts["ADVISED_BY"] = _merge_rels(onto, "ADVISED_BY", "Client", "Advisor",
                                       [_edge(r["id"], r["advisor_id"]) for r in rows if _str(r["advisor_id"])])
    return counts


def _load_accounts(onto: Ontology, data: dict) -> dict[str, int]:
    rows = data["accounts"]
    nodes = [_node(r["id"], name=_str(r["name"]), account_number=_str(r["account_number"]),
                   registration=_str(r["registration"]), account_type=_str(r["account_type"]),
                   custodian=_str(r["custodian"]), tax_status=_str(r["tax_status"]), model=_str(r["model"]),
                   opened_date=_date(r["opened_date"]), commitment_usd=_float(r["commitment_usd"]))
             for r in rows]
    counts = {"Account": _merge_nodes(onto, "Account", nodes)}
    counts["HAS_ACCOUNT"] = _merge_rels(onto, "HAS_ACCOUNT", "Client", "Account",
                                        [_edge(r["client_id"], r["id"]) for r in rows])
    return counts


def _load_funds(onto: Ontology, data: dict) -> dict[str, int]:
    rows = data["funds"]
    nodes = [_node(r["id"], name=_str(r["name"]), ticker=_str(r["ticker"]), share_class=_str(r["share_class"]),
                   asset_class=_str(r["asset_class"]), strategy=_str(r["strategy"]), benchmark=_str(r["benchmark"]),
                   inception_date=_date(r["inception_date"]), expense_ratio_pct=_float(r["expense_ratio_pct"]),
                   aum_usd_m=_number(r["aum_usd_m"]), nav=_float(r["nav"]), nav_date=_date(r["nav_date"]))
             for r in rows]
    counts = {"Fund": _merge_nodes(onto, "Fund", nodes)}
    counts["FOCUSES_ON"] = _merge_rels(onto, "FOCUSES_ON", "Fund", "Theme",
                                       [_edge(r["id"], theme_id) for r in rows for theme_id in _pipe(r["themes"])])
    counts["MANAGED_BY"] = _merge_rels(onto, "MANAGED_BY", "Fund", "Person",
                                       [_edge(r["id"], r["pm_id"]) for r in rows if _str(r["pm_id"])])
    return counts


def _load_fund_holdings(onto: Ontology, data: dict) -> dict[str, int]:
    edges = [_edge(r["fund_id"], r["company_id"], weight=_float(r["weight_pct"]), since=_date(r["since"]),
                   as_of=_date(r["as_of"]))
             for r in data["fund_holdings"]]
    return {"INVESTED_IN": _merge_rels(onto, "INVESTED_IN", "Fund", "Company", edges)}


def _load_company_themes(onto: Ontology, data: dict) -> dict[str, int]:
    edges = [_edge(r["company_id"], r["theme_id"], degree=_str(r["degree"])) for r in data["company_themes"]]
    return {"EXPOSED_TO": _merge_rels(onto, "EXPOSED_TO", "Company", "Theme", edges)}


def _load_person_links(onto: Ontology, data: dict) -> dict[str, int]:
    members = [_edge(r["id"], committee_id, role=role)
               for r in data["people"] for committee_id, role in _committees(r["committees"])]
    contacts = data["contacts"]
    return {
        "MEMBER_OF": _merge_rels(onto, "MEMBER_OF", "Person", "Committee", members),
        "CONTACT_FOR": _merge_rels(onto, "CONTACT_FOR", "Person", "Client",
                                   [_edge(r["id"], r["client_id"], role=_str(r["title"]))
                                    for r in contacts if _str(r["client_id"])]),
        "WORKS_FOR": _merge_rels(onto, "WORKS_FOR", "Person", "Company",
                                 [_edge(r["id"], r["company_id"]) for r in contacts if _str(r["company_id"])]),
    }


def _load_holdings(onto: Ontology, data: dict) -> dict[str, int]:
    edges = [_edge(r["account_id"], r["fund_id"], shares=_float(r["shares"]), price=_float(r["price"]),
                   market_value=_float(r["market_value"]), cost_basis=_float(r["cost_basis"]),
                   as_of=_date(r["as_of"]))
             for r in data["holdings"]]
    return {"HOLDS": _merge_rels(onto, "HOLDS", "Account", "Fund", edges)}


def _load_decisions(onto: Ontology, data: dict) -> dict[str, int]:
    rows = data["ic_decisions"]
    nodes = [_node(r["id"], title=_str(r["title"]), date=_date(r["date"]), status=_str(r["status"]),
                   vote=_str(r["vote"]), direction=_str(r["direction"]), summary=_str(r["summary"]))
             for r in rows]
    counts = {"Decision": _merge_nodes(onto, "Decision", nodes), "AFFECTS": 0}
    for column, label in (("affects_funds", "Fund"), ("affects_companies", "Company"), ("affects_themes", "Theme")):
        edges = [_edge(r["id"], target) for r in rows for target in _pipe(r[column])]
        counts["AFFECTS"] += _merge_rels(onto, "AFFECTS", "Decision", label, edges)
    return counts


def _load_transactions(onto: Ontology, data: dict) -> dict[str, int]:
    rows = data["transactions"]
    nodes = [_node(r["id"], date=_date(r["trade_date"]), settle_date=_date(r["settle_date"]),
                   txn_type=_str(r["txn_type"]), shares=_float(r["shares"]), price=_float(r["price"]),
                   amount_usd=_float(r["amount_usd"]), order_reason=_str(r["order_reason"]))
             for r in rows]
    counts = {"Transaction": _merge_nodes(onto, "Transaction", nodes)}
    counts["HAS_TRANSACTION"] = _merge_rels(onto, "HAS_TRANSACTION", "Account", "Transaction",
                                            [_edge(r["account_id"], r["id"]) for r in rows])
    counts["INVOLVES"] = _merge_rels(onto, "INVOLVES", "Transaction", "Fund",
                                     [_edge(r["id"], r["fund_id"]) for r in rows])
    return counts


def load_structured(structured_dir: str | Path = config.STRUCTURED_DIR,
                    onto: Ontology | None = None) -> dict[str, int]:
    """Loads the CSV exports (systems of record). Requires load_vocabulary() first (themes, committees).

    Returns counts per label and relationship type. Raises ValueError when a row references a node that
    does not exist: structured data must be referentially complete.
    """
    onto = onto or load_ontology()
    data = _read_structured(Path(structured_dir))
    counts: dict[str, int] = {}
    for step in (_load_people, _load_companies, _load_clients, _load_accounts, _load_funds, _load_fund_holdings,
                 _load_company_themes, _load_person_links, _load_holdings, _load_decisions, _load_transactions):
        counts.update(step(onto, data))
    return counts


# =============================================================================
# documents + extractions (unstructured)
# =============================================================================
def load_documents(records: list[DocumentRecord], engine_by_doc: dict[str, str] | None = None) -> int:
    """MERGE one Document node per record. `extraction_engine` is only overwritten when an engine is given."""
    engine_by_doc = engine_by_doc or {}
    rows = [{"id": r.doc_id,
             "props": {"title": r.title, "doc_type": r.doc_type, "date": _date(r.date),
                       "source_system": r.source_system, "source_path": r.source_path, "text": r.text},
             "engine": engine_by_doc.get(r.doc_id)}
            for r in records]
    label = _label(load_ontology(), "Document")
    query = (f"UNWIND $rows AS row MERGE (d:{label} {{id: row.id}})\n"
             "SET d += row.props, d.extraction_engine = coalesce(row.engine, d.extraction_engine)\n"
             "RETURN count(*) AS n")
    return _write_rows(query, rows)


def _prop_value(value: Any) -> Any:
    """Neo4j stores primitives and homogeneous lists; anything else is kept as JSON text."""
    if value is None or isinstance(value, (str, bool, int, float, date)):
        return value
    if isinstance(value, (list, tuple)):
        items = [v for v in value if v is not None]
        kinds = {type(v) for v in items}
        if len(kinds) <= 1 and kinds <= {str, bool, int, float}:
            return items
        if kinds <= {int, float}:
            return [float(v) for v in items]
    return json.dumps(value, ensure_ascii=False, default=str)


def _rel_props(props: dict | None) -> dict:
    return {k: _prop_value(v) for k, v in (props or {}).items() if v is not None and k not in EXTRACTED_REL_KEYS}


def _candidate_id(label: str, name: str) -> str:
    """Id for an unresolved entity that arrived without one; same form as the extractors use (NEW-PERSON-JANE-DOE)."""
    slug = re.sub(r"[^A-Z0-9]+", "-", (name or "").upper()).strip("-") or "UNNAMED"
    return f"NEW-{label.upper()}-{slug}"


def _extracted_rel_problem(onto: Ontology, rel_type: str, src: tuple[str, str], dst: tuple[str, str]) -> str | None:
    """Why a relationship from an extraction cannot be loaded, or None when it is valid."""
    rel = onto.relationships.get(rel_type)
    if rel is None:
        return "relationship type is not declared in the semantic model"
    if rel.origin != "extracted":
        return f"{rel_type} is a {rel.origin} relationship and cannot come from extraction"
    for label, entity_id in (src, dst):
        if label not in onto.entities or onto.entities[label].technical:
            return f"unknown or technical entity label {label!r}"
        if not entity_id:
            return "empty entity id"
    if not onto.allows(rel_type, src[0], dst[0]):
        return f"{src[0]} -> {dst[0]} is outside the domain/range of {rel_type}"
    if src == dst:
        return "self-reference"
    return None


def _meeting_props(entity: EntityRef, extraction: Extraction) -> tuple[dict, str | None]:
    """Meeting title/date/type from the entity, falling back to the extraction's meeting record.

    Returns (props, problem); an unparseable date is dropped and reported instead of failing the load.
    """
    record = extraction.meeting if extraction.meeting and extraction.meeting.get("id") == entity.id else {}
    props = {**record, **{k: v for k, v in (entity.properties or {}).items() if v not in (None, "")}}
    problem = None
    try:
        meeting_date = _date(props.get("date"))
    except (TypeError, ValueError):
        meeting_date, problem = None, f"meeting {entity.id} has an unparseable date {props.get('date')!r}"
    return {"title": props.get("title") or entity.name or None, "date": meeting_date,
            "meeting_type": props.get("meeting_type") or None}, problem


def _caption_props(onto: Ontology, label: str, name: str) -> dict:
    """{caption property: name} for nodes the extraction creates (e.g. Person.name, Document.title)."""
    caption = onto.entities[label].caption
    return {caption: name} if caption != "id" and name else {}


def load_extractions(extractions: list[Extraction], onto: Ontology | None = None) -> dict:
    """Writes extraction results into the graph.

    * Meeting entities are MERGEd with title, date and meeting_type.
    * Resolved entities are matched by label + id; when one is not in the graph yet it is created and a
      warning is recorded (these normally come from master data).
    * Unresolved entities (resolved=False) are MERGEd as candidates: name + candidate=true.
    * Relationships must be `extracted` types of the semantic model and respect its domain/range. They are
      MERGEd between existing nodes; a new edge gets origin='extracted', engine, method, evidence, doc_id
      and the extraction's properties (e.g. inferred, via). Existing edges are left unchanged, so loading
      the same extraction twice changes nothing.

    Returns {"extractions", "nodes": {...}, "relationships": {type: n}, "skipped", "warnings": [...]}.
    """
    onto = onto or load_ontology()
    warnings: list[str] = []
    meetings: dict[str, dict] = {}
    resolved: dict[str, dict[str, tuple[str, str]]] = defaultdict(dict)   # label -> {id: (name, first doc)}
    candidates: dict[str, dict[str, str]] = defaultdict(dict)             # label -> {id: name}
    rels: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    skipped = 0

    for ex in extractions:
        keys: dict[str, tuple[str, str]] = {}
        for e in ex.entities:
            if e.label not in onto.entities or onto.entities[e.label].technical:
                warnings.append(f"{ex.doc_id}: entity {e.key} has an unknown or technical label {e.label!r}; skipped")
                continue
            entity_id = e.id or ("" if e.resolved or e.label == "Meeting" else _candidate_id(e.label, e.name))
            if not entity_id:
                warnings.append(f"{ex.doc_id}: entity {e.key} has no id; skipped")
                continue
            keys[e.key] = (e.label, entity_id)
            if e.label == "Meeting":
                meetings[entity_id], problem = _meeting_props(e, ex)
                if problem:
                    warnings.append(f"{ex.doc_id}: {problem}")
            elif e.resolved:
                resolved[e.label].setdefault(entity_id, (e.name, ex.doc_id))
            else:
                candidates[e.label].setdefault(entity_id, e.name)
        for r in ex.relationships:
            src, dst = keys.get(r.source) or split_key(r.source), keys.get(r.target) or split_key(r.target)
            problem = _extracted_rel_problem(onto, r.type, src, dst)
            if problem:
                warnings.append(f"{ex.doc_id}: {r.source} -[{r.type}]-> {r.target} skipped: {problem}")
                skipped += 1
                continue
            rels[(r.type, src[0], dst[0])].append({
                "src": src[1], "dst": dst[1], "engine": ex.engine, "method": r.method or "",
                "evidence": r.evidence or "", "doc_id": ex.doc_id, "props": _rel_props(r.properties),
                "label": f"{ex.doc_id}: {r.source} -[{r.type}]-> {r.target}"})

    nodes = {"Meeting": _write_meetings(onto, meetings), "matched": 0, "created": 0, "candidates": 0}
    for label, by_id in sorted(resolved.items()):
        created = _match_or_merge(onto, label, by_id)
        nodes["matched"] += len(by_id) - len(created)
        nodes["created"] += len(created)
        warnings += [f"{by_id[i][1]}: resolved entity {label}:{i} was not in the graph; created it" for i in created]
    for label, by_id in sorted(candidates.items()):
        nodes["candidates"] += _merge_candidates(onto, label, by_id)
    counts: dict[str, int] = {}
    for (rel_type, src_label, dst_label), rows in sorted(rels.items()):
        loaded, missing = _merge_extracted_rels(onto, rel_type, src_label, dst_label, rows)
        counts[rel_type] = counts.get(rel_type, 0) + loaded
        skipped += len(missing)
        warnings += [f"{m} skipped: endpoint not in the graph" for m in missing]
    warnings += _stamp_documents(onto, extractions)
    return {"extractions": len(extractions), "nodes": nodes, "relationships": counts, "skipped": skipped,
            "warnings": warnings}


def _write_meetings(onto: Ontology, meetings: dict[str, dict]) -> int:
    rows = [{"id": mid, **props} for mid, props in sorted(meetings.items())]
    query = (f"UNWIND $rows AS row MERGE (m:{_label(onto, 'Meeting')} {{id: row.id}})\n"
             "SET m.title = coalesce(row.title, m.title), m.date = coalesce(row.date, m.date),\n"
             "    m.meeting_type = coalesce(row.meeting_type, m.meeting_type)\n"
             "RETURN count(*) AS n")
    return _write_rows(query, rows)


def _match_or_merge(onto: Ontology, label: str, by_id: dict[str, tuple[str, str]]) -> list[str]:
    """Creates the resolved entities that are not in the graph yet; returns their ids."""
    missing = _missing_ids(onto, label, list(by_id))
    rows = [_node(i, **_caption_props(onto, label, by_id[i][0])) for i in missing]
    query = (f"UNWIND $rows AS row MERGE (n:{_label(onto, label)} {{id: row.id}}) "
             "ON CREATE SET n += row.props RETURN count(*) AS n")
    _write_rows(query, rows)
    return missing


def _merge_candidates(onto: Ontology, label: str, by_id: dict[str, str]) -> int:
    rows = [_node(i, **_caption_props(onto, label, name)) for i, name in sorted(by_id.items())]
    query = (f"UNWIND $rows AS row MERGE (n:{_label(onto, label)} {{id: row.id}}) "
             "ON CREATE SET n += row.props, n.candidate = true RETURN count(*) AS n")
    return _write_rows(query, rows)


def _merge_extracted_rels(onto: Ontology, rel_type: str, src_label: str, dst_label: str,
                          rows: list[dict]) -> tuple[int, list[str]]:
    """Returns (rows merged, descriptions of rows whose endpoints are missing)."""
    rows = sorted(rows, key=lambda r: r["props"].get("inferred") is True)  # explicit evidence wins over inferred
    for i, row in enumerate(rows):
        row["i"] = i
    query = (f"UNWIND $rows AS row\n"
             f"MATCH (a:{_label(onto, src_label)} {{id: row.src}})\n"
             f"MATCH (b:{_label(onto, dst_label)} {{id: row.dst}})\n"
             f"MERGE (a)-[r:{_rel_type(onto, rel_type)}]->(b)\n"
             "ON CREATE SET r += row.props, r.origin = 'extracted', r.engine = row.engine, r.method = row.method,\n"
             "              r.evidence = row.evidence, r.doc_id = row.doc_id\n"
             "RETURN collect(row.i) AS merged")
    merged: set[int] = set()
    for batch in _batches(rows, BATCH_SIZE):
        params = [{k: v for k, v in row.items() if k != "label"} for row in batch]
        merged.update(db.write(query, {"rows": params})[0]["merged"])
    return len(merged), [row["label"] for row in rows if row["i"] not in merged]


def _stamp_documents(onto: Ontology, extractions: list[Extraction]) -> list[str]:
    """Records the engine on documents that have none yet; warns about documents that were never loaded."""
    rows = [{"id": ex.doc_id, "engine": ex.engine} for ex in extractions]
    query = (f"UNWIND $rows AS row MATCH (d:{_label(onto, 'Document')} {{id: row.id}})\n"
             "SET d.extraction_engine = coalesce(d.extraction_engine, row.engine)\n"
             "RETURN collect(row.id) AS found")
    found: set[str] = set()
    for batch in _batches(rows, BATCH_SIZE):
        found.update(db.write(query, {"rows": batch})[0]["found"])
    return [f"Document:{ex.doc_id} is not in the graph (call load_documents first)"
            for ex in extractions if ex.doc_id not in found]


# =============================================================================
# business rules
# =============================================================================
def apply_rules(onto: Ontology | None = None) -> dict:
    """Applies the semantic model's Cypher rules (R-OWNS) and R-TXN-DECISION.

    Returns {"rules": {rule id: relationships carrying that rule}, "warnings": [...]}.
    """
    onto = onto or load_ontology()
    counts: dict[str, int] = {}
    for rule in onto.rules:
        if rule.get("cypher"):
            rel_type = rule.get("produces", "")
            _rel_type(onto, rel_type)                    # the rule must produce a declared relationship type
            db.write(rule["cypher"])
            counts[rule["id"]] = _count_rule(onto, rel_type, rule["id"])
    unknown = _link_transactions_to_decisions(onto)
    counts["R-TXN-DECISION"] = _count_rule(onto, "PURSUANT_TO", "R-TXN-DECISION")
    warnings = [f"R-TXN-DECISION: order reasons reference {d}, which is not in the decision log" for d in unknown]
    return {"rules": counts, "warnings": warnings}


def _count_rule(onto: Ontology, rel_type: str, rule_id: str) -> int:
    return db.run(f"MATCH ()-[r:{_rel_type(onto, rel_type)}]->() WHERE r.rule = $rule RETURN count(r) AS n",
                  {"rule": rule_id})[0]["n"]


def _link_transactions_to_decisions(onto: Ontology) -> list[str]:
    """(Transaction)-[:PURSUANT_TO]->(Decision) for every logged decision id found in an order reason.

    Returns the decision ids that order reasons mention but the decision log does not contain.
    """
    txns = db.run(f"MATCH (t:{_label(onto, 'Transaction')}) WHERE t.order_reason IS NOT NULL "
                  "RETURN t.id AS id, t.order_reason AS reason")
    known = {r["id"] for r in db.run(f"MATCH (d:{_label(onto, 'Decision')}) RETURN d.id AS id")}
    pairs = sorted({(t["id"], decision_id) for t in txns for decision_id in DECISION_ID.findall(t["reason"])})
    rows = [_edge(txn_id, decision_id, rule="R-TXN-DECISION") for txn_id, decision_id in pairs if decision_id in known]
    _merge_rels(onto, "PURSUANT_TO", "Transaction", "Decision", rows)
    return sorted({decision_id for _, decision_id in pairs if decision_id not in known})


# =============================================================================
# stats + CLI
# =============================================================================
def graph_stats() -> dict[str, dict[str, int]]:
    """{"nodes": {label: count}, "relationships": {type: count}}; a node counts once per label."""
    nodes = db.run("MATCH (n) UNWIND labels(n) AS label RETURN label, count(*) AS n ORDER BY label")
    rels = db.run("MATCH ()-[r]->() RETURN type(r) AS type, count(*) AS n ORDER BY type")
    return {"nodes": {r["label"]: r["n"] for r in nodes}, "relationships": {r["type"]: r["n"] for r in rels}}


def _fmt(counts: dict[str, int]) -> str:
    return ", ".join(f"{k} {v:,}" for k, v in counts.items()) or "-"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m kgdemo.graph_load",
                                     description="Load the structured part of the knowledge graph, or show counts.")
    parser.add_argument("--structured-only", action="store_true",
                        help="reset Neo4j, then load schema, vocabulary, structured exports and business rules")
    args = parser.parse_args(argv)
    if args.structured_only:
        onto = load_ontology()
        print(f"reset        deleted {reset_graph():,} nodes")
        schema = create_schema(onto)
        print(f"schema       {len(schema['constraints'])} constraints, {len(schema['range_indexes'])} range indexes, "
              f"{len(schema['fulltext_indexes'])} full-text indexes")
        print(f"vocabulary   {_fmt(load_vocabulary(onto))}")
        print(f"structured   {_fmt(load_structured(config.STRUCTURED_DIR, onto))}")
        rules = apply_rules(onto)
        print(f"rules        {_fmt(rules['rules'])}")
        for warning in rules["warnings"]:
            print(f"warning      {warning}")
    stats = graph_stats()
    print(f"nodes        {_fmt(stats['nodes'])}")
    print(f"rels         {_fmt(stats['relationships'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
