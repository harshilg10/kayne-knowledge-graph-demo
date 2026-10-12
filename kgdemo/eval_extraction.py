"""Extraction recall against the document manifest - the ground truth the corpus was written from.

    python -m kgdemo.eval_extraction              # evaluates build/extracted/*.json
    python -m kgdemo.eval_extraction --strict     # exit code 1 when recall < 100%

Expected entities of a document: the catalog entities its body must mention (DocSpec.must_mention),
the people in its header (meeting participants, authors / preparers / CRM owner, sender, To and Cc),
the meeting that meeting notes record, a CRM note's client, a due-diligence borrower and a memo's
proposed decision. Entities found beyond these are counted as "extra": allowed and informational
(documents mention more than the required minimum). Cited documents are not counted as entities.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import world as w
from .catalog import Catalog, load_catalog
from .config import EXTRACTED_DIR
from .manifest import DocSpec, doc_specs
from .models import Extraction, entity_key


def expected_entities(spec: DocSpec, catalog: Catalog | None = None) -> tuple[set[str], list[str]]:
    """Entity keys the extraction of `spec` must contain, plus manifest problems (unknown names)."""
    cat = catalog or load_catalog()
    keys: set[str] = set()
    problems: list[str] = []
    for surface in spec.must_mention:
        entry = cat.lookup(surface)
        if entry is None:
            problems.append(f"{spec.doc_id}: must_mention '{surface}' is not a catalog form")
        else:
            keys.add(entry.key)
    people = list(spec.authors) + ([spec.sender] if spec.sender else []) + list(spec.to) + list(spec.cc)
    if spec.meeting_key:
        meeting = w.meeting_by_key(spec.meeting_key)
        people += meeting["participants"]
        keys.add(entity_key("Meeting", meeting["id"]))
    for name in people:
        entry = cat.person_by_name(name)
        if entry is None:
            problems.append(f"{spec.doc_id}: header person '{name}' is not in the catalog")
        else:
            keys.add(entry.key)
    if spec.client_id:
        keys.add(entity_key("Client", spec.client_id))
    if spec.borrower:
        entry = cat.lookup(spec.borrower)
        if entry is None:
            problems.append(f"{spec.doc_id}: borrower '{spec.borrower}' is not in the catalog")
        else:
            keys.add(entry.key)
    if spec.decision_ref:
        keys.add(entity_key("Decision", spec.decision_ref))
    return keys, problems


def evaluate(extractions: list[Extraction]) -> dict:
    """Per-document and overall recall of the expected entities, plus extra-entity counts."""
    specs = {s.doc_id: s for s in doc_specs()}
    cat = load_catalog()
    per_doc: dict[str, dict] = {}
    unknown: list[str] = []
    problems: list[str] = []
    for ex in sorted(extractions, key=lambda e: e.doc_id):
        spec = specs.get(ex.doc_id)
        if spec is None:
            unknown.append(ex.doc_id)
            continue
        expected, issues = expected_entities(spec, cat)
        problems += issues
        found = {e.key for e in ex.entities}
        missing = sorted(expected - found)
        extra = sorted(k for k in found - expected if not k.startswith("Document:"))
        per_doc[ex.doc_id] = {
            "engine": ex.engine, "expected": len(expected), "found": len(expected) - len(missing),
            "recall": (len(expected) - len(missing)) / len(expected) if expected else 1.0,
            "missing": missing, "extra": extra,
        }
    n_expected = sum(d["expected"] for d in per_doc.values())
    n_found = sum(d["found"] for d in per_doc.values())
    return {
        "documents": len(per_doc),
        "expected": n_expected,
        "found": n_found,
        "recall": n_found / n_expected if n_expected else 1.0,
        "extra": sum(len(d["extra"]) for d in per_doc.values()),
        "per_doc": per_doc,
        "not_extracted": sorted(set(specs) - {ex.doc_id for ex in extractions}),
        "unknown_documents": unknown,
        "manifest_problems": problems,
    }


def describe(key: str, catalog: Catalog | None = None) -> str:
    """'Company:CMP-NVDA (Nvidia)' - a key with its canonical name, for reports."""
    entry = (catalog or load_catalog()).by_key.get(key)
    return f"{key} ({entry.name})" if entry is not None and entry.name != entry.id else key


def format_report(report: dict) -> str:
    cat = load_catalog()
    lines = []
    for doc_id, d in report["per_doc"].items():
        if d["missing"]:
            missing = ", ".join(describe(k, cat) for k in d["missing"])
            lines.append(f"{doc_id:<14} recall {d['recall']:6.1%}  missing: {missing}")
    lines.append(f"{report['documents']} documents evaluated: recall {report['recall']:.1%} "
                 f"({report['found']}/{report['expected']} expected entities found), "
                 f"{report['extra']} extra entities (informational)")
    if report["not_extracted"]:
        lines.append(f"not extracted ({len(report['not_extracted'])}): {', '.join(report['not_extracted'])}")
    if report["unknown_documents"]:
        lines.append(f"not in the manifest (skipped): {', '.join(report['unknown_documents'])}")
    lines += [f"manifest problem: {p}" for p in report["manifest_problems"]]
    return "\n".join(lines)


def load_extractions(directory: Path = EXTRACTED_DIR) -> tuple[list[Extraction], list[str]]:
    """Every extraction JSON in `directory`, plus errors for unreadable files. Other JSON artifacts
    kept there (e.g. ingest's documents.json, a list of records) are skipped."""
    extractions, errors = [], []
    for path in sorted(Path(directory).glob("*.json")):
        try:
            data = json.loads(path.read_text())
            if isinstance(data, dict) and "doc_id" in data and "entities" in data:
                extractions.append(Extraction.from_dict(data))
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            errors.append(f"{path.name}: {exc}")
    return extractions, errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m kgdemo.eval_extraction",
                                     description="Extraction recall against the manifest ground truth.")
    parser.add_argument("--dir", type=Path, default=EXTRACTED_DIR, help="directory of <DOC-ID>.json extractions")
    parser.add_argument("--strict", action="store_true", help="exit with status 1 when recall is below 100%%")
    args = parser.parse_args(argv)
    extractions, errors = load_extractions(args.dir)
    for e in errors:
        print(f"unreadable extraction {e}")
    if not extractions:
        print(f"no extractions in {args.dir} - run python -m kgdemo.extraction first")
        return 1
    report = evaluate(extractions)
    print(format_report(report))
    return 1 if args.strict and report["recall"] < 1.0 else 0


if __name__ == "__main__":
    sys.exit(main())
