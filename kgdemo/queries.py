"""Named demo queries (Cypher). Used by the app, the Neo4j Browser query pack and the tests.

The first three are the queries from the demo brief, verbatim. The rest show what
the semantic model makes possible: explainable theme search, look-through
exposure, decision provenance, expertise discovery and path explanations.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .config import AS_OF_DATE

AS_OF = AS_OF_DATE.isoformat()


@dataclass(frozen=True)
class DemoQuery:
    id: str
    title: str
    question: str                 # the business question in plain English
    cypher: str
    params: dict = field(default_factory=dict)
    shows: str = "table"          # table | graph | both
    talking_point: str = ""
    graph_cypher: str = ""        # optional richer query for the graph view (the table always shows `cypher`)


QUERIES: list[DemoQuery] = [
    DemoQuery(
        id="brief-1-theme-documents",
        title="Find all documents discussing a theme (from the brief)",
        question="Which documents discuss AI Infrastructure?",
        cypher="MATCH (d:Document)-[:MENTIONS]->(t:Theme {name:'AI Infrastructure'})\nRETURN d",
        shows="both",
        graph_cypher="MATCH p = (d:Document)-[:MENTIONS]->(t:Theme {name:'AI Infrastructure'})\nRETURN p",
        talking_point="Returns documents that never literally say 'AI infrastructure' - the semantic model maps "
                      "'GPU capacity', 'hyperscaler capex' or 'liquid cooling' to the theme.",
    ),
    DemoQuery(
        id="brief-2-people-nvidia",
        title="Find people discussing Nvidia (from the brief)",
        question="Who has been in meetings where Nvidia was discussed?",
        cypher="MATCH (p:Person)-[:ATTENDED]->(m:Meeting)-[:DISCUSSED]->(c:Company {name:'Nvidia'})\nRETURN DISTINCT p",
        shows="both",
        graph_cypher="MATCH path = (p:Person)-[:ATTENDED]->(m:Meeting)-[:DISCUSSED]->(c:Company {name:'Nvidia'})\n"
                     "RETURN path",
        talking_point="Two hops across meeting notes: attendance comes from the participant list, discussion from the "
                      "text.",
    ),
    DemoQuery(
        id="brief-3-investment-impact",
        title="Trace investment impact (from the brief)",
        question="Which clients own which funds, and what do those funds invest in?",
        cypher="MATCH (c:Client)-[:OWNS]->(f:Fund)-[:INVESTED_IN]->(co:Company)\nRETURN c,f,co",
        shows="both",
        graph_cypher="MATCH p = (c:Client {name: 'Hartwell Family Trust'})-[:OWNS]->(f:Fund)-[:INVESTED_IN]->(co:Company)\n"
                     "RETURN p",
        talking_point="OWNS is a business definition in the semantic model (client -> account -> holding), "
                      "materialized as one relationship.",
    ),
    DemoQuery(
        id="theme-documents-explained",
        title="Theme search with explanations",
        question="Which documents discuss a theme, and why was each one returned?",
        cypher=(
            "MATCH (d:Document)-[r:MENTIONS]->(t:Theme {name: $theme})\n"
            "RETURN d.date AS date, d.doc_type AS type, d.title AS title, d.id AS doc_id,\n"
            "       CASE WHEN r.inferred THEN 'concept: ' + r.via ELSE 'explicit mention' END AS why\n"
            "ORDER BY date DESC"),
        params={"theme": "AI Infrastructure"},
        talking_point="Every inferred link keeps the concept that triggered it - the answer is explainable.",
    ),
    DemoQuery(
        id="keyword-vs-semantic",
        title="Keyword search vs semantic model",
        question="How many relevant documents does plain keyword search miss?",
        cypher=(
            "CALL db.index.fulltext.queryNodes('documentText', $phrase) YIELD node\n"
            "WITH collect(node.id) AS keyword_hits\n"
            "MATCH (d:Document)-[r:MENTIONS]->(:Theme {name: $theme})\n"
            "WITH keyword_hits, d, collect(r.via) AS vias\n"
            "RETURN d.id AS doc_id, toString(d.date) AS date, d.title AS title, d.doc_type AS type,\n"
            "       d.id IN keyword_hits AS found_by_keyword,\n"
            "       [v IN vias WHERE v IS NOT NULL] AS matched_via_concepts\n"
            "ORDER BY found_by_keyword, d.date DESC"),
        params={"phrase": '"AI infrastructure"', "theme": "AI Infrastructure"},
        talking_point="Keyword search only finds the literal phrase. The semantic layer also finds documents about "
                      "GPU capacity, AI data centers, liquid cooling or hyperscaler capex.",
    ),
    DemoQuery(
        id="client-theme-impact",
        title="Everything AI-infrastructure related that impacted a client (last 12 months)",
        question="Show me everything related to AI infrastructure investments that impacted the Hartwell Family "
                 "Trust in the last 12 months.",
        cypher=(
            "WITH date($as_of) - duration('P12M') AS since\n"
            "MATCH (c:Client {name: $client}), (t:Theme {name: $theme})\n"
            "CALL (c, t, since) {\n"
            "  MATCH p = (c)-[:OWNS]->(:Fund)-[:INVESTED_IN]->(:Company)-[:EXPOSED_TO]->(t)\n"
            "  RETURN p\n"
            "  UNION\n"
            "  MATCH p = (c)-[:HAS_ACCOUNT]->(:Account)-[:HAS_TRANSACTION]->(x:Transaction)-[:PURSUANT_TO]->(:Decision)-[:AFFECTS]->(t)\n"
            "  WHERE x.date >= since\n"
            "  RETURN p\n"
            "  UNION\n"
            "  MATCH p = (c)<-[:ABOUT|MENTIONS]-(d:Document)-[:MENTIONS]->(t)\n"
            "  WHERE d.date >= since\n"
            "  RETURN p\n"
            "  UNION\n"
            "  MATCH p = (c)<-[:CONTACT_FOR]-(:Person)<-[:SENT_TO]-(d:Document)-[:MENTIONS]->(t)\n"
            "  WHERE d.date >= since\n"
            "  RETURN p\n"
            "  UNION\n"
            "  MATCH p = (c)<-[:ABOUT|MENTIONS]-(d:Document)-[:MENTIONS]->(:Fund)-[:FOCUSES_ON]->(t)\n"
            "  WHERE d.date >= since\n"
            "  RETURN p\n"
            "  UNION\n"
            "  MATCH p = (c)<-[:ABOUT|MENTIONS]-(d:Document)-[:REFERENCES]->(:Decision)-[:AFFECTS]->(t)\n"
            "  WHERE d.date >= since\n"
            "  RETURN p\n"
            "  UNION\n"
            "  MATCH p = (c)<-[:FOR_CLIENT]-(m:Meeting)-[:DISCUSSED]->(t)\n"
            "  WHERE m.date >= since\n"
            "  RETURN p\n"
            "}\n"
            "RETURN p"),
        params={"client": "Hartwell Family Trust", "theme": "AI Infrastructure", "as_of": AS_OF},
        shows="graph",
        talking_point="One question, five systems: portfolio accounting, order management, CRM, email and meeting "
                      "notes - connected through the client and the theme.",
    ),
    DemoQuery(
        id="look-through-exposure",
        title="Look-through theme exposure by client",
        question="Which clients have the most look-through exposure to AI Infrastructure?",
        cypher=(
            "MATCH (c:Client)-[:HAS_ACCOUNT]->(:Account)-[h:HOLDS]->(f:Fund)\n"
            "WITH c, f, sum(h.market_value) AS value\n"
            "OPTIONAL MATCH (f)-[i:INVESTED_IN]->(:Company)-[e:EXPOSED_TO]->(:Theme {name: $theme})\n"
            "WITH c, f, value,\n"
            "     sum(coalesce(i.weight, 0.0) / 100.0 *\n"
            "         CASE e.degree WHEN 'high' THEN 1.0 WHEN 'medium' THEN 0.5 WHEN 'low' THEN 0.25 ELSE 0.0 END) AS factor\n"
            "WITH c, sum(value) AS total, sum(value * factor) AS exposed\n"
            "RETURN c.name AS client, round(total) AS total_usd, round(exposed) AS exposed_usd,\n"
            "       round(1000.0 * exposed / total) / 10.0 AS exposure_pct\n"
            "ORDER BY exposure_pct DESC"),
        params={"theme": "AI Infrastructure"},
        talking_point="Exposure the fund labels hide: a 'Global Technology' fund and a private credit loan both "
                      "carry AI Infrastructure risk. Guideline is 15%.",
    ),
    DemoQuery(
        id="hidden-nvidia-exposure",
        title="Hidden single-name concentration",
        question="Through which funds does a client own Nvidia, and how much?",
        cypher=(
            "MATCH (c:Client {name: $client})-[o:OWNS]->(f:Fund)-[i:INVESTED_IN]->(co:Company {name: $company})\n"
            "RETURN f.name AS fund, o.market_value AS client_position_usd, i.weight AS weight_pct,\n"
            "       round(o.market_value * i.weight / 100.0) AS look_through_usd\n"
            "ORDER BY look_through_usd DESC"),
        params={"client": "Hartwell Family Trust", "company": "Nvidia"},
        talking_point="Answers the trustee's question from March: how much Nvidia do we really own?",
    ),
    DemoQuery(
        id="decision-provenance",
        title="Decision provenance",
        question="What discussions led us to increase AI infrastructure exposure?",
        cypher=(
            "MATCH (t:Theme {name: $theme})<-[:AFFECTS]-(dec:Decision {direction: 'increase'})\n"
            "CALL (t, dec) {\n"
            "  MATCH p = (dec)<-[:PROPOSES]-(:Document)<-[:AUTHORED]-(:Person)\n"
            "  RETURN p\n"
            "  UNION\n"
            "  MATCH p = (dec)<-[:PROPOSES]-(:Document)-[:CITES]->(:Document)<-[:AUTHORED]-(:Person)\n"
            "  RETURN p\n"
            "  UNION\n"
            "  MATCH p = (dec)<-[:DECIDED]-(:Meeting)<-[:ATTENDED]-(:Person)\n"
            "  RETURN p\n"
            "  UNION\n"
            "  MATCH p = (t)<-[:DISCUSSED]-(m:Meeting)<-[:ATTENDED]-(:Person)\n"
            "  WHERE m.date < dec.date AND m.date >= dec.date - duration('P120D')\n"
            "  RETURN p\n"
            "}\n"
            "RETURN p"),
        params={"theme": "AI Infrastructure"},
        shows="graph",
        talking_point="From the decision back to the memo, the research it cited, the meetings and the people.",
    ),
    DemoQuery(
        id="decision-implementation",
        title="Decision implementation",
        question="Which trades implemented each AI Infrastructure decision, and for which clients?",
        cypher=(
            "MATCH (dec:Decision)-[:AFFECTS]->(:Theme {name: $theme})\n"
            "MATCH (dec)<-[:PURSUANT_TO]-(x:Transaction)<-[:HAS_TRANSACTION]-(a:Account)<-[:HAS_ACCOUNT]-(c:Client)\n"
            "MATCH (x)-[:INVOLVES]->(f:Fund)\n"
            "RETURN dec.id AS decision, dec.date AS decided, count(DISTINCT c) AS clients,\n"
            "       count(DISTINCT a) AS accounts, count(x) AS trades,\n"
            "       sum(CASE WHEN x.txn_type IN ['BUY', 'CAPITAL_CALL'] THEN x.amount_usd ELSE 0 END) AS bought_usd,\n"
            "       sum(CASE WHEN x.txn_type = 'SELL' THEN x.amount_usd ELSE 0 END) AS sold_usd\n"
            "ORDER BY decided"),
        params={"theme": "AI Infrastructure"},
        talking_point="Structured trades link to unstructured decisions through a shared identifier in the order "
                      "reason.",
    ),
    DemoQuery(
        id="theme-experts",
        title="Who are our experts on a theme?",
        question="Who in the firm knows the most about AI Infrastructure?",
        cypher=(
            "MATCH (t:Theme {name: $theme})\n"
            "MATCH (p:Person)\n"
            "OPTIONAL MATCH (p)-[:AUTHORED]->(d:Document)-[:MENTIONS]->(t)\n"
            "WITH p, t, count(DISTINCT d) AS authored\n"
            "OPTIONAL MATCH (p)-[:ATTENDED]->(m:Meeting)-[:DISCUSSED]->(t)\n"
            "WITH p, authored, count(DISTINCT m) AS meetings\n"
            "WHERE authored + meetings > 0\n"
            "RETURN p.name AS person, p.title AS title, authored, meetings, 2 * authored + meetings AS score\n"
            "ORDER BY score DESC, person LIMIT 10"),
        params={"theme": "AI Infrastructure"},
        talking_point="Institutional knowledge: expertise inferred from who wrote and discussed what.",
    ),
    DemoQuery(
        id="why-connected",
        title="Why is this client connected to this company?",
        question="How is the Hartwell Family Trust connected to Cobalt Ridge Data Centers?",
        cypher=(
            "MATCH (c:Client {name: $client}), (co:Company {name: $borrower})\n"
            "MATCH p = allShortestPaths((c)-[*..4]-(co))\n"
            "RETURN p LIMIT 25"),
        params={"client": "Hartwell Family Trust", "borrower": "Cobalt Ridge Data Centers"},
        shows="graph",
        talking_point="Explainability: the investment link (fund -> loan) and the conversation link (CRM notes) side "
                      "by side.",
    ),
    DemoQuery(
        id="brief-sample-path",
        title="Client -> Fund -> Nvidia -> Meeting Notes -> Investment Committee",
        question="Show the path from a client to the Investment Committee discussions about a company they own.",
        cypher=(
            "MATCH p = (c:Client {name: $client})-[:OWNS]->(:Fund)-[:INVESTED_IN]->(co:Company {name: $company})\n"
            "          <-[:MENTIONS]-(:Document {doc_type: 'Meeting Notes'})-[:RECORDS]->(:Meeting)\n"
            "          -[:HELD_BY]->(:Committee {name: 'Investment Committee'})\n"
            "RETURN p"),
        params={"client": "Hartwell Family Trust", "company": "Nvidia"},
        shows="graph",
        talking_point="The exact path sketched in the demo brief - traversed in both directions.",
    ),
    DemoQuery(
        id="evidence",
        title="Show me the evidence",
        question="What exactly was said about Nvidia, where, and which engine extracted it?",
        cypher=(
            "MATCH (m:Meeting)-[r:DISCUSSED]->(:Company {name: $company})\n"
            "RETURN m.date AS date, m.title AS meeting, r.evidence AS evidence, r.doc_id AS source_document,\n"
            "       r.engine AS extracted_by\n"
            "ORDER BY date"),
        params={"company": "Nvidia"},
        talking_point="Every extracted relationship keeps its source document and the sentence that supports it.",
    ),
    DemoQuery(
        id="time-window",
        title="Time-aware retrieval",
        question="Which AI Infrastructure documents fall inside vs outside the last 12 months?",
        cypher=(
            "MATCH (d:Document)-[:MENTIONS]->(:Theme {name: $theme})\n"
            "WITH d, d.date >= date($as_of) - duration('P12M') AS in_window\n"
            "RETURN in_window, count(*) AS documents, collect(d.title)[..5] AS examples\n"
            "ORDER BY in_window DESC"),
        params={"theme": "AI Infrastructure", "as_of": AS_OF},
    ),
    DemoQuery(
        id="schema",
        title="The schema the semantic model produced",
        question="What does the graph's schema look like?",
        cypher="CALL db.schema.visualization()",
        shows="graph",
    ),
]


def by_id(query_id: str) -> DemoQuery:
    for q in QUERIES:
        if q.id == query_id:
            return q
    raise KeyError(query_id)
