"""Shared semantic mapping, validation and orchestration for both extraction engines.

    python -m kgdemo.extraction                         # every document, offline rules engine
    python -m kgdemo.extraction --engine claude         # with Claude (falls back to rules per document)
    python -m kgdemo.extraction DOC-MN-03 DOC-ICM-03    # selected documents only

`finalize` is the step that makes either engine's output a graph of the semantic model: concept
mentions roll up to their themes (explainably, via the concept), every relationship is checked
against the ontology's domain and range, dangling and duplicate relationships are dropped, and
the result is put in a deterministic order.
"""
from __future__ import annotations

import argparse
import copy
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import config
from .extract_rules import EVIDENCE_MAX, ORIGIN_RANK, RulesExtractor, clip, normalize_title
from .models import DocumentRecord, EntityRef, Extraction, RelationshipRef, doc_key, entity_key, meeting_id, split_key
from .ontology import Ontology, load_ontology

ENGINES = ("rules", "claude")


# ---------------------------------------------------------------------------- semantic mapping
def finalize(ex: Extraction, record: DocumentRecord) -> Extraction:
    """Applies the semantic model to a raw extraction (the input is not modified)."""
    ex = copy.deepcopy(ex)
    onto = load_ontology()
    warnings = list(ex.warnings)
    entities = _merge_entities(ex.entities)
    relationships = _allowed(ex.relationships, onto, warnings)
    relationships = _connected(relationships, set(entities) | {doc_key(record.doc_id)}, warnings)
    relationships += _allowed(_concept_theme_links(entities, relationships, onto, warnings), onto, warnings)
    relationships = _dedupe(relationships)
    for r in relationships:
        r.evidence = clip(r.evidence, EVIDENCE_MAX)
    ordered = sorted(entities.values(), key=lambda e: e.key)
    return Extraction(
        doc_id=record.doc_id, engine=ex.engine,
        document={"id": record.doc_id, "title": record.title, "doc_type": record.doc_type, "date": record.date,
                  "source_system": record.source_system, "source_path": record.source_path},
        entities=ordered,
        relationships=sorted(relationships, key=lambda r: (r.type, r.source, r.target)),
        meeting=_meeting(ordered, record),
        warnings=list(dict.fromkeys(warnings)))


def _merge_entities(entities: list[EntityRef]) -> dict[str, EntityRef]:
    merged: dict[str, EntityRef] = {}
    for e in entities:
        have = merged.get(e.key)
        if have is None:
            merged[e.key] = e
            continue
        if ORIGIN_RANK.get(e.origin, 0) > ORIGIN_RANK.get(have.origin, 0):
            have.origin = e.origin
        have.mentions += [m for m in e.mentions if m not in have.mentions]
        have.spans += [s for s in e.spans if s not in have.spans]
        have.properties = {**e.properties, **have.properties}
    for e in merged.values():
        e.mentions = list(dict.fromkeys(e.mentions))
        e.spans = [list(s) for s in sorted({tuple(s) for s in e.spans})]
    return merged


def _label(key: str) -> str:
    return split_key(key)[0]


def _allowed(relationships: list[RelationshipRef], onto: Ontology, warnings: list[str]) -> list[RelationshipRef]:
    """(b) domain/range: keep a relationship only if the ontology allows its type between the labels."""
    kept = []
    for r in relationships:
        src, tgt = _label(r.source), _label(r.target)
        if onto.allows(r.type, src, tgt):
            kept.append(r)
        else:
            warnings.append(f"dropped {r.source} -{r.type}-> {r.target}: the semantic model does not allow "
                            f"{src} -{r.type}-> {tgt}")
    return kept


def _connected(relationships: list[RelationshipRef], keys: set[str], warnings: list[str]) -> list[RelationshipRef]:
    """(c) both endpoints must be the document or one of the extracted entities, and distinct."""
    kept = []
    for r in relationships:
        missing = [k for k in (r.source, r.target) if k not in keys]
        if missing:
            warnings.append(f"dropped {r.source} -{r.type}-> {r.target}: {', '.join(missing)} is not an "
                            f"extracted entity")
        elif r.source == r.target:
            warnings.append(f"dropped {r.source} -{r.type}-> {r.target}: a relationship needs two endpoints")
        else:
            kept.append(r)
    return kept


