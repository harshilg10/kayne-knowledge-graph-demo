# Knowledge Graph Demo: Wealth Management & Investment Research

A working, end-to-end demo of how **unstructured content gets graphed** and how a **semantic model** makes that
graph useful. It covers source data, the semantic model, entity extraction, Neo4j visualization, Cypher, and
Graph-RAG compared with standard RAG.

> The firm ("Arbor Peak Wealth Partners"), its people, clients, accounts, funds and private borrowers are fictional;
> the names were checked against public sources to avoid colliding with real firms, products or fund tickers.
> Listed companies (Nvidia, TSMC, ...) are real and appear only as fund holdings and research subjects; every opinion
> in the corpus belongs to the fictional firm.

## Quick start (macOS, already set up on this machine)

```bash
cd kg-demo
scripts/neo4j_start.sh                          # Neo4j 2026.01 Community; Browser at http://localhost:7474/browser/
.venv/bin/python -m kgdemo.build                # data -> documents -> extraction -> Neo4j -> embeddings (~1-2 min)
.venv/bin/python -m kgdemo.server               # demo app at http://localhost:8501
```

Neo4j login: user `neo4j`, password from `.env` (`NEO4J_PASSWORD`).

The app is a single page per demo step; ← and → (or a presentation clicker) move between steps. The built UI
(`web/dist`) is served by the Python server, so the demo machine needs no Node.js and runs offline. To change the UI,
edit `web/src` and run `make web`.

**Optional: Claude.** Put `ANTHROPIC_API_KEY=...` in `.env`. The app then offers Claude
(`claude-opus-5-5`) for live extraction and writes Graph-RAG and RAG answers with an LLM. To re-extract the whole
corpus with Claude, run `.venv/bin/python -m kgdemo.build --engine claude`. Without a key, everything still works
offline:
- extraction uses the semantic rules engine (same ontology, vocabulary and identity catalog);
- standard RAG shows the best-matching passages;
- Graph-RAG composes its answer directly from the retrieved graph facts.

Run `make test` to execute the test suite against the built graph.

## What the demo shows

| Step | Where | What you see |
|---|---|---|
| 1. Source data | app → *Data* | 13 structured exports (clients, accounts, holdings, transactions, fund NAVs, funds, companies, IC decisions, ...) and 101 documents: meeting notes (.md), CRM notes (.csv export), research (.pdf), emails (.eml), IC memos (.docx), due diligence (.pdf) |
| 2. Semantic model | app → *Semantic model*, `ontology/semantic_model.yaml` | the ontology, the business vocabulary (themes → concepts → synonyms) and the measured gap between keyword search and the semantic model |
| 3. Unstructured → graph | app → *Text → graph* | the Investment Committee note from the brief turned into entities and relationships, written to Neo4j live |
| 4. Graph queries + Neo4j | app → *Queries*, Neo4j Browser | the brief's three Cypher queries verbatim, the path Client → Fund → Nvidia → Meeting Notes → Investment Committee, look-through exposure, hidden concentration and decision implementation; each opens in Neo4j Browser with one click |
| 5. Graph-RAG | app → *Graph-RAG* | the same question answered by vector RAG and by Graph-RAG, with a fact-coverage comparison and the traversal |
| 6. Business value | app → *Value* | the five value points, each backed by a number from this graph |

The talk track, with timings and the exact numbers to expect, is in [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md).

## The story in the data

