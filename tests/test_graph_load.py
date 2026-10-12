"""Graph loading, business rules, chunking and embeddings.

The Neo4j tests RESET the database (marker `destructive`), so they only run when asked:

    KG_DESTRUCTIVE_TESTS=1 .venv/bin/python -m pytest tests/test_graph_load.py

They leave Neo4j loaded with the structured data only (what `python -m kgdemo.graph_load --structured-only`
produces); run `python -m kgdemo.build` afterwards for the full demo graph. Chunking tests need no database.
"""
from __future__ import annotations

import csv
import math
import random
from collections import Counter

import pytest
from neo4j.time import Date

from kgdemo import build, config, embed, graph_load
from kgdemo import world as w
from kgdemo import neo4j_client as db
from kgdemo.embed import chunk_text
from kgdemo.models import DocumentRecord, EntityRef, Extraction, RelationshipRef, meeting_id
from kgdemo.ontology import load_ontology

destructive = pytest.mark.destructive

TEST_PREFIX = "DOC-TEST-"
DOC_ID = "DOC-TEST-MN-01"
TITLE = "AI Hardware Research Sync"
DATE = "2026-03-05"
MTG_ID = meeting_id(DATE, TITLE)
DOC, MEETING = f"Document:{DOC_ID}", f"Meeting:{MTG_ID}"
CANDIDATE_ID = "NEW-PERSON-JORDAN-PIKE"
UNKNOWN_COMPANY_ID = "CMP-ZZZ-TEST"
GPU_EVIDENCE = "Meredith Calloway expects demand for GPU capacity to stay ahead of supply through 2027."
PKG_EVIDENCE = "Arjun Mehta flagged that Nvidia shipments depend on advanced packaging capacity at TSMC."
NOTE_TEXT = (f"{TITLE}\nDate: {DATE}\nMeeting Type: Research\nParticipants:\nMeredith Calloway\nArjun Mehta\n"
             f"Jordan Pike (Halvorsen Analytics)\n\nDiscussion:\n{GPU_EVIDENCE}\n{PKG_EVIDENCE}\n"
             "Jordan Pike shared channel checks on rack-level power density at Zed Holdings.\n")
CLEANUP_IDS = [MTG_ID, CANDIDATE_ID, UNKNOWN_COMPANY_ID, "TXN-TEST-1"]


# =============================================================================
# helpers + fixtures
# =============================================================================
def _csv(name: str) -> list[dict[str, str]]:
    with (config.STRUCTURED_DIR / name).open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _load_structured_graph() -> dict:
    """What `python -m kgdemo.graph_load --structured-only` does."""
    graph_load.reset_graph()
    graph_load.create_schema()
    return {"vocabulary": graph_load.load_vocabulary(), "structured": graph_load.load_structured(),
            "rules": graph_load.apply_rules()}


def _cleanup_test_nodes() -> None:
    db.write("MATCH (n) WHERE n.id STARTS WITH $prefix OR n.id IN $ids DETACH DELETE n",
             {"prefix": TEST_PREFIX, "ids": CLEANUP_IDS})


def _assert_conforms_to_semantic_model() -> None:
    onto = load_ontology()
    labels = {r["l"] for r in db.run("MATCH (n) UNWIND labels(n) AS l RETURN DISTINCT l")}
    assert labels <= set(onto.entities), labels - set(onto.entities)
    for r in db.run("MATCH (a)-[r]->(b) RETURN DISTINCT type(r) AS t, labels(a) AS a, labels(b) AS b"):
        assert r["t"] in onto.relationships, r
        assert any(onto.allows(r["t"], la, lb) for la in r["a"] for lb in r["b"]), r


@pytest.fixture(scope="module")
def neo4j():
    try:
        db.ping()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Neo4j is not reachable: {exc}")
    yield db
    _load_structured_graph()        # leave the database with the structured data only


@pytest.fixture(scope="module")
def structured(neo4j):
    return _load_structured_graph()


@pytest.fixture
def clean(structured):
    """Removes every node a test adds on top of the structured graph."""
    _cleanup_test_nodes()
    yield
    _cleanup_test_nodes()


def _note_record(doc_id: str = DOC_ID) -> DocumentRecord:
    return DocumentRecord(doc_id=doc_id, doc_type="Meeting Notes", title=TITLE, date=DATE,
                          source_system="Document Management", source_path=f"tests/{doc_id}.md", text=NOTE_TEXT,
                          body_offset=NOTE_TEXT.index("Discussion:"),
                          metadata={"meeting_type": "Research", "participants": []})


def _entity(label: str, entity_id: str, name: str, **kwargs) -> EntityRef:
    return EntityRef(key=f"{label}:{entity_id}", label=label, id=entity_id, name=name, **kwargs)