def _concept_theme_links(entities: dict[str, EntityRef], relationships: list[RelationshipRef], onto: Ontology,
                         warnings: list[str]) -> list[RelationshipRef]:
    """(a) every concept brings its broader theme; X-[MENTIONS|DISCUSSED]->Concept implies
    X-[same]->Theme {inferred, via: concept}, unless X already has that link to the theme."""
    for e in [e for e in entities.values() if e.label == "Concept"]:
        concept = onto.concepts.get(e.id)
        if concept is None:
            warnings.append(f"concept {e.key} is not in the semantic model vocabulary")
            continue
        theme = onto.themes[concept.theme_id]
        tkey = entity_key("Theme", theme.id)
        if tkey not in entities:
            entities[tkey] = EntityRef(key=tkey, label="Theme", id=theme.id, name=theme.name, origin="inferred")
    present = {(r.source, r.type, r.target) for r in relationships}
    inferred = []
    for r in relationships:
        if r.type not in ("MENTIONS", "DISCUSSED") or _label(r.target) != "Concept":
            continue
        concept = onto.concepts.get(split_key(r.target)[1])
        if concept is None:
            continue
        triple = (r.source, r.type, entity_key("Theme", concept.theme_id))
        if triple in present:               # explicit link, or already inferred from an earlier concept
            continue
        present.add(triple)
        inferred.append(RelationshipRef(source=r.source, type=r.type, target=triple[2], evidence=r.evidence,
                                         method="vocabulary", properties={"inferred": True, "via": concept.name}))
    return inferred


def _dedupe(relationships: list[RelationshipRef]) -> list[RelationshipRef]:
    """(d) one relationship per (source, type, target); the first one wins."""
    seen, out = set(), []
    for r in relationships:
        triple = (r.source, r.type, r.target)
        if triple not in seen:
            seen.add(triple)
            out.append(r)
    return out


def _meeting(entities: list[EntityRef], record: DocumentRecord) -> dict | None:
    if record.doc_type != "Meeting Notes":
        return None
    meetings = [e for e in entities if e.label == "Meeting"]
    if not meetings:
        return {"id": meeting_id(record.date, record.title), "title": record.title, "date": record.date,
                "meeting_type": (record.metadata or {}).get("meeting_type", "")}
    m = next((e for e in meetings if e.id == meeting_id(record.date, record.title)), meetings[0])
    return {"id": m.id, "title": m.name, "date": m.properties.get("date", record.date),
            "meeting_type": m.properties.get("meeting_type", "")}


# ---------------------------------------------------------------------------- orchestration
def build_title_index(records: list[DocumentRecord]) -> dict[str, str]:
    """Normalized document title -> doc id, for resolving citations. A title shared by several
    documents (e.g. every "Investment Committee Meeting") is ambiguous and left out."""
    ids: dict[str, set[str]] = {}
    for r in records:
        title = normalize_title(r.title)
        if title:
            ids.setdefault(title, set()).add(r.doc_id)
    return {title: next(iter(docs)) for title, docs in sorted(ids.items()) if len(docs) == 1}


def extract_record(record: DocumentRecord, engine: str = "rules", title_index: dict[str, str] | None = None,
                   client=None) -> Extraction:
    """Extracts one document with the chosen engine and applies `finalize`. The Claude engine falls
    back to the rules engine (with a warning) whenever Claude is unavailable or fails."""
    if engine == "rules":
        raw = RulesExtractor().extract(record, title_index)
    elif engine == "claude":
        from .extract_llm import ClaudeExtractor
        from .llm import LLMError
        try:
            raw = ClaudeExtractor(client=client).extract(record, title_index)
        except LLMError as exc:
            raw = RulesExtractor().extract(record, title_index)
            raw.warnings.insert(0, f"claude extraction unavailable ({exc}); used rules engine")
    else:
        raise ValueError(f"unknown extraction engine {engine!r}; use one of {', '.join(ENGINES)}")
    return finalize(raw, record)