A fictional firm grows convinced that demand for GPU capacity will last through 2027. The Investment Committee
note from the brief is the January 15, 2026 meeting. In February the committee raises the AI Infrastructure Fund
allocation (IC-2026-004, approved 6-1 over the risk officer's concentration concern), and trades run in 60
accounts for 32 clients. The firm also lends to a GPU-dense data center developer (IC-2026-006) and to its liquid-cooling
supplier (IC-2026-013).

A mid-year look-through review then finds three families above the firm's 15% AI-exposure guideline, the
Hartwell Family Trust among them. Two things drive the overlap: their AI fund and Global Technology fund hold the
same names, and the private-credit loans add more. The committee caps single names and trims the overlap
(IC-2026-011).

Answering "everything AI infrastructure that impacted the Hartwell Family Trust" takes portfolio accounting,
trading, CRM, email, meeting notes, research and due-diligence documents together. That is the point of the demo.

## The data

`data/` holds source data only, in two separate sets of files:

| Folder | Contents |
|---|---|
| `data/structured/` | 13 CSV exports from the systems of record: CRM (`clients`, `contacts`, `advisors`), HR (`people`), portfolio accounting (`accounts`, `holdings`), order management (`transactions`), security master and pricing (`funds`, `fund_nav`, `companies`, `fund_holdings`, `company_themes`) and the IC decision log (`ic_decisions`) |
| `data/unstructured/` | 101 documents as found: `meeting_notes/*.md`, `ic_memos/*.docx`, `research/*.pdf`, `due_diligence/*.pdf`, `emails/*.eml` and the CRM notes export `crm/crm_notes_export.csv` |

It is a mid-sized book of business: 40 clients (households, trusts, family offices, foundations and
endowments) with 78 accounts at Schwab, Fidelity and Pershing plus four private-credit LP interests, about
$477 million under management, 97 people, 50 companies, 10 funds, 443 positions and 4,503 trades and cash flows
from January 2025 to September 2026. The built graph has about 5,300 nodes and 12,900 relationships.

The structured data behaves like real bookkeeping. Positions are kept in shares and priced at each fund's daily NAV
(the private credit fund strikes quarterly marks), on the NYSE trading calendar with T+1 settlement. Holdings carry
average-cost basis and unrealized gains. The flows are the ones a wealth manager actually books:

* model rebalances under each IC decision
* monthly bond-fund income, reinvested or paid to cash
* year-end and quarterly fund distributions
* tiered quarterly advisory fees
* systematic contributions and withdrawals, Roth IRA contributions, and RMDs sized with the IRS Uniform Lifetime
  Table
* foundation grants, endowment spending draws, and private-credit capital calls and distributions

Every number quoted in a document (trade sizes, exposures, account counts) is computed from this data, and
`tests/test_world.py` checks each one.

Two folders sit outside `data/`: `authoring/document_bodies/` (the text each document is rendered from) and
`build/` (extraction output and the build summary, regenerated by every build).

## Neo4j Browser and Bloom

* **Browser:** open http://localhost:7474/browser/. To apply the color scheme, run `:style` and drag
  `neo4j/browser_style.grass` onto the style panel. Then run the `:params` line at the top of
  `neo4j/demo_queries.cypher` and paste any query.
* **Bloom / Explore:** Bloom ships with Neo4j Desktop (free) and AuraDB ("Explore"); the Community server installed
  here includes Browser only. To use Bloom, add a remote connection in Neo4j Desktop to `bolt://localhost:7687`.
  Alternatively, point `NEO4J_URI` at an AuraDB Free instance (`neo4j+s://...`) and run the build again. Useful
  Bloom searches: `Hartwell Family Trust`, `Nvidia`, `AI Infrastructure`, `IC-2026-004`.

## Project layout

```
ontology/semantic_model.yaml   the semantic model: entities, relationships, vocabulary, rules, exposure model
kgdemo/                         pipeline + engines (see docs/ARCHITECTURE.md)
  world.py, manifest.py         master data, pricing, account flows, story and the 101 document specs
  generate_structured.py        -> data/structured/*.csv
  render_docs.py, ingest.py     -> data/unstructured/* (md, docx, pdf, eml, csv) -> parsed DocumentRecords
  extract_rules.py, extract_llm.py, extraction.py   entity & relationship extraction + semantic mapping
  graph_load.py, embed.py, build.py                 Neo4j load, business rules, vector index, one-command build
  queries.py, rag.py                                 demo queries, standard RAG vs Graph-RAG
  server.py, viz.py                                  the app's JSON API and graph payloads; serves web/dist
web/                            the demo app (React + TypeScript + Tailwind + Cytoscape); web/dist is the built UI
neo4j/                          Browser style sheet and query pack
data/structured/                CSV exports from the systems of record
data/unstructured/              documents as found (md, docx, pdf, eml, CRM export)
authoring/document_bodies/      the text each document is rendered from
build/                          extraction output and build summary (regenerated)
tests/                          pytest suite
```

## Rebuilding and resetting

`python -m kgdemo.build` always resets the graph and rebuilds it, so it is safe to run before every demo. Use
`--skip-render` to reuse existing raw files and `--skip-embed` to skip the vector index. Anything written live from
the app (pasted notes get the id prefix `DOC-LIVE-`) disappears on the next build.

## Setting it up on another Mac

```bash
brew install neo4j                                   # also installs OpenJDK 21
neo4j-admin dbms set-initial-password <password>     # before the first start
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env                                 # set NEO4J_PASSWORD (and optionally ANTHROPIC_API_KEY)
scripts/neo4j_start.sh && .venv/bin/python -m kgdemo.build
```

The first build downloads the embedding model `BAAI/bge-small-en-v1.5` (~65 MB) into `.cache/`. The demo runs
offline after that.

## Troubleshooting

* **The app says Neo4j is offline.** Run `scripts/neo4j_start.sh`; logs are in `/opt/homebrew/var/log/neo4j/`.
* **The graph is empty.** Run `.venv/bin/python -m kgdemo.build`.
* **Claude errors.** The app falls back to the offline engines and shows a warning; check `ANTHROPIC_API_KEY`.
* **Port 7474, 7687 or 8501 is busy.** Stop the other process, or run `.venv/bin/python -m kgdemo.server --port 8502`.
* **The app says the web UI is not built.** Run `make web` (needs Node.js: `brew install node`).
