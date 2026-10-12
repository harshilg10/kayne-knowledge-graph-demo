"""The web app's API (kgdemo/server.py) against the built graph. Read-only except the DOC-LIVE write test."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from kgdemo import config, queries, rag
from kgdemo import neo4j_client as db
from kgdemo import world as w
from kgdemo.server import UI_QUERIES, _inline_params, app

client = TestClient(app)


def test_inline_params_writes_safe_literals():
    cypher = "MATCH (c {name: $client, id: $client_id}) WHERE d >= date($as_of) RETURN c"
    out = _inline_params(cypher, {"client": "O'Brien \\ Co", "client_id": "C-1", "as_of": "2026-09-30"})
    assert out == ("MATCH (c {name: 'O\\'Brien \\\\ Co', id: 'C-1'}) WHERE d >= date('2026-09-30') RETURN c")


def test_status_and_overview(graph):
    s = client.get("/api/status").json()
    assert s["neo4j"]["ok"] and s["hero"]["client_name"] == "Hartwell Family Trust"
    o = client.get("/api/overview").json()
    assert o["book"]["clients"] == len(w.CLIENTS) and o["book"]["documents"] == 101
    assert o["graph"]["ok"] and o["graph"]["labels"]["Client"] == len(w.CLIENTS)


def test_structured_tables_and_hero_filter():
    idx = client.get("/api/structured").json()
    names = [t["name"] for s in idx["systems"] for t in s["tables"]]
    assert len(names) == 13 and "fund_nav.csv" in names
    tx = client.get("/api/structured/transactions.csv?hero=true").json()
    hero_accounts = {a["id"] for a in w.accounts_for_client(config.HERO_CLIENT_ID)}
    assert tx["rows"] and all(r["account_id"] in hero_accounts for r in tx["rows"]) and tx["filtered"]
    assert client.get("/api/structured/clients.csv?hero=true").json()["rows"][0]["id"] == config.HERO_CLIENT_ID
    assert client.get("/api/structured/nope.csv").status_code == 404


def test_documents_and_originals():
    docs = client.get("/api/documents").json()
    assert len(docs["documents"]) == 101 and sum(docs["counts"].values()) == 101
    hero = client.get(f"/api/documents/{config.HERO_DOC_ID}").json()
    assert hero["text"].startswith("Investment Committee Meeting") and "Douglas Whitfield" in hero["text"]
    original = client.get("/api/documents/DOC-EM-08/original")
    assert original.status_code == 200 and original.content.startswith(b"From: Michael Torres")
    assert client.get("/api/documents/DOC-XX-99").status_code == 404


def test_document_graph_has_a_browser_query(graph):
    g = client.get(f"/api/documents/{config.HERO_DOC_ID}/graph").json()
    assert g["nodes"] and f"'{config.HERO_DOC_ID}'" in g["browser_cypher"] and "$" not in g["browser_cypher"]


def test_model_and_keyword_comparison(graph):
    m = client.get("/api/model").json()
    assert len(m["schema"]["nodes"]) == 13 and all("position" in n for n in m["schema"]["nodes"])
    assert any(t["name"] == "AI Infrastructure" for t in m["themes"])
    k = client.get("/api/model/keyword-vs-semantic").json()
    assert k["semantic_total"] - k["missed_total"] <= k["keyword_total"] and k["missed_total"] == len(k["missed"])
    assert all(d["doc_id"].startswith("DOC-") and d["via"] for d in k["missed"])


def test_extract_hero_note(graph):
    r = client.post("/api/extract", json={"doc_id": config.HERO_DOC_ID, "engine": "rules"}).json()
    names = {e["name"] for e in r["entities"]}
    assert {"Douglas Whitfield", "Meredith Calloway", "Nvidia", "AI Infrastructure", "GPU Capacity"} <= names
    types = {(x["source"].split(" (")[0], x["type"]) for x in r["relationships"]}
    assert ("Douglas Whitfield", "ATTENDED") in types and r["in_graph"]
    keys = {n["id"] for n in r["graph"]["nodes"]}
    assert all(e["source"] in keys and e["target"] in keys for e in r["graph"]["edges"])
    assert client.post("/api/extract", json={"doc_id": "DOC-XX-99"}).status_code == 404
    assert client.post("/api/extract", json={"doc_id": config.HERO_DOC_ID, "engine": "gpt"}).status_code == 422


def test_queries_run_and_hand_off_to_neo4j_browser(graph):
    listed = client.get("/api/queries").json()
    assert [q["id"] for q in listed["queries"]] == [qid for qid, _ in UI_QUERIES]
    for q in listed["queries"]:
        assert "$" not in q["browser_cypher"], q["id"]
        # the Neo4j Browser version runs as-is and returns the same data
        assert db.run(q["browser_cypher"]), q["id"]
        r = client.post(f"/api/queries/{q['id']}/run", json={"params": {}})
        assert r.status_code == 200, q["id"]
        body = r.json()
        assert body.get("rows") or body.get("graph", {}).get("nodes"), q["id"]
    assert client.post("/api/queries/schema/run", json={"params": {}}).status_code == 404


def test_look_through_query_matches_the_world(graph):
    rows = client.post("/api/queries/look-through-exposure/run", json={"params": {}}).json()["rows"]
    hero = next(r for r in rows if r["client"] == "Hartwell Family Trust")
    assert abs(hero["exposure_pct"] - w.look_through_exposure(config.HERO_CLIENT_ID)["pct"]) < 0.06


def test_rag_compare(graph):
    r = client.post("/api/rag", json={"question": rag.PRESET_QUESTIONS[0]}).json()
    assert r["standard"]["answer"] and r["graph"]["answer"] and r["graph"]["graph"]["nodes"]
    cov = r["coverage"]
    assert cov["graph"] == cov["total"] and cov["standard"] < cov["graph"]
    assert client.post("/api/rag", json={"question": "x"}).status_code == 422


def test_value_cards(graph):
    cards = client.get("/api/value").json()["cards"]
    assert [c["title"] for c in cards] == ["Better discovery", "Explainability", "Data integration", "AI readiness",
                                           "Institutional knowledge"]
    assert all(c["proof"] for c in cards)


def test_unknown_api_path_is_a_json_404():
    r = client.get("/api/does-not-exist")
    assert r.status_code == 404 and r.json()["detail"].startswith("no endpoint")


@pytest.mark.destructive
def test_write_pasted_note(graph):
    note = ("Investment Committee Meeting\n\nDate: 2026-09-24\n\nParticipants:\nElena Vasquez\n\n"
            "Discussion:\nElena Vasquez raised concerns about liquid cooling lead times at Vertiv.")
    body = {"text": note, "engine": "rules"}
    r = client.post("/api/extract", json=body).json()
    assert r["doc_id"].startswith("DOC-LIVE-") and not r["in_graph"]
    assert client.post("/api/extract/write", json=body).json()["doc_id"] == r["doc_id"]
    assert client.post("/api/extract", json=body).json()["in_graph"]
    db.write("MATCH (d:Document {id: $id}) DETACH DELETE d", {"id": r["doc_id"]})
    db.write(f"MATCH (m:Meeting {{id: 'MTG-20260924-INVESTMENT-COMMITTEE-MEETING'}}) DETACH DELETE m")