def _extract_many(records: list[DocumentRecord], engine: str, title_index: dict[str, str], max_workers: int,
                  client=None) -> list[Extraction]:
    if engine == "claude":
        if client is None:
            from .llm import LLMUnavailable, get_client
            try:
                client = get_client()       # one client (connection pool) for every document
            except LLMUnavailable:
                client = None               # each document then falls back to the rules engine
        if max_workers > 1 and len(records) > 1:
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                return list(pool.map(lambda r: extract_record(r, engine, title_index, client), records))
    return [extract_record(r, engine, title_index, client) for r in records]


def extract_all(records: list[DocumentRecord], engine: str = "rules", out_dir: Path = config.EXTRACTED_DIR,
                max_workers: int = 4, client=None) -> list[Extraction]:
    """Extracts every record (citations resolved across the whole set), writes out_dir/<DOC-ID>.json,
    removes stale DOC-*.json files of documents no longer in `records`, and returns the extractions
    sorted by doc id. An empty `records` list is a no-op (it never wipes earlier outputs)."""
    if engine not in ENGINES:
        raise ValueError(f"unknown extraction engine {engine!r}; use one of {', '.join(ENGINES)}")
    if not records:
        return []
    results = _extract_many(records, engine, build_title_index(records), max_workers, client)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    wanted = {r.doc_id for r in records}
    for path in out.glob("DOC-*.json", case_sensitive=True):     # never ingest's documents.json
        if path.stem not in wanted:
            path.unlink()
    for ex in results:
        ex.save(out / f"{ex.doc_id}.json")
    return sorted(results, key=lambda e: e.doc_id)


# ---------------------------------------------------------------------------- CLI
def _report(extractions: list[Extraction]) -> None:
    for ex in extractions:
        print(f"{ex.doc_id:<16} {ex.engine:<24} {len(ex.entities):3d} entities  "
              f"{len(ex.relationships):3d} relationships")
        for w in ex.warnings:
            print(f"    warning: {w}")
    n_warn = sum(len(ex.warnings) for ex in extractions)
    print(f"\n{len(extractions)} documents, {sum(len(ex.entities) for ex in extractions)} entities, "
          f"{sum(len(ex.relationships) for ex in extractions)} relationships, {n_warn} warnings")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m kgdemo.extraction",
                                     description="Extract entities and relationships from the ingested documents.")
    parser.add_argument("--engine", choices=ENGINES, default="rules")
    parser.add_argument("doc_ids", nargs="*", metavar="DOC-ID", help="only these documents (default: all)")
    args = parser.parse_args(argv)

    from .ingest import ingest_all
    records = ingest_all(config.UNSTRUCTURED_DIR)
    if not records:
        print(f"no documents found in {config.UNSTRUCTURED_DIR} - render the raw files first (python -m kgdemo.build)")
        return 1
    out_dir = Path(config.EXTRACTED_DIR)
    if not args.doc_ids:
        _report(extract_all(records, engine=args.engine, out_dir=out_dir))
        return 0
    by_id = {r.doc_id: r for r in records}
    unknown = [d for d in args.doc_ids if d not in by_id]
    if unknown:
        print(f"unknown document ids: {', '.join(unknown)}")
        return 2
    selected = [by_id[d] for d in dict.fromkeys(args.doc_ids)]
    # citations still resolve against the whole corpus; other documents' outputs are left alone
    extractions = _extract_many(selected, args.engine, build_title_index(records), max_workers=4)
    out_dir.mkdir(parents=True, exist_ok=True)
    for ex in extractions:
        ex.save(out_dir / f"{ex.doc_id}.json")
    _report(extractions)
    return 0


if __name__ == "__main__":
    sys.exit(main())
