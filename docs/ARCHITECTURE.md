# Architecture & Contracts

```
 STRUCTURED SOURCES (CSV exports)          UNSTRUCTURED SOURCES (data/unstructured)
 CRM, Portfolio Accounting, Order Mgmt,    meeting notes .md, IC memos .docx, research .pdf,
 Security Master, IC Decision Log          due diligence .pdf, emails .eml, CRM notes export .csv
            |                                              |
            |                                   ingest.py  (format parsers -> DocumentRecord)
            |                                              |
            |                         extraction (rules engine | Claude), constrained by
            |                         ontology/semantic_model.yaml + entity catalog
            |                                              |
            |                         semantic mapping: resolve to canonical ids, concept->theme,
            |                         domain/range validation  -> build/extracted/<DOC-ID>.json
            v                                              v
                      graph_load.py  ->  Neo4j  (+ business rules, e.g. Client-OWNS->Fund)
                                         embed.py -> Chunk nodes + vector index
                                              |
              queries.py (Cypher pack)   rag.py (standard RAG vs Graph-RAG)   server.py (API) -> web app
```

## Module map

| Module | Responsibility |
|---|---|
| `kgdemo/config.py` | paths, Neo4j/LLM settings, demo constants (`AS_OF_DATE` = 2026-09-30) |
| `kgdemo/world.py` | master data + story; daily NAV pricing; share-based simulation of every account flow; look-through exposure math |
| `kgdemo/manifest.py` | the 101 document specs (header facts, required mentions, briefs) |
| `kgdemo/generate_structured.py` | writes `data/structured/*.csv` (13 exports incl. `fund_nav.csv`) |
| `kgdemo/ontology.py` | loads the semantic model |
| `kgdemo/catalog.py` | entity catalog + gazetteer (longest-match, case rules) and `normalize_text` |
| `kgdemo/models.py` | `DocumentRecord`, `EntityRef`, `RelationshipRef`, `Extraction`, `meeting_id()` |
| `kgdemo/render_docs.py` | manifest + `authoring/document_bodies` -> realistic raw files in `data/unstructured` (md, docx, pdf, eml, csv) |
| `kgdemo/ingest.py` | raw files -> `DocumentRecord` (never reads the manifest) |
| `kgdemo/extract_rules.py` | offline extraction engine (ontology + catalog + document structure) |
| `kgdemo/extract_llm.py` | Claude extraction engine (structured outputs, ontology in the prompt) |
| `kgdemo/extraction.py` | shared semantic mapping + validation; engine selection; CLI |
| `kgdemo/neo4j_client.py` | driver, `run()`, `run_graph()`, value conversion |
| `kgdemo/graph_load.py` | schema, structured load, extraction load, business rules |
| `kgdemo/embed.py` | chunking + fastembed (`BAAI/bge-small-en-v1.5`, 384-d) + vector index |
| `kgdemo/queries.py` | named demo Cypher queries |
| `kgdemo/llm.py` | Claude client wrapper (extraction + answers), refusal/fallback handling |
| `kgdemo/rag.py` | standard RAG and Graph-RAG retrieval + answer composition |
| `kgdemo/viz.py` | graph payloads for the web app (primary label, caption) |
| `kgdemo/server.py` | FastAPI: JSON API for each demo step + serves the built UI; Neo4j Browser hand-off links |
| `kgdemo/build.py` | one-command pipeline |
| `kgdemo/validate_docs.py`, `kgdemo/writer_packet.py` | authoring brief + validator for the synthetic corpus |
| `kgdemo/eval_extraction.py` | extraction recall against the manifest ground truth |
| `kgdemo/export_queries.py` | writes the Neo4j Browser query pack from `queries.py` |
| `kgdemo/demo_numbers.py` | renders `docs/DEMO_SCRIPT.md` with numbers computed from the live graph |
| `web/` | the demo UI: React + TypeScript + Tailwind + Cytoscape.js (Vite build to `web/dist`) |

## Raw file contract (render_docs -> ingest)

File names: `data/unstructured/<folder>/<DOC-ID>__<slug>.<ext>`; the ingestion derives `doc_id` from the prefix
before `__`. Folders: `meeting_notes` (.md), `ic_memos` (.docx), `research` (.pdf), `due_diligence` (.pdf),
`emails` (.eml); CRM notes are rows of `crm/crm_notes_export.csv` (NoteId = doc id).