def _note_extraction() -> Extraction:
    """A meeting note: header facts, text mentions, concept -> theme inferences, one unresolved person,
    plus invalid items the loader must reject."""
    entities = [
        _entity("Meeting", MTG_ID, TITLE, origin="header", properties={"date": DATE, "meeting_type": "Research"}),
        _entity("Person", "PER-002", "Meredith Calloway", origin="header", mentions=["Meredith Calloway"]),
        _entity("Person", "PER-009", "Arjun Mehta", origin="header", mentions=["Arjun Mehta"]),
        _entity("Person", CANDIDATE_ID, "Jordan Pike", origin="header", resolved=False),
        _entity("Company", "CMP-NVDA", "Nvidia", mentions=["Nvidia"]),
        _entity("Company", "CMP-TSM", "TSMC", mentions=["TSMC"]),
        _entity("Company", UNKNOWN_COMPANY_ID, "Zed Holdings", mentions=["Zed Holdings"]),  # not in master data
        _entity("Concept", "CON-GPU", "GPU Capacity", mentions=["GPU capacity"]),
        _entity("Concept", "CON-PKG", "Advanced Packaging", mentions=["advanced packaging"]),
        _entity("Theme", "THM-AI", "AI Infrastructure", origin="inferred"),
        _entity("Theme", "THM-SEMI", "Semiconductor Supply Chain", origin="inferred"),
        _entity("Spaceship", "X-1", "Enterprise"),                                          # not in the ontology
    ]
    rel = RelationshipRef
    relationships = [
        rel(DOC, "RECORDS", MEETING, evidence=TITLE, method="header"),
        rel("Person:PER-002", "ATTENDED", MEETING, evidence="Participants: Meredith Calloway", method="header"),
        rel("Person:PER-009", "ATTENDED", MEETING, evidence="Participants: Arjun Mehta", method="header"),
        rel(f"Person:{CANDIDATE_ID}", "ATTENDED", MEETING, evidence="Participants: Jordan Pike", method="header"),
        rel(MEETING, "DISCUSSED", "Company:CMP-NVDA", evidence=PKG_EVIDENCE, method="text"),
        rel(MEETING, "DISCUSSED", "Concept:CON-GPU", evidence=GPU_EVIDENCE, method="text"),
        rel(MEETING, "DISCUSSED", "Theme:THM-AI", evidence=GPU_EVIDENCE, method="vocabulary",
            properties={"inferred": True, "via": "GPU Capacity"}),
        rel(DOC, "MENTIONS", "Company:CMP-NVDA", evidence=PKG_EVIDENCE, method="text"),
        rel(DOC, "MENTIONS", "Company:CMP-TSM", evidence=PKG_EVIDENCE, method="text"),
        rel(DOC, "MENTIONS", f"Company:{UNKNOWN_COMPANY_ID}", evidence="channel checks at Zed Holdings", method="text"),
        rel(DOC, "MENTIONS", "Concept:CON-PKG", evidence=PKG_EVIDENCE, method="text"),
        rel(DOC, "MENTIONS", "Theme:THM-SEMI", evidence=PKG_EVIDENCE, method="vocabulary",
            properties={"inferred": True, "via": "Advanced Packaging"}),
        # rejected: wrong direction, derived type, undeclared type, unknown label, endpoint not in the graph
        rel(MEETING, "ATTENDED", "Person:PER-002", evidence="reversed", method="llm"),
        rel(DOC, "OWNS", "Fund:FND-AIX", evidence="derived only", method="llm"),
        rel(DOC, "LIKES", "Company:CMP-NVDA", evidence="undeclared", method="llm"),
        rel(DOC, "MENTIONS", "Spaceship:X-1", evidence="unknown label", method="llm"),
        rel(DOC, "MENTIONS", "Person:PER-999", evidence="nobody", method="llm"),
    ]
    return Extraction(doc_id=DOC_ID, engine="rules", document={"id": DOC_ID, "title": TITLE},
                      entities=entities, relationships=relationships,
                      meeting={"id": MTG_ID, "title": TITLE, "date": DATE, "meeting_type": "Research"})


def _extracted_edges() -> list[dict]:
    return db.run("MATCH (a)-[r]->(b) WHERE r.doc_id STARTS WITH $prefix\n"
                  "RETURN a.id AS a, type(r) AS type, b.id AS b, properties(r) AS props ORDER BY type, a, b",
                  {"prefix": TEST_PREFIX})


# =============================================================================
# reset + schema
# =============================================================================
@destructive
def test_reset_graph_removes_data_and_owned_schema(neo4j):
    try:
        _load_structured_graph()
        assert graph_load.reset_graph() > 0
        assert db.run("MATCH (n) RETURN count(n) AS n")[0]["n"] == 0
        constraints = {r["name"] for r in db.run("SHOW CONSTRAINTS YIELD name RETURN name")}
        assert not {c for c in constraints if c.startswith("kg_")}
        indexes = db.run("SHOW INDEXES YIELD name, type RETURN name, type")
        assert not [r for r in indexes if r["name"].startswith("kg_") or r["name"] in graph_load.OWNED_INDEXES]
        assert any(r["type"] == "LOOKUP" for r in indexes)          # Neo4j's own token indexes are kept
    finally:
        _load_structured_graph()


@destructive
def test_schema_has_constraints_and_indexes(structured):
    onto = load_ontology()
    constraints = {r["name"]: r for r in db.run(
        "SHOW CONSTRAINTS YIELD name, type, labelsOrTypes, properties RETURN *")}
    for label in onto.labels(include_technical=False) + ["Chunk"]:
        c = constraints[f"kg_{label.lower()}_id"]
        assert (c["type"], c["labelsOrTypes"], c["properties"]) == ("UNIQUENESS", [label], ["id"])
    indexes = {r["name"]: r for r in db.run(
        "SHOW INDEXES YIELD name, type, labelsOrTypes, properties, state RETURN *")}
    assert all(r["state"] == "ONLINE" for r in indexes.values())
    text = indexes["documentText"]
    assert (text["type"], text["labelsOrTypes"], text["properties"]) == ("FULLTEXT", ["Document"], ["title", "text"])
    names = indexes["entityNames"]
    assert names["type"] == "FULLTEXT" and names["properties"] == ["name"]
    assert set(names["labelsOrTypes"]) == {"Person", "Company", "Fund", "Client", "Theme", "Concept"}
    for label, prop in graph_load.RANGE_INDEXES:
        r = indexes[f"kg_{label.lower()}_{prop}"]
        assert (r["type"], r["labelsOrTypes"], r["properties"]) == ("RANGE", [label], [prop])


