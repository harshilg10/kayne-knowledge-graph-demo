"""One-command pipeline: structured exports -> raw documents -> ingestion -> extraction -> Neo4j -> embeddings.

    python -m kgdemo.build                    # offline rules engine
    python -m kgdemo.build --engine claude    # extract with Claude (needs ANTHROPIC_API_KEY)
    python -m kgdemo.build --skip-render      # reuse the raw files in data/unstructured
    python -m kgdemo.build --skip-embed       # no chunks / vector index (standard RAG unavailable)

The graph is reset only after extraction has finished, so a failed extraction never leaves an empty
graph behind. A summary of the run is written to build/build_summary.json.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from . import config
from . import neo4j_client as db

SUMMARY_PATH = config.BUILD_DIR / "build_summary.json"
TOTAL_STEPS = 7
WARNINGS_SHOWN = 15


class _Step:
    """Prints '[n/7] title', indented detail lines and the elapsed time; records the timing."""

    def __init__(self, number: int, title: str, timings: dict[str, float]):
        self.number, self.title, self.timings = number, title, timings
        self.t0 = 0.0

    def __enter__(self) -> "_Step":
        print(f"\n[{self.number}/{TOTAL_STEPS}] {self.title}", flush=True)
        self.t0 = time.perf_counter()
        return self

    def info(self, text: str) -> None:
        print(f"      {text}", flush=True)

    def __exit__(self, exc_type, exc, tb) -> bool:
        elapsed = time.perf_counter() - self.t0
        self.timings[self.title] = round(elapsed, 2)
        if exc_type is None:
            print(f"      done in {elapsed:.1f}s", flush=True)
        else:
            print(f"      FAILED after {elapsed:.1f}s", flush=True)
        return False


def _skipped(number: int, title: str, reason: str) -> None:
    print(f"\n[{number}/{TOTAL_STEPS}] {title}: skipped ({reason})", flush=True)


def _rel(path: Path) -> str:
    try:
        return str(Path(path).relative_to(config.ROOT))
    except ValueError:
        return str(path)


def _fmt(counts: dict[str, Any]) -> str:
    return ", ".join(f"{k} {v:,}" if isinstance(v, int) else f"{k} {v}" for k, v in counts.items()) or "-"


def _by_size(counts: dict[str, int]) -> dict[str, int]:
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def build(engine: str = "rules", skip_render: bool = False, skip_embed: bool = False) -> dict:
    """Runs the pipeline; returns the summary that is also written to build/build_summary.json."""
    from . import generate_structured, graph_load
    from .ontology import load_ontology

    started, t_start = datetime.now(), time.perf_counter()
    timings: dict[str, float] = {}
    counts: dict[str, Any] = {}
    warnings: list[str] = []
    server = db.ping()
    print(f"Knowledge graph build | engine: {engine} | Neo4j {server['version']} {server['edition']} at "
          f"{config.NEO4J_URI}", flush=True)

    with _Step(1, "Structured exports", timings) as step:
        rows = generate_structured.generate()
        counts["structured_rows"] = rows
        step.info(f"{len(rows)} CSV files, {sum(rows.values()):,} rows -> {_rel(config.STRUCTURED_DIR)}")

    if skip_render:
        _skipped(2, "Render raw documents", f"--skip-render: reusing {_rel(config.UNSTRUCTURED_DIR)}")
    else:
        with _Step(2, "Render raw documents", timings) as step:
            from .render_docs import render_all
            rendered = render_all()
            counts["rendered"] = rendered
            step.info(f"{sum(rendered.values()):,} documents ({_fmt(rendered)}) -> {_rel(config.UNSTRUCTURED_DIR)}")

    with _Step(3, "Ingest raw documents", timings) as step:
        from .ingest import ingest_all
        records = ingest_all()
        if not records:
            raise RuntimeError(f"no documents found in {_rel(config.UNSTRUCTURED_DIR)}; run the build without --skip-render")
        by_type = Counter(r.doc_type for r in records)
        counts["documents"] = len(records)
        counts["documents_by_type"] = dict(by_type.most_common())
        step.info(f"{len(records)} documents: {_fmt(counts['documents_by_type'])}")

    with _Step(4, f"Extract entities & relationships ({engine})", timings) as step:
        from .extraction import extract_all
        extractions = extract_all(records, engine=engine)
        engines = Counter(ex.engine for ex in extractions)
        counts["extracted_entities"] = sum(len(ex.entities) for ex in extractions)
        counts["extracted_relationships"] = sum(len(ex.relationships) for ex in extractions)
        warnings += [f"extract {ex.doc_id}: {w}" for ex in extractions for w in ex.warnings]
        missing = sorted({r.doc_id for r in records} - {ex.doc_id for ex in extractions})
        if missing:
            warnings.append(f"extract: no extraction for {', '.join(missing)}")
        step.info(f"{len(extractions)} documents, {counts['extracted_entities']:,} entities, "
                  f"{counts['extracted_relationships']:,} relationships -> {_rel(config.EXTRACTED_DIR)}")
        step.info(f"engines: {_fmt(dict(engines))}")

    with _Step(5, "Load Neo4j", timings) as step:
        onto = load_ontology()
        step.info(f"reset        {graph_load.reset_graph():,} nodes deleted")
        schema = graph_load.create_schema(onto)
        step.info(f"schema       {len(schema['constraints'])} constraints, {len(schema['range_indexes'])} range "
                  f"indexes, {len(schema['fulltext_indexes'])} full-text indexes")
        vocabulary = graph_load.load_vocabulary(onto)
        step.info(f"vocabulary   {_fmt(vocabulary)}")
        structured = graph_load.load_structured(config.STRUCTURED_DIR, onto)
        step.info(f"structured   {_fmt(structured)}")
        documents = graph_load.load_documents(records, {ex.doc_id: ex.engine for ex in extractions})
        step.info(f"documents    {documents:,}")
        loaded = graph_load.load_extractions(extractions, onto)
        warnings += [f"load: {w}" for w in loaded["warnings"]]
        step.info(f"extractions  {_fmt(loaded['nodes'])}; relationships {_fmt(loaded['relationships'])}; "
                  f"skipped {loaded['skipped']}")
        rules = graph_load.apply_rules(onto)
        warnings += [f"rules: {w}" for w in rules["warnings"]]
        step.info(f"rules        {_fmt(rules['rules'])}")
        counts["loaded"] = {"vocabulary": vocabulary, "structured": structured, "documents": documents,
                            "extractions": {k: v for k, v in loaded.items() if k != "warnings"},
                            "rules": rules["rules"]}

    if skip_embed:
        _skipped(6, "Embed chunks", "--skip-embed: no vector index, standard RAG is unavailable")
        counts["chunks"] = None
    else:
        with _Step(6, "Embed chunks", timings) as step:
            from .embed import VECTOR_INDEX, build_chunks
            counts["chunks"] = build_chunks()
            step.info(f"{counts['chunks']:,} chunks embedded with {config.EMBED_MODEL} ({config.EMBED_DIM}-d), "
                      f"vector index '{VECTOR_INDEX}'")

    with _Step(7, "Summary", timings) as step:
        stats = graph_load.graph_stats()
        step.info(f"nodes ({sum(stats['nodes'].values()):,}): {_fmt(_by_size(stats['nodes']))}")
        step.info(f"relationships ({sum(stats['relationships'].values()):,}): "
                  f"{_fmt(_by_size(stats['relationships']))}")
        from .export_queries import OUT as QUERY_PACK, export
        export()
        step.info(f"query pack   {_rel(QUERY_PACK)}")
        if skip_embed:
            warnings.append("demo script not refreshed: it quotes standard-RAG numbers, which need embeddings")
        else:
            try:
                from .demo_numbers import OUT as SCRIPT, render
                render()
                step.info(f"talk track   {_rel(SCRIPT)} (numbers computed from this graph)")
            except Exception as exc:  # the graph is usable even if the script cannot be refreshed
                warnings.append(f"demo script not refreshed: {exc}")

    summary = {
        "built_at": started.isoformat(timespec="seconds"),
        "duration_s": round(time.perf_counter() - t_start, 1),
        "engine": engine,
        "extraction_engines": dict(engines),
        "options": {"skip_render": skip_render, "skip_embed": skip_embed},
        "as_of": config.AS_OF_DATE.isoformat(),
        "neo4j": {"uri": config.NEO4J_URI, "database": config.NEO4J_DATABASE, "version": server["version"],
                  "edition": server["edition"]},
        "timings_s": timings,
        "counts": counts,
        "stats": stats,
        "warnings_count": len(warnings),
        "warnings": warnings,
    }
    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")

    if warnings:
        print(f"\nWarnings ({len(warnings)}):")
        for w in warnings[:WARNINGS_SHOWN]:
            print(f"  - {w}")
        if len(warnings) > WARNINGS_SHOWN:
            print(f"  ... {len(warnings) - WARNINGS_SHOWN} more in {_rel(SUMMARY_PATH)}")
    print(f"\nBuild finished in {summary['duration_s']:.1f}s with {len(warnings)} warnings; "
          f"summary in {_rel(SUMMARY_PATH)}.", flush=True)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m kgdemo.build",
                                     description="Build the knowledge graph demo end to end (resets Neo4j).")
    parser.add_argument("--engine", choices=("rules", "claude"), default="rules",
                        help="extraction engine (default: the offline rules engine)")
    parser.add_argument("--skip-render", action="store_true", help="reuse the raw files in data/unstructured")
    parser.add_argument("--skip-embed", action="store_true", help="skip chunk embeddings and the vector index")
    args = parser.parse_args(argv)

    if args.engine == "claude" and not config.llm_available():
        print("--engine claude needs Claude credentials: set ANTHROPIC_API_KEY in .env (and unset KG_LLM_DISABLED).",
              file=sys.stderr)
        return 2
    try:
        db.ping()
    except Exception as exc:  # noqa: BLE001 - any connection problem gets the same advice
        print(f"Neo4j is not reachable at {config.NEO4J_URI} ({exc}).\n"
              "Start it with scripts/neo4j_start.sh and check NEO4J_PASSWORD in .env.", file=sys.stderr)
        return 1
    build(engine=args.engine, skip_render=args.skip_render, skip_embed=args.skip_embed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
