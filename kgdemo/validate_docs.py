"""Validates authored document bodies (authoring/document_bodies/<DOC-ID>.txt) against the manifest.

    python -m kgdemo.validate_docs                 # every body on disk
    python -m kgdemo.validate_docs DOC-RR-01 ...   # specific documents

Errors must be fixed. Warnings must be reviewed (they flag possible invented names
or dates after the document date).
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from datetime import date

from .catalog import load_catalog, normalize_text
from .config import SOURCE_DOCS_DIR
from .manifest import DocSpec, doc_specs
from . import world as w

HEADER_PREFIXES = ("Date:", "Participants:", "From:", "To:", "Cc:", "CC:", "Subject:", "Authors:", "Author:",
                   "Prepared by:", "Borrower:", "Meeting Type:", "Decision Reference:", "Published:", "For Meeting:")
DECISION_RE = re.compile(r"\bIC-\d{4}-\d{3}\b")
ISO_DATE_RE = re.compile(r"\b(20\d\d)-(\d\d)-(\d\d)\b")
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]
LONG_DATE_RE = re.compile(r"\b(" + "|".join(MONTHS) + r")\s+(\d{1,2}),\s+(20\d\d)\b")
CAP_SEQ_RE = re.compile(r"\b([A-Z][A-Za-z0-9&'-]*(?:[ \t]+(?:of|and|the|&|for|de)?[ \t]*[A-Z][A-Za-z0-9&'-]*)+)")
STOP_STARTS = {"The", "At", "On", "In", "My", "Our", "This", "That", "These", "Those", "A", "An", "For", "From", "By",
               "With", "As", "Per", "Since", "After", "Before", "During", "We", "I", "He", "She", "They", "It", "If",
               "When", "While", "Both", "All", "Each", "Trades", "Trading", "Following", "Next", "Last", "And", "But"}
# capitalized phrases that are fine without being catalog entities
ALLOWED_PHRASES = {
    "Arbor Peak", "Arbor Peak Wealth Partners", "West Texas", "Mid-Atlantic", "Permian Basin", "United States",
    "Investment Committee Meeting", "Risk Committee", "Growth", "Balanced", "Action Items", "Key Points",
    "Portfolio Implications", "Risks and Mitigants", "Transaction Overview", "Business Overview", "Key Findings",
    "Investment Thesis", "Supporting Documents", "Q1", "Q2", "Q3", "Q4", "Chief Risk Officer",
    "Chief Investment Officer", "Head of Technology Research", "Head of Wealth Management", "Head of Private Credit",
    "Head of Trading", "Portfolio Manager", "Wealth Advisor", "Senior Wealth Advisor", "Client Service Associate",
    "Growth and Balanced", "Growth and Balanced Models", "Supporting Documents", "Investment Committee Memorandum",
}


@dataclass
class Report:
    doc_id: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def body_path(doc_id: str):
    return SOURCE_DOCS_DIR / f"{doc_id}.txt"


def load_body(spec: DocSpec) -> str | None:
    if spec.fixed_body is not None:
        return spec.fixed_body
    p = body_path(spec.doc_id)
    return p.read_text() if p.exists() else None


def validate_spec(spec: DocSpec, body: str) -> Report:
    rep = Report(spec.doc_id)
    cat = load_catalog()
    if not body.strip():
        rep.errors.append("body is empty")
        return rep
    non_ascii = sorted({ch for ch in body if ord(ch) > 127})
    if non_ascii:
        rep.errors.append(f"non-ASCII characters {non_ascii!r}: use plain ASCII (straight quotes, '-' for dashes)")
    text = normalize_text(body)

    n_words = len(re.findall(r"\S+", text))
    lo, hi = spec.words
    if spec.fixed_body is None and not (lo * 0.85 <= n_words <= hi * 1.15):
        rep.errors.append(f"{n_words} words; target {lo}-{hi}")

    first = text.strip().splitlines()[0].strip().lstrip("#").strip()
    if first.lower() == spec.title.lower():
        rep.errors.append("body repeats the title - the title is rendered automatically")
    for line in text.splitlines():
        if line.strip().startswith(HEADER_PREFIXES):
            rep.errors.append(f"header-style line in body (headers are rendered automatically): {line.strip()[:60]!r}")

    matches = cat.find(text)
    found = {m.entry.key for m in matches}
    for surface in spec.must_mention:
        entry = cat.lookup(surface)
        if entry is None:
            rep.errors.append(f"manifest problem: must_mention {surface!r} is not a catalog form")
            continue
        if entry.key not in found:
            forms = " / ".join(entry.forms[:4])
            rep.errors.append(f"missing required mention of {entry.label} '{entry.name}' (use: {forms})")

    for phrase in spec.avoid_phrases:
        if re.search(rf"(?<![A-Za-z0-9]){re.escape(phrase)}(?![A-Za-z0-9])", text, re.IGNORECASE):
            rep.errors.append(f"uses forbidden phrase {phrase!r} - describe the topic with specific terms instead")

    known = {d["id"]: d for d in w.DECISIONS}
    for did in sorted(set(DECISION_RE.findall(text))):
        if did not in known:
            rep.errors.append(f"unknown decision id {did}")
        elif known[did]["date"] > spec.date and did != spec.decision_ref:
            rep.errors.append(f"{did} is decided on {known[did]['date']}, after this document's date {spec.date}")

    doc_day = date.fromisoformat(spec.date)
    for y, mth, d in ISO_DATE_RE.findall(text):
        try:
            when = date(int(y), int(mth), int(d))
        except ValueError:
            rep.errors.append(f"invalid date {y}-{mth}-{d}")
            continue
        if when > doc_day:
            rep.warnings.append(f"date {when} is after the document date - fine only if it is a scheduled event")
    for mon, d, y in LONG_DATE_RE.findall(text):
        when = date(int(y), MONTHS.index(mon) + 1, int(d))
        if when > doc_day:
            rep.warnings.append(f"date {mon} {d}, {y} is after the document date - fine only if it is a scheduled event")

    spans = [(m.start, m.end) for m in matches]
    unknown = set()
    for m in CAP_SEQ_RE.finditer(text):
        words = m.group(1).strip(" ,-").split()
        while words and (words[0] in STOP_STARTS or words[0] in MONTHS):
            words = words[1:]
        while words and (words[-1] in MONTHS or re.fullmatch(r"Q[1-4]", words[-1])):
            words = words[:-1]
        phrase = " ".join(words)
        if len(words) < 2 or phrase in ALLOWED_PHRASES:
            continue
        if any(m.start() < e and s < m.end() for s, e in spans):
            continue
        unknown.add(phrase)
    for phrase in sorted(unknown):
        rep.warnings.append(f"capitalized phrase not in catalog: {phrase!r} - OK if generic (place, section label, "
                            f"product, title); otherwise it may be an invented entity")
    return rep


def validate(doc_ids: list[str] | None = None) -> list[Report]:
    specs = doc_specs()
    if doc_ids:
        wanted = set(doc_ids)
        unknown_ids = wanted - {s.doc_id for s in specs}
        if unknown_ids:
            raise SystemExit(f"unknown doc ids: {sorted(unknown_ids)}")
        specs = [s for s in specs if s.doc_id in wanted]
    reports = []
    for spec in specs:
        body = load_body(spec)
        if body is None:
            if doc_ids:
                reports.append(Report(spec.doc_id, errors=[f"missing body file {body_path(spec.doc_id)}"]))
            continue
        reports.append(validate_spec(spec, body))
    return reports


def main(argv: list[str]) -> int:
    reports = validate(argv or None)
    n_err = 0
    for r in reports:
        status = "OK " if r.ok else "ERR"
        print(f"[{status}] {r.doc_id}")
        for e in r.errors:
            print(f"    error:   {e}")
        for wmsg in r.warnings:
            print(f"    warning: {wmsg}")
        n_err += len(r.errors)
    print(f"\n{len(reports)} documents checked, {sum(not r.ok for r in reports)} with errors, "
          f"{sum(len(r.warnings) for r in reports)} warnings")
    return 1 if n_err else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