@destructive
def test_load_structured_requires_the_vocabulary(neo4j):
    try:
        graph_load.reset_graph()
        graph_load.create_schema()
        with pytest.raises(ValueError, match="not loaded"):
            graph_load.load_structured()                 # FOCUSES_ON needs Theme nodes
    finally:
        _load_structured_graph()


# =============================================================================
# vocabulary + structured data
# =============================================================================
@destructive
def test_structured_counts(structured):
    stats = graph_load.graph_stats()
    transactions = _csv("transactions.csv")
    assert stats["nodes"] == {
        "Person": len(_csv("people.csv")) + len(_csv("contacts.csv")), "Advisor": len(_csv("advisors.csv")),
        "Client": len(_csv("clients.csv")), "Account": len(_csv("accounts.csv")), "Fund": 10, "Company": 50,
        "Theme": 10, "Concept": 45, "Committee": 2, "Decision": 8, "Transaction": len(transactions)}
    rels = stats["relationships"]
    assert rels["HOLDS"] == len(_csv("holdings.csv"))
    assert rels["INVESTED_IN"] == len(_csv("fund_holdings.csv"))
    assert rels["EXPOSED_TO"] == len(_csv("company_themes.csv"))
    assert rels["HAS_TRANSACTION"] == rels["INVOLVES"] == len(transactions)
    assert rels["HAS_ACCOUNT"] == len(_csv("accounts.csv")) and rels["ADVISED_BY"] == len(_csv("clients.csv"))
    assert rels["MANAGED_BY"] == 10
    assert rels["CONTACT_FOR"] == sum(1 for c in _csv("contacts.csv") if c["client_id"])
    assert rels["WORKS_FOR"] == 10 and rels["MEMBER_OF"] == 12
    assert rels["BROADER"] == 45 and rels["RELATED_TO"] == 7
    assert rels["FOCUSES_ON"] == sum(len([t for t in f["themes"].split("|") if t]) for f in _csv("funds.csv"))
    assert rels["AFFECTS"] == sum(len([x for col in ("affects_funds", "affects_companies", "affects_themes")
                                       for x in d[col].split("|") if x]) for d in _csv("ic_decisions.csv"))
    loaded = {**structured["vocabulary"], **structured["structured"]}
    for key, n in loaded.items():
        assert (stats["nodes"].get(key) or rels.get(key)) == n, key
    _assert_conforms_to_semantic_model()


@destructive
def test_structured_relationships_carry_their_origin(structured):
    rows = db.run("MATCH ()-[r]->() RETURN type(r) AS t, r.origin AS origin, r.rule AS rule, count(*) AS n")
    for r in rows:
        if r["t"] == "OWNS":
            assert (r["origin"], r["rule"]) == ("derived", "R-OWNS"), r
        elif r["t"] == "PURSUANT_TO":
            assert (r["origin"], r["rule"]) == ("structured", "R-TXN-DECISION"), r
        else:
            assert (r["origin"], r["rule"]) == ("structured", None), r


@destructive
def test_dates_are_neo4j_dates_and_numbers_are_numbers(structured):
    rec = db.run_records(
        "MATCH (adv:Advisor {id: 'PER-018'}), (c:Client {id: 'C-001'}), (a:Account {id: 'ACC-1001'}),\n"
        "      (f:Fund {id: 'FND-AIX'}), (d:Decision {id: 'IC-2026-004'}), (t:Transaction {id: 'TXN-000001'}),\n"
        "      (a)-[h:HOLDS]->(f), (f)-[i:INVESTED_IN]->(:Company {id: 'CMP-NVDA'})\n"
        "RETURN adv.start_date AS start, c.client_since AS since, a.opened_date AS opened,\n"
        "       f.inception_date AS inception, d.date AS decided, t.date AS traded, h.as_of AS holding_as_of,\n"
        "       i.since AS invested_since, i.as_of AS invested_as_of, h.market_value AS mv, i.weight AS weight,\n"
        "       t.amount_usd AS amount, f.aum_usd_m AS aum")[0]
    for key in ("start", "since", "opened", "inception", "decided", "traded", "holding_as_of", "invested_since",
                "invested_as_of"):
        assert isinstance(rec[key], Date), key
    assert rec["decided"] == Date(2026, 2, 12) and rec["holding_as_of"] == Date(2026, 9, 30)
    assert rec["invested_since"] == Date(2023, 4, 3) and rec["start"] == Date(2011, 6, 1)
    assert isinstance(rec["mv"], float) and isinstance(rec["amount"], float) and isinstance(rec["aum"], float)
    assert isinstance(rec["weight"], float) and rec["weight"] == 9.94
    holding = next(r for r in _csv("holdings.csv") if (r["account_id"], r["fund_id"]) == ("ACC-1001", "FND-AIX"))
    assert rec["mv"] == float(holding["market_value"])
    # dates compare as dates in Cypher
    since_2026 = db.run("MATCH (t:Transaction) WHERE t.date >= date('2026-01-01') RETURN count(t) AS n")[0]["n"]
    assert since_2026 == sum(1 for t in _csv("transactions.csv") if t["trade_date"] >= "2026-01-01")


