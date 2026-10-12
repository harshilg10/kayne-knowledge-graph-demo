"""Graph payloads for the web app: Neo4j results -> {nodes, edges} with a primary label, caption and style hints."""
from __future__ import annotations

LABEL_COLORS = {
    "Client": "#E8A33D", "Account": "#F2C879", "Fund": "#4C8BF5", "Company": "#7B61FF", "Theme": "#E5484D",
    "Concept": "#F28B82", "Person": "#2BB673", "Advisor": "#1E8E5A", "Document": "#8D99AE", "Meeting": "#00A3BF",
    "Committee": "#0B6E7F", "Decision": "#D6336C", "Transaction": "#B0B7C3", "Chunk": "#DADDE2",
}
LABEL_SIZES = {"Client": 30, "Theme": 30, "Committee": 26, "Fund": 24, "Decision": 22, "Meeting": 22, "Company": 20,
               "Person": 18, "Advisor": 20, "Document": 16, "Concept": 16, "Account": 16, "Transaction": 10, "Chunk": 8}
LABEL_PRIORITY = ["Advisor", "Client", "Account", "Fund", "Company", "Theme", "Concept", "Person", "Document",
                  "Meeting", "Committee", "Decision", "Transaction", "Chunk"]
CAPTION_KEYS = {"Document": "title", "Meeting": "title", "Decision": "id", "Transaction": "txn_type", "Account": "id",
                "Chunk": "id"}
DOC_TYPE_SHORT = {"Meeting Notes": "Notes", "IC Memo": "Memo", "Research Report": "Research", "Due Diligence": "DD",
                  "Email": "Email", "CRM Note": "CRM"}


def primary_label(labels: list[str]) -> str:
    for label in LABEL_PRIORITY:
        if label in labels:
            return label
    return labels[0] if labels else "Node"


def short(text: str, n: int = 32) -> str:
    text = str(text)
    return text if len(text) <= n else text[: n - 1] + "…"


def caption_for(label: str, props: dict) -> str:
    key = CAPTION_KEYS.get(label, "name")
    value = props.get(key) or props.get("name") or props.get("title") or props.get("id") or label
    if label == "Meeting" and props.get("date"):
        return f"{short(value, 26)}\n{props['date']}"
    if label == "Document" and props.get("doc_type"):
        return short(f"{DOC_TYPE_SHORT.get(props['doc_type'], props['doc_type'])}: {value}", 34)
    if label == "Transaction" and props.get("amount_usd") is not None:
        return f"{value} ${props['amount_usd'] / 1000:,.0f}k"
    return short(value)


def graph_payload(nodes: list[dict], edges: list[dict]) -> dict:
    """neo4j_client.records_to_graph output -> the web app's graph format."""
    out_nodes = []
    for n in nodes:
        label = primary_label(n["labels"])
        out_nodes.append({"id": n["element_id"], "label": label, "labels": n["labels"],
                          "caption": caption_for(label, n["properties"]), "properties": n["properties"]})
    out_edges = [{"id": e["element_id"], "source": e["source"], "target": e["target"], "type": e["type"],
                  "properties": e.get("properties", {}), "inferred": bool(e.get("properties", {}).get("inferred"))}
                 for e in edges]
    return {"nodes": out_nodes, "edges": out_edges}
