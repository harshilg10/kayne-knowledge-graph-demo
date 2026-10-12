"""Standard RAG vs Graph-RAG on the built graph (offline: no LLM)."""
from __future__ import annotations

from kgdemo import rag
from kgdemo import manifest as mf
from kgdemo import world as w

Q_IMPACT = rag.PRESET_QUESTIONS[0]
Q_PROVENANCE = rag.PRESET_QUESTIONS[1]


def test_entity_linking_for_the_brief_questions():
    linked = rag.link_question(Q_IMPACT)
    assert [c["name"] for c in linked["clients"]] == ["Hartwell Family Trust"]
    assert [t["name"] for t in linked["themes"]] == ["AI Infrastructure"]
    assert linked["since"] == "2025-09-30"
    assert rag.choose_strategy(linked) == "client_theme_impact"

    linked = rag.link_question(Q_PROVENANCE)
    assert [t["name"] for t in linked["themes"]] == ["AI Infrastructure"]
    assert linked["direction"] == "increase" and "provenance" in linked["intent"]
    assert rag.choose_strategy(linked) == "decision_provenance"


def test_concepts_link_to_their_theme():
    linked = rag.link_question("Who are our experts on liquid cooling?")
    assert linked["concepts"][0]["name"] == "Liquid Cooling"
    assert rag.choose_strategy(linked) == "expertise"


def test_graph_rag_client_impact(graph):
    res = rag.graph_rag(Q_IMPACT, use_llm=False)
    kinds = {f.kind for f in res.facts}
    assert {"client", "exposure", "holding", "decision", "trade", "client_meeting", "client_document",
            "internal_document", "meeting", "research"} <= kinds
    client_docs = {f.data["id"] for f in res.facts if f.kind == "client_document"}
    internal_docs = {f.data["id"] for f in res.facts if f.kind == "internal_document"}
    assert {"DOC-EM-08", "DOC-CRM-03"} <= client_docs
    assert "DOC-ICM-07" in internal_docs and not (client_docs & internal_docs)
    assert not any(d.startswith("DOC-MN-15") for d in client_docs | internal_docs)  # reported as a client meeting
    exposure = next(f for f in res.facts if f.kind == "exposure")
    assert abs(exposure.data["pct"] - w.look_through_exposure("C-001")["pct"]) < 0.06
    decisions = {f.data["id"]: f.data for f in res.facts if f.kind == "decision"}
    assert {"IC-2026-004", "IC-2026-006", "IC-2026-011", "IC-2026-013"} <= set(decisions)
    assert all(decisions[d]["affects_client"] for d in ("IC-2026-004", "IC-2026-006", "IC-2026-011", "IC-2026-013"))
    trades = [f.data for f in res.facts if f.kind == "trade"]
    hero_buy = next(t for t in w.transactions() if t["account_id"] == "ACC-1001" and t["txn_type"] == "BUY"
                    and "IC-2026-004" in t["order_reason"])
    assert any(t["date"] == hero_buy["date"] == "2026-02-17" and abs(t["amount"] - hero_buy["amount_usd"]) < 0.005
               and t["type"] == "BUY" for t in trades)
    assert all(t["date"] >= "2025-09-30" for t in trades)
    assert res.answer_engine == "template" and "IC-2026-004" in res.answer
    assert res.nodes and res.edges


def test_company_exposure_lists_client_communications_only(graph):
    res = rag.graph_rag(rag.PRESET_QUESTIONS[2], use_llm=False)
    assert res.strategy == "company_exposure" and res.nodes
    comms = [f for f in res.facts if f.kind == "client_communication"]
    assert comms and all(f.data["type"] in ("CRM Note", "Email", "Meeting Notes") for f in comms)
    assert not any(f.data["id"] in ("DOC-ICM-07", "DOC-EM-16", "DOC-MN-09") for f in comms)


def test_graph_rag_decision_provenance(graph):
    res = rag.graph_rag(Q_PROVENANCE, use_llm=False)
    decisions = [f.data["id"] for f in res.facts if f.kind == "decision"]
    assert "IC-2026-004" in decisions
    assert all(f.data["direction"] == "increase" for f in res.facts if f.kind == "decision")
    cited = {f.data["id"] for f in res.facts if f.kind == "cited" and f.data["decision"] == "IC-2026-004"}
    assert {"DOC-RR-01", "DOC-RR-02", "DOC-RR-03", "DOC-RR-04"} <= cited
    meeting = next(f for f in res.facts if f.kind == "decision_meeting" and f.data["decision"] == "IC-2026-004")
    assert "Elena Vasquez" in meeting.data["attendees"]
    prior = {f.data["id"] for f in res.facts if f.kind == "prior_meeting" and f.data["decision"] == "IC-2026-004"}
    assert "MTG-20260115-INVESTMENT-COMMITTEE-MEETING" in prior
    # provenance of the Cobalt Ridge loan is about Cobalt Ridge / the credit fund, not every AI meeting
    prior_006 = [f.data for f in res.facts if f.kind == "prior_meeting" and f.data["decision"] == "IC-2026-006"]
    assert prior_006 and all(set(m["topics"]) & {"Cobalt Ridge Data Centers", "Arbor Peak Private Credit Fund II"}
                             for m in prior_006)
    assert "MTG-20260115-INVESTMENT-COMMITTEE-MEETING" not in {m["id"] for m in prior_006}
    impl = next(f for f in res.facts if f.kind == "implementation" and f.data["decision"] == "IC-2026-004")
    ic004 = [t for t in w.transactions() if "IC-2026-004" in t["order_reason"]]
    assert impl.data["accounts"] == len({t["account_id"] for t in ic004}) == mf.F["ic004_accounts"]


def test_every_preset_answers(graph):
    for q in rag.PRESET_QUESTIONS:
        res = rag.graph_rag(q, use_llm=False)
        assert res.facts, q
        assert res.answer.strip(), q


def test_standard_rag_offline(graph):
    res = rag.standard_rag(Q_IMPACT, use_llm=False)
    assert len(res.chunks) == 6
    assert res.answer_engine == "extractive" and res.answer.strip()
    assert all(c["doc_id"].startswith("DOC-") for c in res.chunks)


def test_graph_context_covers_more_than_vector_context(graph):
    for q in rag.PRESET_QUESTIONS[:2]:
        gr = rag.graph_rag(q, use_llm=False)
        std = rag.standard_rag(q, use_llm=False)
        items = rag.key_facts(gr)
        assert len(items) >= 5
        cov_gr, cov_std = rag.coverage(items, gr.context), rag.coverage(items, std.context)
        assert all(cov_gr), [it["label"] for it, ok in zip(items, cov_gr) if not ok]
        assert sum(cov_std) < sum(cov_gr)