@destructive
def test_people_and_their_links(structured):
    people = {r["id"]: r for r in db.run("MATCH (p:Person) RETURN p.id AS id, p.name AS name, "
                                         "p.person_type AS type, p.organization AS org, p.department AS dept, "
                                         "labels(p) AS labels")}
    assert people["PER-001"]["type"] == "employee" and people["PER-001"]["org"] == config.FIRM_NAME
    assert people["PER-026"]["type"] == "client_contact" and people["PER-026"]["org"] == "Hartwell Family Trust"
    assert people["PER-041"]["type"] == "external" and people["PER-041"]["dept"] is None   # empty cell -> no property
    assert sorted(p for p, r in people.items() if "Advisor" in r["labels"]) == [
        r["person_id"] for r in _csv("advisors.csv")]
    roles = {(r["p"], r["c"]): r["role"] for r in db.run(
        "MATCH (p:Person)-[m:MEMBER_OF]->(c:Committee) RETURN p.id AS p, c.id AS c, m.role AS role")}
    assert roles[("PER-001", "COM-IC")] == "Chair" and roles[("PER-006", "COM-RISK")] == "Chair"
    assert roles[("PER-001", "COM-RISK")] == "Member"
    row = db.run("MATCH (:Person {id: 'PER-026'})-[r:CONTACT_FOR]->(c:Client) RETURN r.role AS role, c.id AS c")
    assert row == [{"role": "Trustee", "c": "C-001"}]
    row = db.run("MATCH (:Client {id: 'C-001'})-[:ADVISED_BY]->(a:Advisor) RETURN a.name AS name, a.office AS office")
    assert row == [{"name": "Michael Torres", "office": "Dallas"}]
    assert db.run("MATCH (f:Fund {id: 'FND-PC2'}) RETURN f.ticker AS t")[0]["t"] is None


# =============================================================================
# business rules
# =============================================================================
@destructive
def test_owns_sums_hartwell_holdings(structured):
    client_of = {a["id"]: a["client_id"] for a in _csv("accounts.csv")}
    expected_mv, expected_accounts = Counter(), Counter()
    for h in _csv("holdings.csv"):
        if client_of[h["account_id"]] == config.HERO_CLIENT_ID:
            expected_mv[h["fund_id"]] += float(h["market_value"])
            expected_accounts[h["fund_id"]] += 1
    rows = db.run("MATCH (:Client {id: $cid})-[o:OWNS]->(f:Fund)\n"
                  "RETURN f.id AS fund, o.market_value AS mv, o.accounts AS accounts, o.origin AS origin,\n"
                  "       o.rule AS rule", {"cid": config.HERO_CLIENT_ID})
    assert {r["fund"]: round(r["mv"], 2) for r in rows} == {f: round(v, 2) for f, v in expected_mv.items()}
    assert {r["fund"]: r["accounts"] for r in rows} == dict(expected_accounts)
    assert {(r["origin"], r["rule"]) for r in rows} == {("derived", "R-OWNS")}
    pairs = {(client_of[h["account_id"]], h["fund_id"]) for h in _csv("holdings.csv")}
    assert structured["rules"]["rules"]["R-OWNS"] == len(pairs)
    total = db.run("MATCH (:Client)-[o:OWNS]->(:Fund) RETURN count(o) AS n, sum(o.market_value) AS mv")[0]
    assert total["n"] == len(pairs)
    assert abs(total["mv"] - sum(float(h["market_value"]) for h in _csv("holdings.csv"))) < 0.01


@destructive
def test_pursuant_to_links_trades_to_decisions(structured):
    transactions = _csv("transactions.csv")
    ic004 = {t["id"] for t in transactions if "IC-2026-004" in t["order_reason"]}
    rows = db.run("MATCH (t:Transaction)-[r:PURSUANT_TO]->(:Decision {id: 'IC-2026-004'})\n"
                  "MATCH (a:Account)-[:HAS_TRANSACTION]->(t)\n"
                  "RETURN t.id AS id, a.id AS account, r.origin AS origin, r.rule AS rule")
    assert ic004 and {r["id"] for r in rows} == ic004
    assert len({r["account"] for r in rows}) == len({t["account_id"] for t in transactions if t["id"] in ic004}) == 60
    assert {(r["origin"], r["rule"]) for r in rows} == {("structured", "R-TXN-DECISION")}
    decisions = {d["id"] for d in _csv("ic_decisions.csv")}
    linked = [t for t in transactions if any(d in t["order_reason"] for d in decisions)]
    assert structured["rules"]["rules"]["R-TXN-DECISION"] == len(linked)
    assert graph_load.graph_stats()["relationships"]["PURSUANT_TO"] == len(linked)