Header blocks (one field per line; ingestion parses them, the body follows after a blank line):

* Meeting notes (.md): line 1 = meeting title; `Date: YYYY-MM-DD`; `Meeting Type: <type>` (omitted for the
  hero note, where the type is inferred from the title); `Participants:` followed by one name per line, external
  people as `Name (Organization)`; then a blank line and the body.
* IC memo (.docx) paragraphs: `ARBOR PEAK WEALTH PARTNERS`, `INVESTMENT COMMITTEE MEMORANDUM`,
  `To: Investment Committee`, `From: A, B`, `Date: YYYY-MM-DD`, `Subject: <title>`,
  `Decision Reference: IC-YYYY-NNN`, `For Meeting: Investment Committee Meeting, YYYY-MM-DD`, body paragraphs,
  `Supporting Documents:` then one cited document title per paragraph, then a disclaimer paragraph.
* Research (.pdf): `ARBOR PEAK WEALTH PARTNERS | RESEARCH`, title, `Authors: A, B`, `Published: YYYY-MM-DD`,
  body, disclaimer.
* Due diligence (.pdf): `ARBOR PEAK WEALTH PARTNERS | PRIVATE CREDIT DUE DILIGENCE`, title,
  `Borrower: <company>`, `Prepared by: Name` or `Name (Organization)` (comma-separated), `Date: YYYY-MM-DD`,
  body, disclaimer.
* Email (.eml): RFC 5322 headers `From`, `To`, `Cc`, `Date`, `Subject`, `Message-ID`; plain-text body.
* CRM export (.csv): `NoteId, CreatedDate, ClientId, ClientName, Owner, Type, Subject, Body`.

## Graph contract (Neo4j)

Every node has `id` (unique per label, enforced by constraints). Dates are stored as Neo4j `date` values.

| Label | Properties |
|---|---|
| Person (+ `Advisor` for advisors) | id, name, title, department, person_type (employee/client_contact/external), organization, email; Advisor: office, start_date |
| Client | id, name, client_type, segment, risk_profile, client_since, city, notes |
| Account | id, name, account_number, registration, account_type, custodian, tax_status, model, opened_date, commitment_usd |
| Fund | id, name, ticker, share_class, asset_class, strategy, benchmark, inception_date, expense_ratio_pct, aum_usd_m, nav, nav_date |
| Company | id, name, legal_name, ticker, kind, sector, industry, country |
| Theme | id, name, definition |
| Concept | id, name, theme_id |
| Committee | id, name, charter |
| Decision | id, title, date, status, vote, direction, summary |
| Transaction | id, date (trade date), settle_date, txn_type (BUY, SELL, FEE, INCOME, DISTRIBUTION, CAPITAL_CALL), shares, price, amount_usd, order_reason |
| Document | id, title, doc_type, date, source_system, source_path, text, extraction_engine |
| Meeting | id, title, date, meeting_type |
| Chunk | id, doc_id, seq, text, embedding (384 floats) |

Relationship properties:

* structured: `HOLDS {shares, price, market_value, cost_basis, as_of}`, `INVESTED_IN {weight, since, as_of}`, `EXPOSED_TO {degree}`,
  `MEMBER_OF {role}`, `CONTACT_FOR {role}`, `RELATED_TO {rationale}`; every structured relationship has
  `origin: 'structured'`.
* extracted: `{origin: 'extracted', engine, method, evidence, doc_id}`; theme links inferred from a concept also
  carry `{inferred: true, via: '<concept name>'}`.
* derived: `OWNS {market_value, accounts, origin: 'derived', rule: 'R-OWNS'}`,
  `PURSUANT_TO {origin: 'structured', rule: 'R-TXN-DECISION'}`.

Indexes: uniqueness constraints on `id` for every label; full-text `documentText` on Document(title, text);
full-text `entityNames` on Person|Company|Fund|Client|Theme|Concept(name); vector `chunkEmbedding` on
Chunk(embedding), 384 dimensions, cosine.

Keys used in extraction JSON: `"<Label>:<id>"`, documents `"Document:<DOC-ID>"`, meetings
`"Meeting:<meeting_id(date, title)>"`.
