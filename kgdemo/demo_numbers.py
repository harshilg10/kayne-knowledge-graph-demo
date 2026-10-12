"""Computes the numbers quoted in the talk track from the live graph and renders docs/DEMO_SCRIPT.md.

    python -m kgdemo.demo_numbers
"""
from __future__ import annotations

import re

from . import neo4j_client as db
from . import queries, rag
from . import world as w
from .config import ROOT

TEMPLATE = ROOT / "docs" / "templates" / "DEMO_SCRIPT.md.tmpl"
OUT = ROOT / "docs" / "DEMO_SCRIPT.md"


def compute() -> dict[str, str]:
    n = {}
    n["DOCS"] = str(db.run("MATCH (d:Document) WHERE NOT d.id STARTS WITH 'DOC-LIVE' RETURN count(d) AS n")[0]["n"])
    n["CLIENTS"] = str(db.run("MATCH (c:Client) RETURN count(c) AS n")[0]["n"])
    n["ACCOUNTS"] = str(db.run("MATCH (a:Account) RETURN count(a) AS n")[0]["n"])
    n["TXNS"] = f"{db.run('MATCH (t:Transaction) RETURN count(t) AS n')[0]['n']:,}"
    kv = queries.by_id("keyword-vs-semantic")
    rows = db.run(kv.cypher, kv.params)
    n["SEM"] = str(len(rows))
    n["MISSED"] = str(sum(1 for r in rows if not r["found_by_keyword"]))
    n["KW"] = str(db.run("CALL db.index.fulltext.queryNodes('documentText', $p) YIELD node RETURN count(node) AS n",
                         {"p": kv.params["phrase"]})[0]["n"])
    lt = queries.by_id("look-through-exposure")
    now = {r["client"]: r["exposure_pct"] for r in db.run(lt.cypher, lt.params)}
    n["HW_NOW"] = f"{now['Hartwell Family Trust']:.1f}"
    n["HW_JUN"] = f"{w.look_through_exposure('C-001', 'THM-AI', '2026-06-15')['pct']:.1f}"
    impl = {r["decision"]: r for r in db.run(queries.by_id("decision-implementation").cypher,
                                             queries.by_id("decision-implementation").params)}
    n["IC004_TRADES"] = str(impl["IC-2026-004"]["trades"])
    n["IC004_ACCOUNTS"] = str(impl["IC-2026-004"]["accounts"])
    n["IC004_CLIENTS"] = str(impl["IC-2026-004"]["clients"])
    gr = rag.graph_rag(rag.PRESET_QUESTIONS[0], use_llm=False)
    std = rag.standard_rag(rag.PRESET_QUESTIONS[0], use_llm=False)
    items = rag.key_facts(gr)
    n["COV_GR"] = f"{sum(rag.coverage(items, gr.context))}/{len(items)} facts"
    n["COV_STD"] = f"{sum(rag.coverage(items, std.context))}/{len(items)} facts"
    return n


def render() -> dict[str, str]:
    numbers = compute()
    text = TEMPLATE.read_text()
    for key, value in numbers.items():
        text = text.replace(f"__{key}__", value)
    leftovers = sorted(set(re.findall(r"__[A-Z0-9_]+__", text)))
    if leftovers:
        raise ValueError(f"unfilled placeholders in {TEMPLATE.name}: {leftovers}")
    OUT.write_text(text)
    return numbers


if __name__ == "__main__":
    for k, v in render().items():
        print(f"{k:16s} {v}")
    print(f"wrote {OUT.relative_to(ROOT)}")