@destructive
def test_rules_link_only_existing_decisions_and_are_idempotent(clean):
    db.write("CREATE (:Transaction {id: 'TXN-TEST-1', date: date('2026-03-02'), txn_type: 'BUY', amount_usd: 1000,\n"
             "        order_reason: 'Rebalance per IC-2099-001 and IC-2026-004 (test)'})")
    before = graph_load.graph_stats()["relationships"]
    result = graph_load.apply_rules()
    assert any("IC-2099-001" in w for w in result["warnings"])
    linked = db.run("MATCH (:Transaction {id: 'TXN-TEST-1'})-[:PURSUANT_TO]->(d:Decision) RETURN d.id AS id")
    assert linked == [{"id": "IC-2026-004"}]
    after = graph_load.graph_stats()["relationships"]
    assert after["PURSUANT_TO"] == before["PURSUANT_TO"] + 1
    assert after["OWNS"] == before["OWNS"]
    assert not db.run("MATCH (d:Decision {id: 'IC-2099-001'}) RETURN d")


# =============================================================================
# documents + extractions
# =============================================================================
@destructive
def test_load_document_and_extraction(clean):
    assert graph_load.load_documents([_note_record()], {DOC_ID: "rules"}) == 1
    result = graph_load.load_extractions([_note_extraction()])

    assert result["extractions"] == 1
    assert result["nodes"] == {"Meeting": 1, "matched": 8, "created": 1, "candidates": 1}
    assert result["relationships"] == {"ATTENDED": 3, "DISCUSSED": 3, "MENTIONS": 5, "RECORDS": 1}
    assert result["skipped"] == 5
    warnings = "\n".join(result["warnings"])
    for needle in ("Spaceship", "domain/range of ATTENDED", "OWNS is a derived relationship", "LIKES",
                   "Person:PER-999", f"Company:{UNKNOWN_COMPANY_ID} was not in the graph"):
        assert needle in warnings, needle
    assert len(result["warnings"]) == 7

    doc = db.run_records("MATCH (d:Document {id: $id}) RETURN d", {"id": DOC_ID})[0]["d"]
    assert dict(doc) == {"id": DOC_ID, "title": TITLE, "doc_type": "Meeting Notes", "date": Date(2026, 3, 5),
                         "source_system": "Document Management", "source_path": f"tests/{DOC_ID}.md",
                         "text": NOTE_TEXT, "extraction_engine": "rules"}
    meeting = db.run_records("MATCH (m:Meeting {id: $id}) RETURN m", {"id": MTG_ID})[0]["m"]
    assert dict(meeting) == {"id": MTG_ID, "title": TITLE, "date": Date(2026, 3, 5), "meeting_type": "Research"}

    candidate = db.run("MATCH (p:Person {id: $id}) RETURN p.name AS name, p.candidate AS candidate, labels(p) AS l",
                       {"id": CANDIDATE_ID})
    assert candidate == [{"name": "Jordan Pike", "candidate": True, "l": ["Person"]}]
    assert db.run("MATCH (n) WHERE n.candidate = true RETURN count(n) AS n")[0]["n"] == 1
    created = db.run("MATCH (c:Company {id: $id}) RETURN c.name AS name, c.candidate AS candidate",
                     {"id": UNKNOWN_COMPANY_ID})
    assert created == [{"name": "Zed Holdings", "candidate": None}]
    assert db.run("MATCH (p:Person {name: 'Meredith Calloway'}) RETURN count(p) AS n")[0]["n"] == 1   # resolved, not duplicated

    edges = _extracted_edges()
    assert len(edges) == 12
    for e in edges:
        p = e["props"]
        assert (p["origin"], p["engine"], p["doc_id"]) == ("extracted", "rules", DOC_ID), e
        assert p["evidence"] and p["method"] in {"header", "text", "vocabulary"}, e
    by_triple = {(e["a"], e["type"], e["b"]): e["props"] for e in edges}
    assert by_triple[(MTG_ID, "DISCUSSED", "THM-AI")] == {
        "origin": "extracted", "engine": "rules", "method": "vocabulary", "evidence": GPU_EVIDENCE,
        "doc_id": DOC_ID, "inferred": True, "via": "GPU Capacity"}
    assert by_triple[(DOC_ID, "MENTIONS", "THM-SEMI")]["via"] == "Advanced Packaging"
    assert "inferred" not in by_triple[(MTG_ID, "DISCUSSED", "CMP-NVDA")]
    attendees = db.run("MATCH (p:Person)-[:ATTENDED]->(:Meeting {id: $id})-[:DISCUSSED]->(:Company {name: 'Nvidia'})\n"
                       "RETURN p.name AS name ORDER BY name", {"id": MTG_ID})
    assert [r["name"] for r in attendees] == ["Arjun Mehta", "Jordan Pike", "Meredith Calloway"]
    assert db.run("MATCH (:Document {id: $id})-[r:OWNS|LIKES]->() RETURN count(r) AS n", {"id": DOC_ID})[0]["n"] == 0
    _assert_conforms_to_semantic_model()


@destructive
def test_loading_an_extraction_twice_changes_nothing(clean):
    graph_load.load_documents([_note_record()], {DOC_ID: "rules"})
    graph_load.load_extractions([_note_extraction()])
    first_edges, first_stats = _extracted_edges(), graph_load.graph_stats()

    graph_load.load_documents([_note_record()])               # no engine given: keeps extraction_engine
    again = _note_extraction()
    again.engine = "claude:test"
    for r in again.relationships:
        r.evidence = "changed"
    result = graph_load.load_extractions([again])
    assert result["nodes"]["created"] == 0 and result["nodes"]["matched"] == 9
    assert _extracted_edges() == first_edges                  # existing edges keep their provenance
    assert graph_load.graph_stats() == first_stats
    assert db.run("MATCH (d:Document {id: $id}) RETURN d.extraction_engine AS e", {"id": DOC_ID}) == [{"e": "rules"}]


