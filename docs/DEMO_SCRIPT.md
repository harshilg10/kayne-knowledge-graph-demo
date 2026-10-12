# Demo Script: Knowledge Graphs, Semantic Models and Graph-RAG

**Audience:** wealth management / investment research leadership and their technology team.
**Their question:** *How does unstructured content get graphed, and how does a semantic model enable that graph?*
**Length:** about 25 minutes plus Q&A. Every number below comes from the built demo graph (`make build`).

## Before the meeting (5 minutes)

1. `scripts/neo4j_start.sh`, then `.venv/bin/python -m kgdemo.build` (resets the graph to a known state).
2. `.venv/bin/python -m kgdemo.server` and open http://localhost:8501. Use ← and → (or a clicker) to move between steps.
3. In the same browser, open Neo4j Browser (http://localhost:7474/browser/) and connect once, so the app's
   **Open in Neo4j Browser** buttons land in a connected session. Run `:style` and drop in `neo4j/browser_style.grass`
   for the same colors as the app.
4. Optional: with `ANTHROPIC_API_KEY` in `.env`, the app offers Claude for extraction and answers. Without it
   everything runs offline. Say which mode you are in; nothing is pre-recorded.

---

## 0. Framing (1 min) - *Overview*

> "Here is the kind of question your advisors and PMs actually ask: *Show me everything related to AI infrastructure
> investments that impacted one client in the last 12 months.* The answer lives in seven places: portfolio accounting,
> trading, CRM, email, meeting notes, research and due-diligence files. We'll show how a semantic model turns all of
> that into one graph, and why the model has to come first."

Point at the pipeline: Sources → Ingest → Extract → Semantic mapping → Knowledge graph → Cypher & Graph-RAG.

## 1. Source data (3 min) - *1 Data*

* **SQL data:** open the table picker; it is grouped by system (CRM, portfolio accounting, order management,
  security master, IC decision log).
  The book: 40 clients, 78 accounts at three custodians, 4,503 trades and cash flows since
  January 2025, daily NAVs for the mutual funds and quarterly marks for the private credit fund. Show `holdings`
  and `transactions` (type "Hartwell" in the row filter to narrow them to the hero client).
* **Documents:** 101 documents across six types. Open the **Investment Committee Meeting (2026-01-15)** note,
  then a research PDF and an email. Each has a different format, and the parser handles all of them.

> "The structured data tells us *what* happened: trades, holdings. The documents tell us *why*. Nobody can join them
> today, because a PDF has no foreign keys."

## 2. Semantic model (4 min) - *2 Semantic model*

* **Ontology:** the diagram of entity types and relationships. Call out the three origins of relationships:
  *structured* (OWNS, HOLDS, INVESTED_IN), *extracted* (ATTENDED, DISCUSSED, MENTIONS) and *derived*
  (business rules such as `Client -OWNS-> Fund`, defined as "any of the client's accounts holds the fund").
* **Vocabulary:** *AI Infrastructure* is selected. Concepts like *GPU Capacity*, *Hyperscaler Capex*,
  *Liquid Cooling* and *AI Data Centers* roll up to it.
* **Keyword search vs meaning:** the key slide.

> "**Without the semantic layer, you're just searching text.** A keyword search for 'AI infrastructure' finds
> 46 documents. **With the semantic layer, you understand meaning:** the model finds 56, including 24
> that never use the phrase. They talk about GPU capacity, liquid cooling, hyperscaler capex. Every one of them
> carries the concept that connected it, so the result is explainable."

## 3. Unstructured → graph: the "aha" (4 min) - *3 Text → graph*

Leave the default document selected: the Investment Committee note from the brief.

```
Investment Committee Meeting
Date: 2026-01-15
Participants:
Douglas Whitfield
Meredith Calloway

Discussion:
We remain bullish on Nvidia and other AI infrastructure providers.
The technology team believes demand for GPU capacity will continue through 2027.
```

Click **Extract**. Expected entities: Douglas Whitfield, Meredith Calloway, Nvidia, AI Infrastructure, Investment Committee Meeting,
GPU Capacity (plus the Investment Committee, linked through the meeting type).
Expected relationships include:

```
Douglas Whitfield -> ATTENDED  -> Meeting       Meredith Calloway -> ATTENDED  -> Meeting
Meeting           -> DISCUSSED -> Nvidia        Meeting           -> DISCUSSED -> AI Infrastructure
Meeting           -> DISCUSSED -> GPU Capacity  Document          -> MENTIONS  -> Nvidia
Meeting           -> HELD_BY   -> Investment Committee
```

> "Notice what the model did. 'Nvidia' resolved to *one* canonical company (the same node the funds invest in).
> 'GPU capacity' isn't a keyword match: the vocabulary maps it to AI Infrastructure. The participants list became
> ATTENDED edges because the model defines what a meeting is. That's the aha: the graph is only as good as the
> semantic model behind the extraction."

Click **Write to the knowledge graph**. The graph below shows this note connected across the corpus; **Open in Neo4j
Browser** shows the same neighbourhood in Neo4j.
*Optional live moment:* click **or paste a note**, add a line such as "Elena Vasquez raised concerns about liquid
cooling lead times at Vertiv.", then extract again. A new person, company and concept appear, all resolved.

## 4. Graph queries and Neo4j (7 min) - *4 Queries*, then Neo4j Browser

Every query runs in the app and has an **Open in Neo4j Browser** button (the query arrives in the Browser editor with
its parameters filled in; press Run).

1. The three queries from the brief, verbatim: theme documents, people who discussed Nvidia, investment impact.
2. **Client → Fund → Nvidia → Meeting Notes → Investment Committee**: the path from the brief. Open it in Neo4j
   Browser and double-click nodes to expand them.

   > "This is where Neo4j shines: the relationships are first-class, so the path *is* the explanation."
3. **Everything AI-infrastructure related that impacted a client**: the Hartwell picture in one graph.
4. **Look-through theme exposure by client.** Hartwell Family Trust is at 13.0% today. In June the risk team
   measured 15.9%, above the firm's 15% guideline. A *Global Technology* fund and a private-credit loan to a data
   center developer carry AI exposure that no fund label shows.
5. **Hidden single-name concentration:** how much Nvidia the trust owns, and through which funds.
6. **Decision implementation:** IC-2026-004 became 120 trades in 60 accounts for
   32 clients. The link from structured trades to an unstructured decision is a shared identifier.

## 5. Graph-RAG (5 min) - *5 Graph-RAG*

Press **Ask** on the default question (Hartwell, AI infrastructure, last 12 months), then pick *What discussions led us
to increase AI infrastructure exposure?* Citations such as `DOC-EM-08` open the source document.

* **Left, standard RAG:** vector search returns six similar passages. They are relevant, but the result can't say
  which trades executed, what the exposure is now, or which decisions drove it.
* **Right, Graph-RAG:** the question is *linked* (client, theme, 12-month window), then the graph is traversed:
  holdings → look-through exposure → decisions → trades → meetings → documents → people. Every fact carries its source.
* **"What each approach could see":** the checklist lists the facts a complete answer needs (decisions, trades, current exposure, advisor, private-credit link) and whether each retriever *put them in front of the LLM*: 12/18 facts for standard RAG vs 18/18 facts for Graph-RAG on the first question. Be clear that this measures retrieval: an LLM can only cite what it was given. Some facts, such as the current look-through exposure, exist only as structured data, so no document search can find them.

* **Show the traversal** draws the part of the graph Graph-RAG walked.

> "Graph-RAG doesn't replace vector search. It gives the LLM the connected facts and the provenance, which is what
> makes an answer explainable to a client or a regulator."

## 6. Business value (2 min) - *6 Value*

Read the five benefits: each one has a proof point computed from this graph.
Close: *"The semantic model is the investment. Once it exists, every new source plugs into the same vocabulary,
identities and rules, and every AI use case (Copilot, Graph-RAG, search) gets grounded in it."*

---

## Likely questions

* **How is extraction done in production?** An LLM (Claude in this build, `claude-opus-5-5`) runs inside the
  semantic model: the ontology, vocabulary and identity catalog are in the prompt, the output is schema-constrained,
  and every relationship is validated against the ontology before loading. The offline rules engine you saw uses
  the same model. It is deterministic, and handy for regression tests.
* **Entity resolution?** Master data (CRM, security master, HR) provides identities and aliases. Text mentions resolve
  to them; anything unknown is created as a *candidate* for data stewardship instead of a duplicate.
* **Where do the semantics live?** In one versioned file (`ontology/semantic_model.yaml`). Business owners change
  vocabulary there; nothing in the pipeline is hard-coded to a theme.
* **Scale and security?** Neo4j handles billions of relationships. Row- and label-level access control, plus
  document-level entitlements on Document nodes, keep advisors to their own clients.
* **Copilot / Microsoft 365?** The graph sits behind a retrieval API or plugin, and Copilot grounds on graph facts
  with citations.

## Reset after the meeting

`.venv/bin/python -m kgdemo.build` restores the initial state (it removes anything written live).
