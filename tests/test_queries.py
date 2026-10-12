"""The demo queries against the built graph (read-only)."""
from __future__ import annotations

import pytest

from kgdemo import queries
from kgdemo import world as w
from kgdemo.ontology import load_ontology
from kgdemo.viz import primary_label


def test_graph_size_matches_the_source_data(graph):
    counts = {r["label"]: r["n"] for r in graph.run("MATCH (n) UNWIND labels(n) AS label RETURN label, count(*) AS n")}
    assert counts["Person"] == len(w.people())
    assert counts["Company"] == len(w.companies()) == 50
    assert counts["Meeting"] == len(w.meetings()) == 21
    assert counts["Document"] == 101
    assert counts["Theme"] == 10
    assert counts["Client"] == len(w.CLIENTS)
    assert counts["Advisor"] == len(w.ADVISORS)
    assert counts["Account"] == len(w.accounts())
    assert counts["Transaction"] == len(w.transactions())
    assert counts.get("Chunk", 0) > 101


def test_graph_conforms_to_the_semantic_model(graph):
    onto = load_ontology()
    labels = {r["label"] for r in graph.run("CALL db.labels() YIELD label RETURN label")}
    assert labels <= set(onto.entities)
    types = {r["t"] for r in graph.run("CALL db.relationshipTypes() YIELD relationshipType AS t RETURN t")}
    assert types <= set(onto.relationships)
    for t in types:
        pairs = graph.run(f"MATCH (a)-[r:{t}]->(b) RETURN DISTINCT labels(a) AS a, labels(b) AS b")
        for p in pairs:
            assert onto.allows(t, primary_label(p["a"]) if "Advisor" not in p["a"] else "Advisor",
                               primary_label(p["b"])), (t, p)


def test_no_candidate_entities_in_the_offline_build(graph):
    assert graph.run("MATCH (n) WHERE n.candidate = true RETURN count(n) AS n")[0]["n"] == 0


def test_brief_query_1_finds_documents_without_the_literal_phrase(graph):
    rows = graph.run(queries.by_id("brief-1-theme-documents").cypher)
    ids = {r["d"]["id"] for r in rows}
    assert "DOC-MN-03" in ids
    assert {"DOC-RR-03", "DOC-RR-04", "DOC-RR-08"} <= ids
    for doc_id in ("DOC-RR-03", "DOC-RR-04", "DOC-RR-08"):
        text = graph.run("MATCH (d:Document {id: $id}) RETURN d.text AS t", {"id": doc_id})[0]["t"]
        assert "ai infrastructure" not in text.lower()


def test_brief_query_2_people_who_discussed_nvidia(graph):
    rows = graph.run(queries.by_id("brief-2-people-nvidia").cypher)
    names = {r["p"]["name"] for r in rows}
    assert {"Douglas Whitfield", "Meredith Calloway"} <= names


def test_brief_query_3_trace_investment_impact(graph):
    rows = graph.run(queries.by_id("brief-3-investment-impact").cypher)
    triples = {(r["c"]["name"], r["f"]["name"], r["co"]["name"]) for r in rows}
    assert ("Hartwell Family Trust", "Arbor Peak AI Infrastructure Fund", "Nvidia") in triples


@pytest.mark.parametrize("q", queries.QUERIES, ids=lambda q: q.id)
def test_every_demo_query_returns_results(graph, q):
    assert graph.run(q.cypher, q.params), q.id


def test_look_through_exposure_matches_the_simulation(graph):
    q = queries.by_id("look-through-exposure")
    rows = graph.run(q.cypher, q.params)
    assert len(rows) == len(w.CLIENTS)
    for r in rows:
        expected = w.look_through_exposure(w.client_by_name(r["client"])["id"])["pct"]
        assert abs(r["exposure_pct"] - expected) < 0.06, r
    assert all(r["exposure_pct"] < 15.0 for r in rows)


def test_hidden_nvidia_exposure(graph):
    q = queries.by_id("hidden-nvidia-exposure")
    funds = {r["fund"] for r in graph.run(q.cypher, q.params)}
    assert funds == {"Arbor Peak AI Infrastructure Fund", "Arbor Peak Global Technology Fund"}


def test_decision_implementation_counts(graph):
    q = queries.by_id("decision-implementation")
    rows = {r["decision"]: r for r in graph.run(q.cypher, q.params)}
    ic004 = [t for t in w.transactions() if "IC-2026-004" in t["order_reason"]]
    assert rows["IC-2026-004"]["trades"] == len(ic004)
    assert rows["IC-2026-004"]["accounts"] == len({t["account_id"] for t in ic004})
    assert rows["IC-2026-004"]["clients"] == len({w.account_by_id(t["account_id"])["client_id"] for t in ic004})
    assert {"IC-2026-006", "IC-2026-011", "IC-2026-013"} <= set(rows)


def test_decision_provenance_reaches_memo_research_and_meetings(graph):
    nodes, edges = graph.run_graph(queries.by_id("decision-provenance").cypher,
                                   queries.by_id("decision-provenance").params)
    ids = {n["properties"].get("id") for n in nodes}
    assert {"IC-2026-004", "DOC-ICM-03", "DOC-RR-01", "MTG-20260115-INVESTMENT-COMMITTEE-MEETING"} <= ids


def test_brief_sample_path(graph):
    q = queries.by_id("brief-sample-path")
    nodes, _ = graph.run_graph(q.cypher, q.params)
    labels = {primary_label(n["labels"]) for n in nodes}
    assert {"Client", "Fund", "Company", "Document", "Meeting", "Committee"} <= labels


def test_semantic_layer_beats_keyword_search(graph):
    q = queries.by_id("keyword-vs-semantic")
    rows = graph.run(q.cypher, q.params)
    missed = [r for r in rows if not r["found_by_keyword"]]
    assert len(missed) >= 10
    assert all(r["matched_via_concepts"] for r in missed)


def test_extracted_relationships_keep_evidence(graph):
    rows = graph.run("MATCH ()-[r]->() WHERE r.origin = 'extracted' RETURN count(r) AS n, "
                     "sum(CASE WHEN r.evidence IS NULL OR r.doc_id IS NULL THEN 1 ELSE 0 END) AS missing")[0]
    assert rows["n"] > 500
    assert rows["missing"] == 0


def test_time_window_excludes_old_documents(graph):
    q = queries.by_id("time-window")
    rows = {r["in_window"]: r["documents"] for r in graph.run(q.cypher, q.params)}
    assert rows.get(True, 0) > 0 and rows.get(False, 0) >= 1