@destructive
def test_explicit_link_wins_over_inferred_one(clean):
    doc_id = "DOC-TEST-MN-02"
    graph_load.load_documents([_note_record(doc_id)])
    inferred = RelationshipRef(f"Document:{doc_id}", "MENTIONS", "Theme:THM-AI", evidence=GPU_EVIDENCE,
                               method="vocabulary", properties={"inferred": True, "via": "GPU Capacity"})
    explicit = RelationshipRef(f"Document:{doc_id}", "MENTIONS", "Theme:THM-AI", evidence="AI infrastructure",
                               method="text")
    ex = Extraction(doc_id=doc_id, engine="claude:test", document={"id": doc_id},
                    entities=[_entity("Theme", "THM-AI", "AI Infrastructure")], relationships=[inferred, explicit])
    result = graph_load.load_extractions([ex])
    assert result["warnings"] == []
    rows = db.run("MATCH (:Document {id: $id})-[r:MENTIONS]->(:Theme {id: 'THM-AI'}) RETURN properties(r) AS p",
                  {"id": doc_id})
    assert len(rows) == 1
    assert rows[0]["p"]["evidence"] == "AI infrastructure" and "inferred" not in rows[0]["p"]
    # a document loaded without an engine gets the extraction's engine
    assert db.run("MATCH (d:Document {id: $id}) RETURN d.extraction_engine AS e", {"id": doc_id}) == [
        {"e": "claude:test"}]


@destructive
def test_extraction_for_a_missing_document_is_reported(clean):
    ex = Extraction(doc_id="DOC-TEST-GHOST", engine="rules", document={"id": "DOC-TEST-GHOST"},
                    entities=[_entity("Company", "CMP-NVDA", "Nvidia")],
                    relationships=[RelationshipRef("Document:DOC-TEST-GHOST", "MENTIONS", "Company:CMP-NVDA",
                                                   evidence="Nvidia", method="text")])
    result = graph_load.load_extractions([ex])
    assert result["skipped"] == 1 and result["relationships"] == {"MENTIONS": 0}
    assert any("load_documents" in w for w in result["warnings"])
    assert not db.run("MATCH (d:Document {id: 'DOC-TEST-GHOST'}) RETURN d")


@destructive
def test_fulltext_indexes(clean):
    graph_load.load_documents([_note_record()])
    hits = db.run("CALL db.index.fulltext.queryNodes('documentText', $q) YIELD node, score RETURN node.id AS id",
                  {"q": '"advanced packaging"'})
    assert [h["id"] for h in hits] == [DOC_ID]
    assert not db.run("CALL db.index.fulltext.queryNodes('documentText', $q) YIELD node RETURN node.id AS id",
                      {"q": '"liquid cooling"'})
    names = db.run("CALL db.index.fulltext.queryNodes('entityNames', $q) YIELD node RETURN node.id AS id LIMIT 1",
                   {"q": "Hartwell~"})
    assert names and names[0]["id"] in {"C-001", "PER-026", "PER-027"}


# =============================================================================
# value handling (no database)
# =============================================================================
def test_decision_ids_are_found_as_whole_tokens():
    found = graph_load.DECISION_ID.findall("Model rebalance per IC-2026-004 (see IC-2025-019); not XIC-2026-005 "
                                           "or IC-2026-0041 or IC-26-001")
    assert found == ["IC-2026-004", "IC-2025-019"]


def test_property_values_are_neo4j_compatible():
    from datetime import date, datetime
    assert graph_load._date("2026-03-05") == date(2026, 3, 5)
    assert graph_load._date("2026-03-05T10:30:00-05:00") == date(2026, 3, 5)
    assert graph_load._date(datetime(2026, 3, 5, 10, 30)) == date(2026, 3, 5)
    assert graph_load._date("") is None and graph_load._date(None) is None
    with pytest.raises(ValueError):
        graph_load._date("March 5, 2026")
    assert graph_load._rel_props({"inferred": True, "via": "GPU Capacity", "origin": "spoofed", "skip": None,
                                  "tags": ["a", "b"], "mixed": [1, 2.5], "nested": {"k": 1}}) == {
        "inferred": True, "via": "GPU Capacity", "tags": ["a", "b"], "mixed": [1.0, 2.5], "nested": '{"k": 1}'}
    assert graph_load._committees("COM-IC:Chair|COM-RISK:Member|COM-X") == [
        ("COM-IC", "Chair"), ("COM-RISK", "Member"), ("COM-X", None)]


# =============================================================================
# chunking (no database)
# =============================================================================
def test_chunk_text_never_returns_empty_chunks():
    assert chunk_text("") == []
    assert chunk_text(" \n\n \t\n") == []
    assert chunk_text("Hello.") == ["Hello."]


def test_short_text_is_a_single_normalized_chunk():
    text = "Investment Committee Meeting\r\nDate: 2026-01-15   \r\n\r\n\r\nWe remain bullish on Nvidia.  \n"
    assert chunk_text(text) == ["Investment Committee Meeting\nDate: 2026-01-15\n\nWe remain bullish on Nvidia."]


