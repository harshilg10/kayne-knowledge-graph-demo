"""Standard RAG vs Graph-RAG.

Standard RAG:  question -> vector search -> top chunks -> LLM.
Graph-RAG:     question -> entity linking through the semantic model (client, theme,
               concept, company, time window, intent) -> graph traversal across holdings,
               trades, decisions, meetings, documents and people -> facts with provenance -> LLM.

Without an API key both modes still answer: standard RAG returns the best-matching
sentences, Graph-RAG composes a templated answer from the retrieved facts.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import date, timedelta

from . import config
from . import neo4j_client as db
from .catalog import load_catalog, normalize_text

GUIDELINE_PCT = 15.0
GUIDELINE_THEME_ID = "THM-AI"   # the look-through guideline in the semantic model applies to AI Infrastructure
DEGREE_CASE = "CASE e.degree WHEN 'high' THEN 1.0 WHEN 'medium' THEN 0.5 WHEN 'low' THEN 0.25 ELSE 0.0 END"

PRESET_QUESTIONS = [
    "Show me everything related to AI infrastructure investments that impacted the Hartwell Family Trust in the "
    "last 12 months.",
    "What discussions led us to increase AI infrastructure exposure?",
    "Which clients have the most exposure to Nvidia, and what have we told them about it?",
    "How is the Hartwell Family Trust exposed to data center power demand?",
    "Who are our experts on liquid cooling?",
]

ANSWER_SYSTEM = (
    "You are an analyst assistant at a wealth and investment management firm. Answer the user's question using only "
    "the context provided. Cite sources inline with their identifiers in square brackets, e.g. [DOC-EM-08], "
    "[IC-2026-004] or [TXN-000123]. Be specific: names, dates, amounts, percentages. Structure the answer with short "
    "headings and bullets. If the context does not contain something the question asks for, say so plainly instead "
    "of guessing. Do not mention the retrieval process."
)


@dataclass
class Fact:
    kind: str                       # exposure | decision | trade | meeting | document | research | person | ...
    text: str                       # one line, as the LLM sees it
    sources: list[str] = field(default_factory=list)
    data: dict = field(default_factory=dict)


@dataclass
class RagResult:
    mode: str                       # standard | graph
    question: str
    strategy: str = ""
    linked: dict = field(default_factory=dict)
    chunks: list[dict] = field(default_factory=list)
    facts: list[Fact] = field(default_factory=list)
    cypher: list[str] = field(default_factory=list)
    queries: list[dict] = field(default_factory=list)   # {purpose, kind: retrieve|graph, cypher, params, rows}
    nodes: list[dict] = field(default_factory=list)
    edges: list[dict] = field(default_factory=list)
    context: str = ""
    answer: str = ""
    answer_engine: str = ""
    sources: list[dict] = field(default_factory=list)
    timings_ms: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


# =============================================================================
# helpers
# =============================================================================
def _usd(x: float | int | None) -> str:
    if x is None:
        return "n/a"
    x = float(x)
    if abs(x) >= 1_000_000:
        return f"${x / 1_000_000:.2f}M"
    return f"${x:,.0f}"


def _pct(x: float) -> str:
    return f"{x:.1f}%"


def _n(count: int, word: str, plural: str | None = None) -> str:
    return f"{count} {word if count == 1 else (plural or word + 's')}"


def _paren(items: list[str], limit: int = 4) -> str:
    items = [i for i in items if i]
    if not items:
        return ""
    more = f", +{len(items) - limit} more" if len(items) > limit else ""
    return f" ({'; '.join(items[:limit])}{more})"


def _fmt_date(iso: str) -> str:
    d = date.fromisoformat(iso[:10])
    return f"{d.strftime('%b')} {d.day}, {d.year}"


class _Recorder:
    """Runs Cypher and remembers what was executed, why, and with which parameters (shown in the app)."""

    def __init__(self, result: RagResult):
        self.result = result

    def run(self, purpose: str, cypher: str, params: dict) -> list[dict]:
        rows = db.run(cypher, params)
        self._log(purpose, "retrieve", cypher, params, len(rows))
        return rows

    def graph(self, purpose: str, cypher: str, params: dict) -> None:
        """Runs the query that draws the traversal; best effort, so a failure leaves an empty picture."""
        try:
            self.result.nodes, self.result.edges = db.run_graph(cypher, params)
        except Exception:
            self.result.nodes, self.result.edges = [], []
        self._log(purpose, "graph", cypher, params, len(self.result.nodes))

    def _log(self, purpose: str, kind: str, cypher: str, params: dict, rows: int) -> None:
        self.result.cypher.append(cypher.strip())
        self.result.queries.append({"purpose": purpose, "kind": kind, "cypher": cypher.strip(),
                                    "params": dict(params), "rows": rows})


# =============================================================================
# entity linking
# =============================================================================
_MONTH_WORDS = {"one": 1, "two": 2, "three": 3, "six": 6, "nine": 9, "twelve": 12, "eighteen": 18, "twenty-four": 24}


def link_question(question: str, as_of: date | None = None) -> dict:
    """Resolve a natural-language question to graph entities, a time window and an intent."""
    as_of = as_of or config.AS_OF_DATE
    text = normalize_text(question)
    cat = load_catalog()
    linked: dict = {"clients": [], "themes": [], "concepts": [], "companies": [], "funds": [], "people": [],
                    "decisions": [], "since": None, "as_of": as_of.isoformat(), "intent": [], "direction": None,
                    "mentions": []}
    seen = set()
    for m in cat.find(text):
        e = m.entry
        linked["mentions"].append({"surface": m.surface, "label": e.label, "id": e.id, "name": e.name})
        if e.key in seen:
            continue
        seen.add(e.key)
        bucket = {"Client": "clients", "Theme": "themes", "Concept": "concepts", "Company": "companies",
                  "Fund": "funds", "Person": "people", "Decision": "decisions"}.get(e.label)
        if bucket:
            linked[bucket].append({"id": e.id, "name": e.name})
        if e.label == "Concept":
            onto_theme = cat.by_key.get(f"Theme:{e.theme_id}")
            if onto_theme and onto_theme.key not in seen:
                seen.add(onto_theme.key)
                linked["themes"].append({"id": onto_theme.id, "name": onto_theme.name, "via": e.name})
    low = text.lower()
    m = re.search(r"\b(?:last|past|previous)\s+(\d+|" + "|".join(_MONTH_WORDS) + r")\s+months?\b", low)
    if m:
        n = int(m.group(1)) if m.group(1).isdigit() else _MONTH_WORDS[m.group(1)]
        linked["since"] = _months_before(as_of, n).isoformat()
    elif re.search(r"\b(?:last|past)\s+year\b", low):
        linked["since"] = _months_before(as_of, 12).isoformat()
    elif re.search(r"\bthis year\b", low):
        linked["since"] = date(as_of.year, 1, 1).isoformat()
    if re.search(r"\b(why|led (?:us )?to|lead (?:us )?to|reason|rationale|drove|behind|how did we decide)\b", low):
        linked["intent"].append("provenance")
    if re.search(r"\bwho\b.*\b(expert|experts|knows|know|specialist)\b|\bexperts?\b", low):
        linked["intent"].append("expertise")
    if re.search(r"\b(exposure|exposed|concentration|own|owns|hold|holds)\b", low):
        linked["intent"].append("exposure")
    if re.search(r"\b(increase|increased|add|added|raise|raised|buy|bought|grow)\b", low):
        linked["direction"] = "increase"
    elif re.search(r"\b(reduce|reduced|trim|trimmed|cut|decrease|decreased|sell|sold|lower)\b", low):
        linked["direction"] = "decrease"
    return linked


def _months_before(d: date, months: int) -> date:
    y, mth = d.year, d.month - months
    while mth <= 0:
        mth += 12
        y -= 1
    day = min(d.day, [31, 29 if y % 4 == 0 and (y % 100 or y % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31,
                      30, 31][mth - 1])
    return date(y, mth, day)


def choose_strategy(linked: dict) -> str:
    if linked["clients"] and (linked["themes"] or linked["companies"]):
        return "client_theme_impact" if linked["themes"] else "client_company_exposure"
    if "expertise" in linked["intent"] and (linked["themes"] or linked["concepts"] or linked["companies"]):
        return "expertise"
    if linked["themes"] and ("provenance" in linked["intent"] or linked["direction"]):
        return "decision_provenance"
    if linked["companies"] and ("exposure" in linked["intent"] or "clients" in "".join(linked["intent"])):
        return "company_exposure"
    if linked["companies"]:
        return "company_exposure"
    if linked["clients"]:
        return "client_theme_impact"
    if linked["themes"]:
        return "decision_provenance"
    return "hybrid"


# =============================================================================
# Graph-RAG strategies
# =============================================================================
def _client_overview(rec: _Recorder, client_id: str) -> tuple[dict, list[Fact]]:
    rows = rec.run("Client, advisor and contacts",
        "MATCH (c:Client {id: $cid})\n"
        "OPTIONAL MATCH (c)-[:ADVISED_BY]->(adv:Person)\n"
        "OPTIONAL MATCH (p:Person)-[r:CONTACT_FOR]->(c)\n"
        "RETURN c.id AS id, c.name AS name, c.risk_profile AS risk, c.segment AS segment, c.notes AS notes,\n"
        "       adv.name AS advisor, collect(DISTINCT p.name + ' (' + r.role + ')') AS contacts", {"cid": client_id})
    if not rows:
        return {}, []
    c = rows[0]
    total = rec.run("The client's total assets",
                    "MATCH (:Client {id: $cid})-[o:OWNS]->(:Fund) RETURN sum(o.market_value) AS total",
                    {"cid": client_id})[0]["total"]
    c["total"] = total
    fact = Fact("client", f"Client {c['name']} ({c['id']}): {c['segment']}, {c['risk']} profile, total assets "
                          f"{_usd(total)}; advisor {c['advisor']}; contacts {', '.join(c['contacts'])}.",
                [c["id"]], c)
    return c, [fact]


def _exposure_facts(rec: _Recorder, client_id: str, theme: dict, total: float) -> tuple[float, list[Fact]]:
    rows = rec.run("Look-through exposure, fund by fund",
        "MATCH (:Client {id: $cid})-[o:OWNS]->(f:Fund)\n"
        "OPTIONAL MATCH (f)-[i:INVESTED_IN]->(co:Company)-[e:EXPOSED_TO]->(:Theme {id: $tid})\n"
        "WITH f, o, i, co, e ORDER BY i.weight DESC\n"
        f"WITH f, o, sum(coalesce(i.weight, 0.0) / 100.0 * {DEGREE_CASE}) AS factor,\n"
        "     collect(CASE WHEN co IS NULL THEN NULL ELSE co.name + ' ' + toString(i.weight) + '% (' + e.degree + ')' END) AS names\n"
        "OPTIONAL MATCH (f)-[:FOCUSES_ON]->(ft:Theme)\n"
        "RETURN f.id AS fund_id, f.name AS fund, o.market_value AS position, factor, names,\n"
        "       collect(DISTINCT ft.id) AS fund_themes\n"
        "ORDER BY position * factor DESC", {"cid": client_id, "tid": theme["id"]})
    exposed = sum(r["position"] * r["factor"] for r in rows)
    pct = 100.0 * exposed / total if total else 0.0
    guideline = (f" The firm's guideline for {theme['name']} is {GUIDELINE_PCT:.0f}% of assets."
                 if theme["id"] == GUIDELINE_THEME_ID else "")
    facts = [Fact("exposure",
                  f"Look-through {theme['name']} exposure: {_pct(pct)} of assets ({_usd(exposed)} of {_usd(total)})."
                  f"{guideline} Method: fund position x fund weight in theme-exposed companies x exposure factor "
                  f"(high 1.0, medium 0.5, low 0.25).",
                  [], {"pct": round(pct, 1), "exposed": exposed, "total": total,
                       "guideline": GUIDELINE_PCT if theme["id"] == GUIDELINE_THEME_ID else None})]
    for r in rows:
        if r["factor"] <= 0:
            continue
        direct = " - the fund's mandate targets this theme" if theme["id"] in r["fund_themes"] else ""
        names = [n for n in r["names"] if n]
        listed = ", ".join(names[:8]) + (f" and {len(names) - 8} more" if len(names) > 8 else "")
        facts.append(Fact("holding",
                          f"{r['fund']}: position {_usd(r['position'])}; {_pct(100 * r['factor'])} of the fund is "
                          f"exposed{direct}; exposed companies: {listed}.", [r["fund_id"]], r))
    return pct, facts


def _related_theme_facts(rec: _Recorder, client_id: str, theme: dict, total: float) -> list[Fact]:
    rows = rec.run("Exposure to related themes",
        "MATCH (:Theme {id: $tid})-[l:RELATED_TO]-(rt:Theme)\n"
        "MATCH (:Client {id: $cid})-[o:OWNS]->(f:Fund)-[i:INVESTED_IN]->(co:Company)-[e:EXPOSED_TO]->(rt)\n"
        f"WITH rt, l, sum(o.market_value * i.weight / 100.0 * {DEGREE_CASE}) AS exposed,\n"
        "     collect(DISTINCT f.name) AS funds, collect(DISTINCT co.name)[..6] AS companies\n"
        "RETURN rt.id AS id, rt.name AS name, l.rationale AS rationale, exposed, funds, companies\n"
        "ORDER BY exposed DESC", {"tid": theme["id"], "cid": client_id})
    facts = []
    for r in rows:
        if r["exposed"] <= 0:
            continue
        facts.append(Fact("adjacent_exposure",
                          f"Adjacent theme {r['name']} ({r['rationale']}): look-through {_pct(100 * r['exposed'] / total)} "
                          f"via {', '.join(r['funds'])} (e.g. {', '.join(r['companies'])}).", [r["id"]], r))
    return facts


def _decision_facts(rec: _Recorder, theme_ids: list[str], since: str | None, as_of: str,
                    client_id: str | None = None, direction: str | None = None) -> list[Fact]:
    rows = rec.run("Investment Committee decisions on the theme",
        "MATCH (dec:Decision)-[:AFFECTS]->(t:Theme) WHERE t.id IN $tids\n"
        "  AND dec.date <= date($as_of) AND ($since IS NULL OR dec.date >= date($since))\n"
        "  AND ($direction IS NULL OR dec.direction = $direction)\n"
        "WITH DISTINCT dec\n"
        "OPTIONAL MATCH (memo:Document)-[:PROPOSES]->(dec)\n"
        "OPTIONAL MATCH (author:Person)-[:AUTHORED]->(memo)\n"
        "OPTIONAL MATCH (m:Meeting)-[:DECIDED]->(dec)\n"
        "OPTIONAL MATCH (x:Transaction)-[:PURSUANT_TO]->(dec)\n"
        "OPTIONAL MATCH (x)<-[:HAS_TRANSACTION]-(:Account)<-[:HAS_ACCOUNT]-(cl:Client)\n"
        "RETURN dec.id AS id, toString(dec.date) AS date, dec.title AS title, dec.vote AS vote,\n"
        "       dec.direction AS direction, dec.summary AS summary, memo.id AS memo_id, memo.title AS memo_title,\n"
        "       collect(DISTINCT author.name) AS authors, m.id AS meeting_id, m.title AS meeting_title,\n"
        "       count(DISTINCT x) AS trades, count(DISTINCT cl) AS clients,\n"
        "       $cid IS NOT NULL AND $cid IN collect(DISTINCT cl.id) AS affects_client\n"
        "ORDER BY date",
        {"tids": theme_ids, "since": since, "as_of": as_of, "direction": direction, "cid": client_id})
    facts = []
    for r in rows:
        memo = f" Proposed in memo '{r['memo_title']}' by {', '.join(r['authors'])} [{r['memo_id']}]." if r["memo_id"] else ""
        impl = f" Implemented through {r['trades']} trades for {r['clients']} clients." if r["trades"] else ""
        mine = " This client's accounts traded under it." if r["affects_client"] else ""
        facts.append(Fact("decision",
                          f"Decision {r['id']} ({_fmt_date(r['date'])}, vote {r['vote']}, {r['direction']}): "
                          f"{r['title']}. {r['summary']}{memo}{impl}{mine}",
                          [r["id"]] + ([r["memo_id"]] if r["memo_id"] else []), r))
    return facts


def _trade_facts(rec: _Recorder, client_id: str, theme_id: str, since: str | None, as_of: str) -> list[Fact]:
    rows = rec.run("Trades in the client's accounts",
        "MATCH (:Client {id: $cid})-[:HAS_ACCOUNT]->(a:Account)-[:HAS_TRANSACTION]->(x:Transaction)-[:INVOLVES]->(f:Fund)\n"
        "WHERE x.date <= date($as_of) AND ($since IS NULL OR x.date >= date($since))\n"
        "OPTIONAL MATCH (x)-[:PURSUANT_TO]->(dec:Decision)\n"
        "WITH a, x, f, dec\n"
        "WHERE (dec IS NOT NULL AND EXISTS { (dec)-[:AFFECTS]->(:Theme {id: $tid}) })\n"
        "   OR EXISTS { (f)-[:FOCUSES_ON]->(:Theme {id: $tid}) }\n"
        "   OR (x.txn_type = 'CAPITAL_CALL' AND EXISTS { (f)-[:INVESTED_IN]->(:Company)-[:EXPOSED_TO {degree: 'high'}]->(:Theme {id: $tid}) })\n"
        "RETURN x.id AS id, toString(x.date) AS date, x.txn_type AS type, x.amount_usd AS amount,\n"
        "       x.order_reason AS reason, a.id AS account_id, a.name AS account, f.name AS fund, dec.id AS decision\n"
        "ORDER BY date, account_id, type", {"cid": client_id, "tid": theme_id, "since": since, "as_of": as_of})
    facts = []
    for r in rows:
        facts.append(Fact("trade",
                          f"{_fmt_date(r['date'])}: {r['type']} {_usd(r['amount'])} {r['fund']} in {r['account']} "
                          f"({r['account_id']}) - {r['reason']}.",
                          [r["id"]] + ([r["decision"]] if r["decision"] else []), r))
    return facts


def _client_document_facts(rec: _Recorder, client_id: str, theme_id: str, since: str | None, as_of: str) -> list[Fact]:
    """Documents linked to the client and to the theme. Client correspondence (CRM notes, emails with the client's
    contacts) and internal documents that name the client are kept apart; notes of client meetings are reported with
    the meetings."""
    rows = rec.run("Documents about the client",
        "MATCH (c:Client {id: $cid})\n"
        "MATCH (d:Document)\n"
        "WHERE d.date <= date($as_of) AND ($since IS NULL OR d.date >= date($since))\n"
        "  AND NOT EXISTS { (d)-[:RECORDS]->(:Meeting)-[:FOR_CLIENT]->(c) }\n"
        "  AND (EXISTS { (d)-[:ABOUT|MENTIONS]->(c) }\n"
        "       OR EXISTS { (d)-[:SENT_TO]->(:Person)-[:CONTACT_FOR]->(c) }\n"
        "       OR EXISTS { (d)<-[:SENT]-(:Person)-[:CONTACT_FOR]->(c) })\n"
        "WITH c, d, (EXISTS { (d)-[:ABOUT]->(c) } OR EXISTS { (d)-[:SENT_TO]->(:Person)-[:CONTACT_FOR]->(c) }\n"
        "            OR EXISTS { (d)<-[:SENT]-(:Person)-[:CONTACT_FOR]->(c) }) AS client_facing\n"
        "OPTIONAL MATCH (d)-[r1:MENTIONS]->(:Theme {id: $tid})\n"
        "OPTIONAL MATCH (d)-[:MENTIONS]->(f:Fund)-[:FOCUSES_ON]->(:Theme {id: $tid})\n"
        "OPTIONAL MATCH (d)-[:MENTIONS]->(co:Company)-[:EXPOSED_TO {degree: 'high'}]->(:Theme {id: $tid})\n"
        "OPTIONAL MATCH (d)-[:REFERENCES]->(dec:Decision)-[:AFFECTS]->(:Theme {id: $tid})\n"
        "WITH d, client_facing, r1, collect(DISTINCT f.name) AS funds, collect(DISTINCT co.name) AS companies,\n"
        "     collect(DISTINCT dec.id) AS decisions\n"
        "WHERE r1 IS NOT NULL OR size(funds) > 0 OR size(companies) > 0 OR size(decisions) > 0\n"
        "OPTIONAL MATCH (author:Person)-[:AUTHORED|SENT]->(d)\n"
        "RETURN d.id AS id, d.title AS title, d.doc_type AS type, toString(d.date) AS date,\n"
        "       d.source_system AS system, collect(DISTINCT author.name) AS authors, client_facing,\n"
        "       CASE WHEN r1 IS NULL THEN NULL WHEN r1.inferred THEN 'concept ' + r1.via ELSE 'explicit mention' END AS theme_link,\n"
        "       r1.evidence AS evidence, funds, companies, decisions,\n"
        "       substring(d.text, 0, 1200) AS text\n"
        "ORDER BY date, id", {"cid": client_id, "tid": theme_id, "since": since, "as_of": as_of})
    facts = []
    for r in rows:
        why = []
        if r["theme_link"]:
            why.append(r["theme_link"])
        if r["funds"]:
            why.append("fund " + ", ".join(r["funds"]))
        if r["companies"]:
            why.append("company " + ", ".join(r["companies"][:4]))
        if r["decisions"]:
            why.append("decision " + ", ".join(r["decisions"]))
        gist = r["evidence"] or _first_sentences(_body_of(r["text"]), 2)
        who = f" by {', '.join(r['authors'])}" if r["authors"] else ""
        kind = "client_document" if r["client_facing"] else "internal_document"
        facts.append(Fact(kind,
                          f"{_fmt_date(r['date'])} {r['type']} '{r['title']}'{who} ({r['system']}); linked via "
                          f"{'; '.join(why)}. Excerpt: \"{gist[:280]}\"", [r["id"]], r))
    return facts


def _meeting_facts(rec: _Recorder, theme_id: str, since: str | None, as_of: str, client_id: str | None = None,
                   before: str | None = None, committee_only: bool = False) -> list[Fact]:
    rows = rec.run("Meetings that discussed the theme",
        "MATCH (m:Meeting)-[r:DISCUSSED]->(:Theme {id: $tid})\n"
        "WHERE m.date <= date($as_of) AND ($since IS NULL OR m.date >= date($since))\n"
        "  AND ($before IS NULL OR m.date < date($before))\n"
        "  AND (NOT $committee_only OR EXISTS { (m)-[:HELD_BY]->(:Committee) } OR m.meeting_type = 'Research')\n"
        "  AND ($cid IS NULL OR EXISTS { (m)-[:HELD_BY]->(:Committee) } OR EXISTS { (m)-[:FOR_CLIENT]->(:Client {id: $cid}) }\n"
        "       OR m.meeting_type IN ['Research', 'Due Diligence'])\n"
        "OPTIONAL MATCH (p:Person)-[:ATTENDED]->(m)\n"
        "OPTIONAL MATCH (d:Document)-[:RECORDS]->(m)\n"
        "RETURN m.id AS id, m.title AS title, toString(m.date) AS date, m.meeting_type AS type,\n"
        "       collect(DISTINCT p.name) AS attendees, r.evidence AS evidence, r.via AS via, d.id AS doc_id\n"
        "ORDER BY date",
        {"tid": theme_id, "since": since, "as_of": as_of, "cid": client_id, "before": before,
         "committee_only": committee_only})
    facts = []
    for r in rows:
        via = f" (via concept {r['via']})" if r["via"] else ""
        facts.append(Fact("meeting",
                          f"{_fmt_date(r['date'])} {r['title']} ({r['type']}); attendees: {', '.join(r['attendees'])}. "
                          f"Discussed the theme{via}: \"{(r['evidence'] or '')[:240]}\"",
                          [r["doc_id"]] if r["doc_id"] else [r["id"]], r))
    return facts


def _client_meeting_facts(rec: _Recorder, client_id: str, since: str | None, as_of: str) -> list[Fact]:
    rows = rec.run("Meetings with the client",
        "MATCH (m:Meeting)-[:FOR_CLIENT]->(:Client {id: $cid})\n"
        "WHERE m.date <= date($as_of) AND ($since IS NULL OR m.date >= date($since))\n"
        "OPTIONAL MATCH (p:Person)-[:ATTENDED]->(m)\n"
        "OPTIONAL MATCH (d:Document)-[:RECORDS]->(m)\n"
        "OPTIONAL MATCH (m)-[:DISCUSSED]->(x) WHERE x:Fund OR x:Company OR x:Theme\n"
        "RETURN m.id AS id, m.title AS title, toString(m.date) AS date, collect(DISTINCT p.name) AS attendees,\n"
        "       d.id AS doc_id, collect(DISTINCT x.name) AS discussed\n"
        "ORDER BY date", {"cid": client_id, "since": since, "as_of": as_of})
    return [Fact("client_meeting",
                 f"{_fmt_date(r['date'])} {r['title']}; attendees: {', '.join(r['attendees'])}; discussed: "
                 f"{', '.join(r['discussed'][:10])}.", [r["doc_id"] or r["id"]], r) for r in rows]


def _research_facts(rec: _Recorder, theme_id: str, since: str | None, as_of: str, limit: int = 8) -> list[Fact]:
    rows = rec.run("Research on the theme",
        "MATCH (d:Document {doc_type: 'Research Report'})-[r:MENTIONS]->(:Theme {id: $tid})\n"
        "WHERE d.date <= date($as_of) AND ($since IS NULL OR d.date >= date($since))\n"
        "OPTIONAL MATCH (a:Person)-[:AUTHORED]->(d)\n"
        "OPTIONAL MATCH (memo:Document)-[:CITES]->(d)\n"
        "WITH d, r, collect(DISTINCT a.name) AS authors, collect(DISTINCT memo.id) AS cited_by\n"
        "RETURN d.id AS id, d.title AS title, toString(d.date) AS date, authors, cited_by,\n"
        "       r.evidence AS evidence, r.via AS via\n"
        "ORDER BY size(cited_by) DESC, CASE WHEN r.via IS NULL THEN 0 ELSE 1 END, date DESC LIMIT $limit",
        {"tid": theme_id, "since": since, "as_of": as_of, "limit": limit})
    facts = []
    for r in rows:
        cited = f"; cited by {', '.join(r['cited_by'])}" if r["cited_by"] else ""
        facts.append(Fact("research",
                          f"{_fmt_date(r['date'])} research '{r['title']}' by {', '.join(r['authors'])}{cited}: "
                          f"\"{(r['evidence'] or '')[:220]}\"", [r["id"]], r))
    return facts


def _graph_for(rec: _Recorder, query_id: str, params: dict) -> None:
    from .queries import by_id
    q = by_id(query_id)
    rec.graph("Draw the graph above", q.cypher, {**q.params, **params})


def strategy_client_theme_impact(rec: _Recorder, linked: dict) -> list[Fact]:
    client = linked["clients"][0]
    theme = linked["themes"][0]
    since, as_of = linked["since"], linked["as_of"]
    overview, facts = _client_overview(rec, client["id"])
    total = overview.get("total") or 0
    _pct_value, exposure = _exposure_facts(rec, client["id"], theme, total)
    facts += exposure
    facts += _related_theme_facts(rec, client["id"], theme, total)
    facts += _decision_facts(rec, [theme["id"]], since, as_of, client_id=client["id"])
    facts += _trade_facts(rec, client["id"], theme["id"], since, as_of)
    facts += _client_meeting_facts(rec, client["id"], since, as_of)
    facts += _meeting_facts(rec, theme["id"], since, as_of, client_id=client["id"], committee_only=True)
    facts += _client_document_facts(rec, client["id"], theme["id"], since, as_of)
    facts += _research_facts(rec, theme["id"], since, as_of)
    _graph_for(rec, "client-theme-impact", {"client": client["name"], "theme": theme["name"], "as_of": as_of})
    return facts


def strategy_decision_provenance(rec: _Recorder, linked: dict) -> list[Fact]:
    """Decision -> proposing memo and its authors -> cited research -> the meetings and internal correspondence about
    what the decision changes (its funds and companies) in the 120 days before -> the decision meeting -> trades."""
    theme = linked["themes"][0]
    as_of = linked["as_of"]
    decisions = _decision_facts(rec, [theme["id"]], linked["since"], as_of, direction=linked["direction"])
    facts: list[Fact] = []
    for dec_fact in decisions:
        dec = dec_fact.data
        facts.append(dec_fact)
        if dec["memo_id"]:
            cited = rec.run(f"{dec['id']}: research the memo cites",
                "MATCH (:Document {id: $memo})-[:CITES]->(d:Document)\n"
                "OPTIONAL MATCH (a:Person)-[:AUTHORED]->(d)\n"
                "RETURN d.id AS id, d.title AS title, toString(d.date) AS date, d.doc_type AS type,\n"
                "       collect(DISTINCT a.name) AS authors ORDER BY date", {"memo": dec["memo_id"]})
            for c in cited:
                facts.append(Fact("cited", f"The {dec['id']} memo cites {c['type'].lower()} '{c['title']}' "
                                           f"({_fmt_date(c['date'])}, by {', '.join(c['authors'])}).",
                                  [c["id"]], {**c, "decision": dec["id"]}))
        if dec["meeting_id"]:
            mt = rec.run(f"{dec['id']}: the meeting that decided it",
                "MATCH (m:Meeting {id: $mid})\n"
                "OPTIONAL MATCH (p:Person)-[:ATTENDED]->(m)\n"
                "OPTIONAL MATCH (d:Document)-[:RECORDS]->(m)\n"
                "OPTIONAL MATCH (m)-[r:DECIDED]->(:Decision {id: $did})\n"
                "RETURN m.title AS title, toString(m.date) AS date, collect(DISTINCT p.name) AS attendees,\n"
                "       d.id AS doc_id, r.evidence AS evidence", {"mid": dec["meeting_id"], "did": dec["id"]})
            if mt:
                m = mt[0]
                facts.append(Fact("decision_meeting",
                                  f"{dec['id']} was decided at the {m['title']} on {_fmt_date(m['date'])}; attendees: "
                                  f"{', '.join(m['attendees'])}. Notes: \"{(m['evidence'] or '')[:240]}\"",
                                  [m["doc_id"] or dec["meeting_id"]], {**m, "decision": dec["id"]}))
        start = (date.fromisoformat(dec["date"]) - timedelta(days=120)).isoformat()
        affected = rec.run(f"{dec['id']}: what the decision changes",
            "MATCH (:Decision {id: $did})-[:AFFECTS]->(x)\n"
            "RETURN [y IN collect(x) WHERE y:Company | y.id] AS companies, [y IN collect(x) WHERE y:Fund | y.id] AS funds",
            {"did": dec["id"]})[0]
        targets = affected["companies"] or affected["funds"]  # what the decision is specifically about
        meetings = rec.run(f"{dec['id']}: earlier meetings on those topics",
            "MATCH (m:Meeting)-[r:DISCUSSED]->(x)\n"
            "WHERE m.date >= date($start) AND m.date < date($before)\n"
            "  AND m.meeting_type IN ['Investment Committee', 'Research', 'Due Diligence', 'Risk Review']\n"
            "  AND (x.id IN $targets OR (size($targets) = 0 AND x.id = $tid))\n"
            "WITH m, r, x ORDER BY size(r.evidence) DESC\n"
            "WITH m, collect(r)[0] AS r, collect(DISTINCT x.name) AS topics\n"
            "OPTIONAL MATCH (p:Person)-[:ATTENDED]->(m)\n"
            "OPTIONAL MATCH (d:Document)-[:RECORDS]->(m)\n"
            "RETURN m.id AS id, m.title AS title, toString(m.date) AS date, m.meeting_type AS type, topics,\n"
            "       collect(DISTINCT p.name) AS attendees, r.evidence AS evidence, d.id AS doc_id ORDER BY date",
            {"start": start, "before": dec["date"], "targets": targets, "tid": theme["id"]})
        for m in meetings:
            facts.append(Fact("prior_meeting",
                              f"{_fmt_date(m['date'])} {m['title']} ({m['type']}) discussed {', '.join(m['topics'])}; "
                              f"attendees: {', '.join(m['attendees'])}. \"{(m['evidence'] or '')[:220]}\"",
                              [m["doc_id"] or m["id"]], {**m, "decision": dec["id"]}))
        prior_docs = rec.run(f"{dec['id']}: earlier internal emails and memos",
            "MATCH (d:Document)-[r:MENTIONS]->(x)\n"
            "WHERE d.doc_type IN ['Email', 'IC Memo'] AND d.date >= date($start) AND d.date < date($before)\n"
            "  AND (x.id IN $targets OR (size($targets) = 0 AND x.id = $tid))\n"
            "  AND NOT EXISTS { (d)-[:SENT_TO]->(:Person {person_type: 'client_contact'}) }\n"
            "  AND NOT EXISTS { (:Person {person_type: 'client_contact'})-[:SENT]->(d) }\n"
            "WITH d, r ORDER BY size(r.evidence) DESC\n"
            "WITH d, collect(r)[0] AS r\n"
            "OPTIONAL MATCH (a:Person)-[:AUTHORED|SENT]->(d)\n"
            "RETURN d.id AS id, d.title AS title, d.doc_type AS type, toString(d.date) AS date,\n"
            "       collect(DISTINCT a.name) AS authors, r.evidence AS evidence,\n"
            "       substring(d.text, 0, 1500) AS text ORDER BY date",
            {"start": start, "before": dec["date"], "targets": targets, "tid": theme["id"]})
        for d in prior_docs:
            if d["id"] == dec["memo_id"]:
                continue
            quote = d["evidence"] or ""
            if len(quote) < 40:  # a bare name (e.g. a signature line) says nothing - use the opening instead
                quote = _first_sentences(_body_of(d["text"]), 2) or quote
            facts.append(Fact("prior_document",
                              f"{_fmt_date(d['date'])} {d['type'].lower()} '{d['title']}' from {', '.join(d['authors'])}: "
                              f"\"{quote[:220]}\"", [d["id"]], {**d, "decision": dec["id"]}))
        impl = rec.run(f"{dec['id']}: the trades that implemented it",
            "MATCH (:Decision {id: $did})<-[:PURSUANT_TO]-(x:Transaction)<-[:HAS_TRANSACTION]-(a:Account)<-[:HAS_ACCOUNT]-(c:Client)\n"
            "RETURN count(x) AS trades, count(DISTINCT a) AS accounts, collect(DISTINCT c.name) AS clients,\n"
            "       sum(CASE WHEN x.txn_type IN ['BUY', 'CAPITAL_CALL'] THEN x.amount_usd ELSE 0 END) AS bought,\n"
            "       toString(min(x.date)) AS first, toString(max(x.date)) AS last", {"did": dec["id"]})
        if impl and impl[0]["trades"]:
            i = impl[0]
            facts.append(Fact("implementation",
                              f"{_n(i['trades'], 'trade')} in {_n(i['accounts'], 'account')} for "
                              f"{_n(len(i['clients']), 'client')} ({', '.join(sorted(i['clients']))}); "
                              f"{_usd(i['bought'])} bought or called "
                              + (f"on {_fmt_date(i['first'])}." if i["first"] == i["last"] else
                                 f"between {_fmt_date(i['first'])} and {_fmt_date(i['last'])}."),
                              [dec["id"]], {**i, "decision": dec["id"]}))
    _graph_for(rec, "decision-provenance", {"theme": theme["name"]})
    return facts


def _company_graph(rec: _Recorder, company_id: str, client_ids: list[str] | None = None) -> None:
    rec.graph(
        "Draw the graph above",
        "MATCH (co:Company {id: $cid})\n"
        "CALL (co) {\n"
        "  MATCH p = (c:Client)-[:OWNS]->(:Fund)-[:INVESTED_IN]->(co)\n"
        "  WHERE $clients IS NULL OR c.id IN $clients\n"
        "  RETURN p\n"
        "  UNION\n"
        "  MATCH p = (c:Client)<-[:ABOUT]-(:Document)-[:MENTIONS]->(co)\n"
        "  WHERE $clients IS NULL OR c.id IN $clients\n"
        "  RETURN p\n"
        "}\n"
        "RETURN p", {"cid": company_id, "clients": client_ids})


def strategy_company_exposure(rec: _Recorder, linked: dict) -> list[Fact]:
    company = linked["companies"][0]
    rows = rec.run("Clients exposed to the company, through funds",
        "MATCH (c:Client)-[o:OWNS]->(f:Fund)-[i:INVESTED_IN]->(co:Company {id: $cid})\n"
        "WITH c, sum(o.market_value * i.weight / 100.0) AS look_through,\n"
        "     collect(f.name + ' (' + toString(i.weight) + '%)') AS via\n"
        "MATCH (c)-[o2:OWNS]->(:Fund)\n"
        "WITH c, look_through, via, sum(o2.market_value) AS total\n"
        "OPTIONAL MATCH (c)-[:ADVISED_BY]->(adv:Person)\n"
        "RETURN c.id AS id, c.name AS client, look_through, total, via, adv.name AS advisor\n"
        "ORDER BY look_through DESC", {"cid": company["id"]})
    facts = []
    for r in rows:
        facts.append(Fact("company_exposure",
                          f"{r['client']}: {_usd(r['look_through'])} look-through {company['name']} exposure "
                          f"({_pct(100 * r['look_through'] / r['total'])} of {_usd(r['total'])}) via {', '.join(r['via'])}; "
                          f"advisor {r['advisor']}.", [r["id"]], r))
    comms = rec.run("Client communications that mention the company",
        "MATCH (d:Document)-[r:MENTIONS]->(:Company {id: $cid})\n"
        "MATCH (c:Client)\n"
        "WHERE EXISTS { (d)-[:ABOUT]->(c) } OR EXISTS { (d)-[:SENT_TO]->(:Person)-[:CONTACT_FOR]->(c) }\n"
        "   OR EXISTS { (d)<-[:SENT]-(:Person)-[:CONTACT_FOR]->(c) }\n"
        "   OR EXISTS { (d)-[:RECORDS]->(:Meeting)-[:FOR_CLIENT]->(c) }\n"
        "OPTIONAL MATCH (a:Person)-[:AUTHORED|SENT]->(d)\n"
        "RETURN d.id AS id, d.title AS title, d.doc_type AS type, toString(d.date) AS date, c.name AS client,\n"
        "       collect(DISTINCT a.name) AS authors, r.evidence AS evidence ORDER BY client, date", {"cid": company["id"]})
    for d in comms:
        who = f" ({', '.join(d['authors'])})" if d["authors"] else ""
        facts.append(Fact("client_communication",
                          f"{_fmt_date(d['date'])} {d['type']} with {d['client']}: '{d['title']}'{who}: "
                          f"\"{(d['evidence'] or '')[:220]}\"", [d["id"]], d))
    _company_graph(rec, company["id"], [r["id"] for r in rows[:6]] or None)
    return facts





def strategy_client_company_exposure(rec: _Recorder, linked: dict) -> list[Fact]:
    client, company = linked["clients"][0], linked["companies"][0]
    _overview, facts = _client_overview(rec, client["id"])
    rows = rec.run("The client's holdings of the company, through funds",
        "MATCH (:Client {id: $cl})-[o:OWNS]->(f:Fund)-[i:INVESTED_IN]->(:Company {id: $co})\n"
        "RETURN f.name AS fund, o.market_value AS position, i.weight AS weight,\n"
        "       o.market_value * i.weight / 100.0 AS look_through ORDER BY look_through DESC",
        {"cl": client["id"], "co": company["id"]})
    for r in rows:
        facts.append(Fact("holding", f"{r['fund']}: position {_usd(r['position'])}, {company['name']} weight "
                                     f"{r['weight']}% -> {_usd(r['look_through'])} look-through.", [], r))
    _company_graph(rec, company["id"], [client["id"]])
    return facts


def strategy_expertise(rec: _Recorder, linked: dict) -> list[Fact]:
    if linked["concepts"]:
        target_label, target = "Concept", linked["concepts"][0]
    elif linked["companies"]:
        target_label, target = "Company", linked["companies"][0]
    else:
        target_label, target = "Theme", linked["themes"][0]
    rows = rec.run("People who wrote about or discussed it",
        f"MATCH (x:{target_label} {{id: $id}})\n"
        "MATCH (p:Person)\n"
        "OPTIONAL MATCH (p)-[:AUTHORED|SENT]->(d:Document)-[:MENTIONS]->(x)\n"
        "WITH p, x, collect(DISTINCT d.title) AS docs\n"
        "OPTIONAL MATCH (p)-[:ATTENDED]->(m:Meeting)-[:DISCUSSED]->(x)\n"
        "WITH p, docs, collect(DISTINCT m.title + ' (' + toString(m.date) + ')') AS meetings\n"
        "WHERE size(docs) + size(meetings) > 0\n"
        "RETURN p.id AS id, p.name AS name, p.title AS title, p.organization AS org, docs, meetings,\n"
        "       2 * size(docs) + size(meetings) AS score ORDER BY score DESC, name LIMIT 8", {"id": target["id"]})
    facts = []
    for r in rows:
        facts.append(Fact("expert",
                          f"{r['name']} ({r['title']}, {r['org']}): {_n(len(r['docs']), 'document')} on {target['name']}"
                          f"{_paren(r['docs'])} and {_n(len(r['meetings']), 'meeting')} where it was discussed"
                          f"{_paren(r['meetings'], 3)}.", [r["id"]], r))
    rec.graph("Draw the graph above",
              f"MATCH (x:{target_label} {{id: $id}})\n"
              "MATCH p = (:Person)-[:AUTHORED|SENT|ATTENDED]->()-[:MENTIONS|DISCUSSED]->(x)\n"
              "RETURN p LIMIT 60", {"id": target["id"]})
    return facts


def strategy_hybrid(rec: _Recorder, linked: dict) -> list[Fact]:
    """No entity linked: start from vector search, then expand to the entities those documents mention."""
    from .embed import vector_search
    chunks = vector_search(rec.result.question, k=5)
    doc_ids = list(dict.fromkeys(c["doc_id"] for c in chunks))
    facts = [Fact("passage", f"'{c['title']}' ({c['doc_type']}, {c['date']}): \"{c['text'][:260]}\"", [c["doc_id"]], c)
             for c in chunks]
    rows = rec.run("What the matching documents mention",
        "MATCH (d:Document)-[:MENTIONS]->(x) WHERE d.id IN $ids AND (x:Company OR x:Fund OR x:Client OR x:Theme)\n"
        "OPTIONAL MATCH (x)<-[:INVESTED_IN]-(f:Fund)<-[:OWNS]-(c:Client)\n"
        "RETURN labels(x)[0] AS label, x.name AS name, collect(DISTINCT d.id) AS docs,\n"
        "       collect(DISTINCT f.name)[..4] AS funds, count(DISTINCT c) AS clients", {"ids": doc_ids})
    for r in rows:
        extra = f"; held by {', '.join(r['funds'])} ({r['clients']} clients)" if r["funds"] else ""
        facts.append(Fact("entity", f"{r['label']} {r['name']} appears in {', '.join(r['docs'])}{extra}.", r["docs"], r))
    rec.graph("Draw the graph above",
              "MATCH p = (d:Document)-[:MENTIONS]->() WHERE d.id IN $ids RETURN p LIMIT 80", {"ids": doc_ids})
    return facts


STRATEGIES = {
    "client_theme_impact": strategy_client_theme_impact,
    "decision_provenance": strategy_decision_provenance,
    "company_exposure": strategy_company_exposure,
    "client_company_exposure": strategy_client_company_exposure,
    "expertise": strategy_expertise,
    "hybrid": strategy_hybrid,
}
STRATEGY_LABELS = {
    "client_theme_impact": "Client impact: holdings -> look-through exposure -> decisions -> trades -> meetings -> documents",
    "decision_provenance": "Decision provenance: decision -> memo -> cited research -> meetings -> people -> trades",
    "company_exposure": "Company exposure: company <- funds <- clients, plus client communications",
    "client_company_exposure": "Client x company: look-through positions",
    "expertise": "Expertise: people -> documents & meetings -> concept",
    "hybrid": "Hybrid: vector entry points -> 1-hop graph expansion",
}


# =============================================================================
# answers
# =============================================================================
def _context_from_facts(question: str, linked: dict, strategy: str, facts: list[Fact]) -> str:
    window = f"{linked['since']} to {linked['as_of']}" if linked["since"] else f"through {linked['as_of']}"
    lines = [f"QUESTION: {question}", f"DATA AS OF: {linked['as_of']}; TIME WINDOW: {window}",
             f"RETRIEVAL: {STRATEGY_LABELS[strategy]}", ""]
    current = None
    for f in facts:
        if f.kind != current:
            lines.append(f"## {f.kind.upper().replace('_', ' ')}")
            current = f.kind
        tags = " ".join(f"[{s}]" for s in f.sources if s)
        lines.append(f"- {f.text} {tags}".rstrip())
    return "\n".join(lines)


def _llm_answer(question: str, context: str) -> tuple[str, str]:
    from .llm import LLMError, text_call
    try:
        text = text_call(ANSWER_SYSTEM, f"{context}\n\nAnswer the question: {question}",
                         effort=config.LLM_ANSWER_EFFORT)
        return text, f"claude:{config.LLM_MODEL}"
    except LLMError as exc:
        raise RuntimeError(str(exc)) from exc


def _template_answer(strategy: str, linked: dict, facts: list[Fact]) -> str:
    """Composes a readable answer directly from graph facts (used when no LLM is configured)."""
    by_kind: dict[str, list[Fact]] = {}
    for f in facts:
        by_kind.setdefault(f.kind, []).append(f)

    def cite(f: Fact) -> str:
        return " ".join(f"[{s}]" for s in f.sources if s)

    def docs_line(f: Fact) -> str:
        d = f.data
        who = f" - {', '.join(d['authors'])}" if d.get("authors") else ""
        return f"- {_fmt_date(d['date'])} {d['type']}: *{d['title']}*{who} {cite(f)}"

    out: list[str] = []
    if strategy == "client_theme_impact":
        client = linked["clients"][0]["name"]
        theme = linked["themes"][0]["name"]
        window = f"{_fmt_date(linked['since'])} - {_fmt_date(linked['as_of'])}" if linked["since"] else "to date"
        exp = by_kind.get("exposure", [None])[0]
        decisions = by_kind.get("decision", [])
        mine = [d for d in decisions if d.data.get("affects_client")]
        trades = by_kind.get("trade", [])
        client_docs = by_kind.get("client_document", [])
        internal_docs = by_kind.get("internal_document", [])
        meetings = by_kind.get("client_meeting", [])
        out.append(f"**{client} - {theme} ({window})**")
        if exp:
            limit = exp.data.get("guideline")
            status = ""
            if limit is not None:
                status = f", {'above' if exp.data['pct'] > limit else 'within'} the firm's {limit:.0f}% guideline"
            out.append(f"\n{client} has **{exp.data['pct']}% look-through exposure** to {theme} "
                       f"({_usd(exp.data['exposed'])} of {_usd(exp.data['total'])}){status}. In this window: "
                       f"{_n(len(mine), 'Investment Committee decision')} on the theme implemented in its accounts, "
                       f"{_n(len(trades), 'theme-related trade')}, {_n(len(meetings), 'client meeting')}, "
                       f"{_n(len(client_docs), 'client communication')} and {_n(len(internal_docs), 'internal document')}"
                       f" that name the client.")
        if by_kind.get("holding") or by_kind.get("adjacent_exposure"):
            out.append("\n**Where the exposure sits**")
            for f in by_kind.get("holding", []) + by_kind.get("adjacent_exposure", []):
                out.append(f"- {f.text}")
        if decisions:
            out.append("\n**Decisions that affected it**")
            for f in decisions:
                d = f.data
                flag = " - implemented in this client's accounts" if d.get("affects_client") else ""
                out.append(f"- **{d['id']}** ({_fmt_date(d['date'])}, vote {d['vote']}): {d['title']}{flag} {cite(f)}")
        if trades:
            out.append("\n**Trades executed**")
            for f in trades:
                out.append(f"- {f.text} {cite(f)}")
        if meetings or client_docs:
            out.append("\n**Conversations with the client**")
            for f in meetings:
                out.append(f"- {f.text} {cite(f)}")
            for f in client_docs:
                out.append(docs_line(f))
        if internal_docs:
            out.append("\n**Internal documents that name the client**")
            for f in internal_docs:
                out.append(docs_line(f))
        if by_kind.get("meeting"):
            out.append("\n**Committee and research discussions of the theme**")
            for f in by_kind["meeting"]:
                d = f.data
                people = ", ".join(d["attendees"][:4]) + ("..." if len(d["attendees"]) > 4 else "")
                out.append(f"- {_fmt_date(d['date'])} {d['title']} ({people}) {cite(f)}")
        if by_kind.get("research"):
            out.append("\n**Research behind the view**")
            for f in by_kind["research"]:
                d = f.data
                out.append(f"- {_fmt_date(d['date'])} *{d['title']}* - {', '.join(d['authors'])} {cite(f)}")
    elif strategy == "decision_provenance":
        theme = linked["themes"][0]["name"]
        decisions = by_kind.get("decision", [])
        verb = {"increase": "increased", "decrease": "reduced"}.get(linked["direction"], "changed")
        out.append(f"**Why we {verb} {theme} exposure**")
        if not decisions:
            out.append("\nNo matching Investment Committee decisions were found.")
        labels = {"cited": "Cited", "decision_meeting": "Decided", "prior_meeting": "Discussed",
                  "prior_document": "Correspondence"}
        for f in decisions:
            d = f.data
            out.append(f"\n**{d['id']} - {_fmt_date(d['date'])} (vote {d['vote']})**: {d['title']} {cite(f)}")
            if d.get("memo_title"):
                out.append(f"- Proposed in *{d['memo_title']}* by {', '.join(d['authors'])} [{d['memo_id']}]")
            timeline = [x for x in facts if x.data.get("decision") == d["id"] and x.kind in labels]
            timeline.sort(key=lambda x: x.data.get("date") or "")
            for x in timeline:
                out.append(f"- {labels[x.kind]}: {x.text} {cite(x)}")
            for x in facts:
                if x.kind == "implementation" and x.data.get("decision") == d["id"]:
                    out.append(f"- Implemented: {x.text}")
    elif strategy in ("company_exposure", "client_company_exposure"):
        out.append(f"**{linked['companies'][0]['name']} exposure by client (look-through)**")
        for f in by_kind.get("company_exposure", []) + by_kind.get("holding", []):
            out.append(f"- {f.text} {cite(f)}")
        if by_kind.get("client_communication"):
            out.append("\n**What we told clients**")
            for f in by_kind["client_communication"]:
                out.append(f"- {f.text} {cite(f)}")
    elif strategy == "expertise":
        out.append("**People with the deepest involvement**")
        for f in by_kind.get("expert", []):
            out.append(f"- {f.text}")
    else:
        out.append("**Related information found**")
        for f in facts:
            out.append(f"- {f.text} {cite(f)}")
    out.append("\n_Answer composed from graph facts (no LLM configured). Every bullet is traceable to its source._")
    return "\n".join(out)


def _sources_from_facts(facts: list[Fact]) -> list[dict]:
    ids = []
    for f in facts:
        for s in f.sources:
            if s and s.startswith("DOC-") and s not in ids:
                ids.append(s)
    if not ids:
        return []
    rows = db.run("MATCH (d:Document) WHERE d.id IN $ids RETURN d.id AS id, d.title AS title, d.doc_type AS type, "
                  "toString(d.date) AS date, d.source_system AS system", {"ids": ids})
    order = {i: n for n, i in enumerate(ids)}
    return sorted(rows, key=lambda r: order[r["id"]])


def graph_rag(question: str, as_of: date | None = None, use_llm: bool | None = None) -> RagResult:
    t0 = time.perf_counter()
    res = RagResult(mode="graph", question=question)
    linked = link_question(question, as_of)
    res.linked = linked
    res.strategy = choose_strategy(linked)
    rec = _Recorder(res)
    t1 = time.perf_counter()
    res.facts = STRATEGIES[res.strategy](rec, linked)
    t2 = time.perf_counter()
    res.context = _context_from_facts(question, linked, res.strategy, res.facts)
    res.sources = _sources_from_facts(res.facts)
    use_llm = config.llm_available() if use_llm is None else use_llm
    if use_llm:
        try:
            res.answer, res.answer_engine = _llm_answer(question, res.context)
        except RuntimeError as exc:
            res.warnings.append(f"LLM unavailable ({exc}); showing the graph-composed answer.")
    if not res.answer:
        res.answer, res.answer_engine = _template_answer(res.strategy, linked, res.facts), "template"
    t3 = time.perf_counter()
    res.timings_ms = {"link": round(1000 * (t1 - t0)), "retrieve": round(1000 * (t2 - t1)),
                      "answer": round(1000 * (t3 - t2))}
    return res


# =============================================================================
# standard RAG
# =============================================================================
def _split_sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text)
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z\"'(])", text)
    return [p.strip() for p in parts if len(p.strip()) > 25]


def _body_of(text: str) -> str:
    parts = text.split("\n\n", 1)
    return parts[1] if len(parts) == 2 else text


def _first_sentences(text: str, n: int) -> str:
    return " ".join(_split_sentences(text)[:n])


_HEADER_LINE = re.compile(r"^(From|To|Cc|Date|Subject|Authors?|Published|Borrower|Prepared by|Participants|"
                          r"Meeting Type|Decision Reference|For Meeting|Client|Owner|Type):", re.IGNORECASE)


def _passage_sentences(chunk: dict) -> list[str]:
    """Sentences of a retrieved passage, without document header lines (title, From:, Date: ...)."""
    lines = chunk["text"].splitlines()
    if chunk.get("chunk_id", "").endswith("#00") and lines:
        lines = lines[1:]  # the first chunk starts with the document title
    clean = []
    for line in lines:
        t = line.strip()
        if not t or _HEADER_LINE.match(t) or (t.endswith(":") and len(t.split()) <= 4):
            continue  # header field or a bare section label such as "Discussion:"
        clean.append(re.sub(r"^[-*]\s+", "", t))
    return _split_sentences("\n".join(clean))


def _extractive_answer(question: str, chunks: list[dict], n: int = 5) -> str:
    from .embed import embed_passages, embed_query
    import numpy as np
    candidates, seen = [], set()
    for c in chunks:
        for s in _passage_sentences(c):
            if s not in seen:
                seen.add(s)
                candidates.append((s, c["doc_id"]))
    if not candidates:
        return "No relevant passages were found."
    q = np.array(embed_query(question))
    vecs = np.array(embed_passages([s for s, _ in candidates]))
    scores = vecs @ q / (np.linalg.norm(vecs, axis=1) * np.linalg.norm(q) + 1e-9)
    best = sorted(range(len(candidates)), key=lambda i: -scores[i])[:n]
    lines = ["**Most relevant passages**"]
    for i in sorted(best, key=lambda i: -scores[i]):
        s, doc_id = candidates[i]
        lines.append(f"- {s} [{doc_id}]")
    lines.append("\n_Extractive answer (best-matching sentences from the top chunks; no LLM configured)._")
    return "\n".join(lines)


def standard_rag(question: str, k: int = 6, use_llm: bool | None = None) -> RagResult:
    from .embed import vector_search
    t0 = time.perf_counter()
    res = RagResult(mode="standard", question=question, strategy="vector")
    res.chunks = vector_search(question, k=k)
    res.cypher.append("CALL db.index.vector.queryNodes('chunkEmbedding', $k, $embedding) YIELD node, score")
    t1 = time.perf_counter()
    blocks = [f"[{c['doc_id']} | {c['doc_type']} | {c['date']} | {c['title']}]\n{c['text']}" for c in res.chunks]
    res.context = f"QUESTION: {question}\n\nCONTEXT PASSAGES:\n\n" + "\n\n".join(blocks)
    seen = []
    for c in res.chunks:
        if c["doc_id"] not in [s["id"] for s in seen]:
            seen.append({"id": c["doc_id"], "title": c["title"], "type": c["doc_type"], "date": c["date"],
                         "system": c["source_system"]})
    res.sources = seen
    use_llm = config.llm_available() if use_llm is None else use_llm
    if use_llm:
        try:
            res.answer, res.answer_engine = _llm_answer(question, res.context)
        except RuntimeError as exc:
            res.warnings.append(f"LLM unavailable ({exc}); showing the extractive answer.")
    if not res.answer:
        res.answer, res.answer_engine = _extractive_answer(question, res.chunks), "extractive"
    t2 = time.perf_counter()
    res.timings_ms = {"retrieve": round(1000 * (t1 - t0)), "answer": round(1000 * (t2 - t1))}
    return res


# =============================================================================
# coverage comparison
# =============================================================================
def key_facts(graph_result: RagResult) -> list[dict]:
    """Ground-truth checklist derived from the graph retrieval: what a complete answer must contain.

    Each item has a label and probe strings; an answer context "covers" the item when any probe appears in it.
    """
    items: list[dict] = []
    facts = graph_result.facts
    if graph_result.strategy == "client_theme_impact":
        for f in facts:
            if f.kind == "client":
                items.append({"label": f"Advisor of record: {f.data['advisor']}", "probes": [f.data["advisor"]]})
            if f.kind == "exposure":
                items.append({"label": f"Current look-through exposure ({f.data['pct']}%)",
                              "probes": [f"{f.data['pct']}%", f"{f.data['pct']} %"]})
            if f.kind == "decision" and f.data.get("affects_client"):
                items.append({"label": f"Decision {f.data['id']}: {f.data['title'][:60]}", "probes": [f.data["id"]]})
            if f.kind == "trade" and f.data.get("decision"):
                amt = f.data["amount"]
                items.append({"label": f"Trade {_fmt_date(f.data['date'])}: {f.data['type']} {_usd(amt)} {f.data['fund']}",
                              "probes": _amount_probes(amt)})
            if f.kind == "holding" and f.data["fund_id"] == "FND-PC2":
                items.append({"label": "Private credit exposure (Private Credit Fund II)",
                              "probes": ["Private Credit Fund II", "PCF II"]})
    elif graph_result.strategy == "decision_provenance":
        for f in facts:
            if f.kind == "decision":
                items.append({"label": f"Decision {f.data['id']} ({_fmt_date(f.data['date'])})", "probes": [f.data["id"]]})
            if f.kind == "cited":
                items.append({"label": f"Research cited: {f.data['title'][:55]}", "probes": [f.data["title"][:40]]})
            if f.kind == "decision_meeting":
                items.append({"label": f"Decision meeting {_fmt_date(f.data['date'])} and its attendees",
                              "probes": [_fmt_date(f.data["date"]), f.data["date"]]})
            if f.kind == "implementation":
                items.append({"label": f"{f.data['decision']} implementation ({f.data['trades']} trades)",
                              "probes": [f"{f.data['trades']} trades"]})
    else:
        for f in facts[:8]:
            for s in f.sources[:1]:
                items.append({"label": f.text[:70], "probes": [s]})
    dedup, seen = [], set()
    for it in items:
        if it["label"] not in seen:
            seen.add(it["label"])
            dedup.append(it)
    return dedup


def _amount_probes(amount: float) -> list[str]:
    a = float(amount)
    probes = [f"${a:,.0f}", f"{_usd(a)}"]
    if a >= 1_000_000:
        probes += [f"${a / 1_000_000:.2f} million", f"${a / 1_000_000:.1f} million", f"${a / 1_000_000:.2f}M"]
    else:
        probes += [f"${a / 1000:.0f}k", f"${a / 1000:.0f}K", f"${a / 1000:.0f},000"]
    return list(dict.fromkeys(probes))


def coverage(items: list[dict], context: str) -> list[bool]:
    low = context.lower()
    return [any(p.lower() in low for p in it["probes"]) for it in items]