def test_paragraphs_are_packed_with_one_paragraph_of_overlap():
    paragraphs = [f"Paragraph {i}: " + " ".join(f"word{i}-{j}" for j in range(15)) for i in range(10)]
    chunks = chunk_text("\n\n".join(paragraphs), max_chars=400, overlap_paragraphs=1)
    assert len(chunks) > 2 and all(len(c) <= 400 for c in chunks)
    parts = [c.split("\n\n") for c in chunks]
    for prev, nxt in zip(parts, parts[1:]):
        assert nxt[0] == prev[-1]                      # each chunk repeats the previous chunk's last paragraph
        assert len(nxt) > 1                            # ... and adds new content
    assert list(dict.fromkeys(p for ps in parts for p in ps)) == paragraphs


def test_without_overlap_chunks_partition_the_paragraphs():
    paragraphs = [f"Paragraph {i}. " + "Lorem ipsum dolor sit amet. " * (i % 4 + 1) for i in range(12)]
    text = "\n\n".join(p.strip() for p in paragraphs)
    chunks = chunk_text(text, max_chars=300, overlap_paragraphs=0)
    assert "\n\n".join(chunks) == text
    assert all(len(c) <= 300 for c in chunks)


def test_long_paragraph_is_split_at_sentence_boundaries():
    sentences = [f"Sentence {i} says demand for GPU capacity keeps growing." for i in range(40)]
    paragraph = " ".join(sentences)
    chunks = chunk_text(paragraph, max_chars=300, overlap_paragraphs=0)
    assert len(chunks) > 1 and all(len(c) <= 300 for c in chunks)
    assert all(c.startswith("Sentence ") and c.endswith(".") for c in chunks)
    assert " ".join(chunks) == paragraph


def test_sentence_splitting_keeps_abbreviations_and_initials_together():
    sentence = "Dr. Leah Goldberg and John F. Kennedy reviewed the U.S. queue, e.g. Texas sites. "
    chunks = chunk_text(sentence * 12, max_chars=200, overlap_paragraphs=0)
    assert all(len(c) <= 200 for c in chunks)
    assert all(c.startswith("Dr. Leah Goldberg") and c.endswith("Texas sites.") for c in chunks)


def test_long_bullet_lists_split_between_lines():
    lines = [f"- Item {i}: a covenant test or maintenance covenant observation." for i in range(30)]
    chunks = chunk_text("Key Findings:\n" + "\n".join(lines), max_chars=250, overlap_paragraphs=0)
    assert all(len(c) <= 250 for c in chunks)
    assert all(line.startswith(("- Item", "Key Findings:")) for c in chunks for line in c.split("\n"))


def test_overlong_words_are_split_by_characters():
    assert [len(c) for c in chunk_text("x" * 2000, max_chars=900)] == [900, 900, 200]
    chunks = chunk_text("short " + "y" * 50 + " tail", max_chars=20, overlap_paragraphs=0)
    assert all(0 < len(c) <= 20 for c in chunks)
    assert "".join(chunks).replace(" ", "") == ("short" + "y" * 50 + "tail")


def test_chunk_text_rejects_bad_arguments():
    with pytest.raises(ValueError):
        chunk_text("text", max_chars=0)
    with pytest.raises(ValueError):
        chunk_text("text", overlap_paragraphs=-1)


@pytest.mark.parametrize("seed", range(25))
def test_chunk_text_invariants_on_random_text(seed):
    rng = random.Random(seed)
    words = ["GPU", "capacity", "Nvidia", "power", "demand", "Dr.", "U.S.", "e.g.", "rate", "cuts", "covenant",
             "data", "center", "AI", "infrastructure", "pipeline", "LNG", "duration"]
    paragraphs = []
    for _ in range(rng.randint(1, 12)):
        lines = []
        for _ in range(rng.randint(1, 4)):
            sentences = [" ".join(rng.choice(words) for _ in range(rng.randint(3, 25))) + rng.choice(".!?")
                         for _ in range(rng.randint(1, 6))]
            lines.append(" ".join(sentences))
        paragraphs.append("\n".join(lines))
    text = ("\n\n" + "\n" * rng.randint(0, 2)).join(paragraphs)
    max_chars, overlap = rng.randint(40, 600), rng.randint(0, 2)
    chunks = chunk_text(text, max_chars=max_chars, overlap_paragraphs=overlap)
    assert chunks and all(c.strip() == c and 0 < len(c) <= max_chars for c in chunks)
    assert set(" ".join(chunks).split()) == set(text.split())
    exact = chunk_text(text, max_chars=max_chars, overlap_paragraphs=0)
    assert " ".join(exact).split() == text.split()      # nothing lost, nothing duplicated, order kept


def test_corpus_bodies_chunk_within_the_limit():
    bodies = sorted(config.SOURCE_DOCS_DIR.glob("*.txt"))
    if not bodies:
        pytest.skip("no authored document bodies yet")
    for path in bodies:
        text = path.read_text(encoding="utf-8")
        chunks = chunk_text(text)
        assert all(0 < len(c) <= 900 for c in chunks), path.name
        assert set(" ".join(chunks).split()) == set(text.split()), path.name


# =============================================================================
# embeddings + vector index
# =============================================================================
EMBED_DOCS = {
    "DOC-TEST-EMB-1": ("Research Report", "Liquid cooling for dense GPU racks", "2026-05-01",
                       "Direct-to-chip liquid cooling lets operators run GPU racks above 100 kW without hot spots."),
    "DOC-TEST-EMB-2": ("Research Report", "Municipal bond outlook", "2026-05-02",
                       "Tax-exempt municipal bonds offer attractive after-tax yields; we keep portfolio duration "
                       "near five years."),
    "DOC-TEST-EMB-3": ("Email", "Zero trust rollout", "2026-05-03",
                       "Endpoint security and identity controls are consolidating onto fewer cybersecurity "
                       "platforms."),
}
QUESTIONS = {
    "Which note covers tax-exempt municipal bonds and duration?": "DOC-TEST-EMB-2",
    "How can data centers cool high-density GPU racks?": "DOC-TEST-EMB-1",
    "Are cybersecurity vendors consolidating endpoint and identity tools?": "DOC-TEST-EMB-3",
}


def _embed_records() -> list[DocumentRecord]:
    return [DocumentRecord(doc_id=doc_id, doc_type=doc_type, title=title, date=day, source_system="Research Portal"
                           if doc_type == "Research Report" else "Email", source_path=f"tests/{doc_id}",
                           text=f"{title}\n\n{body}", body_offset=len(title) + 2)
            for doc_id, (doc_type, title, day, body) in EMBED_DOCS.items()]


def test_embeddings_are_normalized_384_floats():
    vector = embed.embed_query("AI infrastructure exposure")
    assert len(vector) == config.EMBED_DIM and all(isinstance(x, float) for x in vector)
    assert math.isclose(math.sqrt(sum(x * x for x in vector)), 1.0, abs_tol=1e-3)
    passages = embed.embed_passages(["GPU capacity", "municipal bonds"])
    assert [len(v) for v in passages] == [config.EMBED_DIM] * 2
    assert embed.embed_passages([]) == []


@destructive
def test_embed_and_vector_search_round_trip(clean, monkeypatch):
    db.write("DROP INDEX chunkEmbedding IF EXISTS")
    with pytest.raises(RuntimeError, match="kgdemo.embed"):
        embed.vector_search("anything")

    records = _embed_records()
    graph_load.load_documents(records)
    assert embed.build_chunks(batch_size=2) == 3                 # several batches
    chunks = db.run_records("MATCH (c:Chunk)-[r:PART_OF]->(d:Document) RETURN c, r, d.id AS doc ORDER BY c.id")
    assert [rec["c"]["id"] for rec in chunks] == [f"{r.doc_id}#00" for r in records]
    for rec, record in zip(chunks, records):
        chunk = dict(rec["c"])
        assert (chunk["doc_id"], chunk["seq"], chunk["text"]) == (record.doc_id, 0, record.text)
        assert len(chunk["embedding"]) == config.EMBED_DIM
        assert rec["doc"] == record.doc_id and dict(rec["r"]) == {"origin": "structured"}

    index = db.run("SHOW VECTOR INDEXES YIELD name, state, labelsOrTypes, properties, options RETURN *")
    assert len(index) == 1 and index[0]["name"] == "chunkEmbedding" and index[0]["state"] == "ONLINE"
    assert (index[0]["labelsOrTypes"], index[0]["properties"]) == (["Chunk"], ["embedding"])
    cfg = index[0]["options"]["indexConfig"]
    assert cfg["vector.dimensions"] == 384 and cfg["vector.similarity_function"].lower() == "cosine"

    for question, expected in QUESTIONS.items():
        hits = embed.vector_search(question, k=3)
        assert [h["doc_id"] for h in hits][0] == expected, (question, hits)
        assert len(hits) == 3 and {h["doc_id"] for h in hits} == set(EMBED_DOCS)
        assert [h["score"] for h in hits] == sorted((h["score"] for h in hits), reverse=True)
    top = embed.vector_search("tax-exempt municipal bonds", k=1)
    assert top == [{"chunk_id": "DOC-TEST-EMB-2#00", "text": records[1].text, "score": top[0]["score"],
                    "doc_id": "DOC-TEST-EMB-2", "title": "Municipal bond outlook", "doc_type": "Research Report",
                    "date": "2026-05-02", "source_system": "Research Portal"}]

    assert embed.build_chunks() == 3                              # rebuilding replaces, never duplicates
    assert db.run("MATCH (c:Chunk) RETURN count(c) AS n")[0]["n"] == 3

    def fail(texts):
        raise RuntimeError("embedding model unavailable")
    monkeypatch.setattr(embed, "embed_passages", fail)
    with pytest.raises(RuntimeError, match="unavailable"):
        embed.build_chunks()
    assert db.run("MATCH (c:Chunk) RETURN count(c) AS n")[0]["n"] == 3   # a failed rebuild keeps the old chunks


# =============================================================================
# command lines
# =============================================================================
@destructive
def test_graph_load_cli_structured_only(neo4j, capsys):
    assert graph_load.main(["--structured-only"]) == 0
    out = capsys.readouterr().out
    assert "R-OWNS" in out and "R-TXN-DECISION" in out
    nodes = graph_load.graph_stats()["nodes"]
    assert (nodes["Person"], nodes["Client"], nodes["Fund"], nodes["Decision"]) == (len(w.people()),
                                                                                len(w.CLIENTS), 10, 8)
    assert "Document" not in nodes and "Chunk" not in nodes


def test_build_refuses_claude_without_credentials(monkeypatch, capsys):
    monkeypatch.setattr(config, "llm_available", lambda: False)
    assert build.main(["--engine", "claude"]) == 2
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err


def test_build_rejects_unknown_engines():
    with pytest.raises(SystemExit):
        build.main(["--engine", "gpt"])
