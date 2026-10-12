"""Offline extraction engine: semantic model + entity catalog + document structure.

Facts come from two places, and both are expressed in the semantic model:
  * header facts - the document's structured fields (meeting title and participants, authors,
    sender and recipients, CRM owner and client, due-diligence borrower, memo decision and
    citations), resolved to canonical ids through the catalog. The Claude engine reuses
    `add_header_facts` so both engines agree on document structure.
  * text facts - catalog matches in the body (names, aliases, tickers, theme and concept phrases,
    decision ids) -> MENTIONS, DISCUSSED, REFERENCES and DECIDED.

`RulesExtractor.extract` returns a raw Extraction; `kgdemo.extraction.finalize` then applies the
shared semantic mapping (concept -> theme) and the ontology's domain/range validation.
"""
from __future__ import annotations

import csv
import re
from email.utils import parseaddr
from functools import lru_cache
from typing import NamedTuple

from .catalog import Catalog, CatalogEntry, load_catalog, normalize_text
from .config import STRUCTURED_DIR
from .models import DocumentRecord, EntityRef, Extraction, RelationshipRef, doc_key, entity_key, meeting_id
from .ontology import Committee, Ontology, load_ontology

ENGINE = "rules"
EVIDENCE_MAX = 300
ORIGIN_RANK = {"inferred": 0, "text": 1, "header": 2}     # a header fact is the strongest identification
_AUTHOR_FIELD = {"IC Memo": "From", "Research Report": "Authors", "Due Diligence": "Prepared by", "CRM Note": "Owner"}
_ABBREVIATIONS = {"dr", "mr", "mrs", "ms", "st", "inc", "co", "corp", "ltd", "no", "vs", "jr", "sr", "approx"}
_BULLET = re.compile(r"(?:[-*\u2022]|\d{1,2}[.)])\s+")
_SENTENCE_END = re.compile(r"[.!?][\"')\]]*\s+")
_INITIALS = re.compile(r"(?:[a-z]\.)*[a-z]")


# ---------------------------------------------------------------------------- small helpers
def slug(name: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "-", name.upper()).strip("-")


def new_entity_id(label: str, name: str) -> str:
    """Id of an entity that is not in the catalog, e.g. NEW-PERSON-JANE-DOE."""
    return f"NEW-{label.upper()}-{slug(name)}"


def normalize_title(title: str) -> str:
    """Comparison form of a document title: typography-normalized, lowercase, single spaces."""
    return " ".join(normalize_text(title).split()).lower()


def clip(text: str, limit: int = EVIDENCE_MAX) -> str:
    """Whitespace-collapsed text of at most `limit` characters."""
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[:limit - 3].rstrip() + "..."


@lru_cache(maxsize=1)
def decision_log() -> dict[str, dict]:
    """The IC decision log (data/structured/ic_decisions.csv) keyed by decision id."""
    path = STRUCTURED_DIR / "ic_decisions.csv"
    if not path.exists():
        load_catalog()                      # generates the structured exports on first use
    with path.open(newline="") as fh:
        return {row["id"]: row for row in csv.DictReader(fh)}


def phrase_pattern(phrase: str) -> re.Pattern | None:
    """Case-insensitive, whitespace-flexible, word-bounded pattern for a literal phrase."""
    words = str(phrase or "").split()
    if not words:
        return None
    return re.compile(r"(?<![A-Za-z0-9_])" + r"\s+".join(map(re.escape, words)) + r"(?![A-Za-z0-9_])",
                      re.IGNORECASE)


def find_phrase(text: str, phrase: str, lo: int = 0, hi: int | None = None) -> tuple[int, int] | None:
    pattern = phrase_pattern(phrase)
    match = pattern.search(text, lo, len(text) if hi is None else hi) if pattern else None
    return match.span() if match else None


def phrase_spans(text: str, phrase: str, lo: int = 0, hi: int | None = None) -> list[list[int]]:
    pattern = phrase_pattern(phrase)
    if pattern is None:
        return []
    return [list(m.span()) for m in pattern.finditer(text, lo, len(text) if hi is None else hi)]


# ---------------------------------------------------------------------------- evidence
def evidence_at(text: str, start: int, end: int, limit: int = EVIDENCE_MAX) -> str:
    """The line containing text[start:end] - or its sentence when the line is longer than `limit` -
    without a bullet marker, trimmed to at most `limit` characters around the mention."""
    ls = text.rfind("\n", 0, start) + 1
    le = text.find("\n", end)
    le = len(text) if le < 0 else le
    if le - ls > limit:
        ls, le = _sentence_bounds(text, ls, le, start, end)
    return _clip_around(text, ls, le, start, end, limit)


def _sentence_bounds(text: str, ls: int, le: int, start: int, end: int) -> tuple[int, int]:
    starts = [ls]
    for m in _SENTENCE_END.finditer(text, ls, le):
        if text[m.start()] == "." and _is_abbreviation(text, ls, m.start()):
            continue
        starts.append(m.end())
    first = max(s for s in starts if s <= start)
    last = next((s for s in starts if s >= end), le)
    return first, last


def _is_abbreviation(text: str, ls: int, dot: int) -> bool:
    j = dot
    while j > ls and not text[j - 1].isspace():
        j -= 1
    token = text[j:dot].lower().lstrip("(\"'")
    return token in _ABBREVIATIONS or bool(_INITIALS.fullmatch(token))


def _clip_around(text: str, s0: int, e0: int, start: int, end: int, limit: int) -> str:
    while s0 < e0 and text[s0].isspace():
        s0 += 1
    bullet = _BULLET.match(text, s0, e0)
    if bullet and bullet.end() <= start:
        s0 = bullet.end()
    while e0 > s0 and text[e0 - 1].isspace():
        e0 -= 1
    if e0 - s0 <= limit:
        return text[s0:e0]
    ms, me = max(start, s0), min(end, e0)
    budget = limit - 6                      # room for a leading and a trailing "..."
    if me - ms >= budget:
        return text[ms:ms + limit]
    left = max(s0, ms - (budget - (me - ms)) // 2)
    right = min(e0, left + budget)
    left = max(s0, right - budget)
    if left > s0:                           # cut at word boundaries
        space = text.find(" ", left, ms)
        left = space + 1 if space != -1 else left
    if right < e0:
        space = text.rfind(" ", me, right)
        right = space if space != -1 else right
    return ("..." if left > s0 else "") + text[left:right].strip() + ("..." if right < e0 else "")


def header_evidence(text: str, region_end: int, needles: list[str], fallback: str) -> str:
    """Evidence for a header fact: the first line within text[:region_end] naming one of `needles`,
    prefixed with its list label when it is a list item (e.g. "Participants: Douglas Whitfield");
    `fallback` when no needle occurs."""
    for needle in needles:
        span = find_phrase(text, needle, 0, region_end)
        if span:
            return _labelled_line(text, *span)
    return clip(fallback)


def _labelled_line(text: str, start: int, end: int) -> str:
    ls = text.rfind("\n", 0, start) + 1
    le = text.find("\n", end)
    line = text[ls:len(text) if le < 0 else le].strip()
    label = ""
    if ":" not in line:                     # a list item: find the "Label:" line that opens the list
        j = ls - 1
        while j > 0:
            ps = text.rfind("\n", 0, j) + 1
            prev = text[ps:j].strip()
            if prev.endswith(":"):
                label = prev
                break
            if not prev or ":" in prev:
                break
            j = ps - 1
    if label and len(label) + 1 + len(line) <= EVIDENCE_MAX:
        return f"{label} {line}"
    return evidence_at(text, start, end)


# ---------------------------------------------------------------------------- builder
class GraphBuilder:
    """Accumulates one document's entities (one EntityRef per key) and relationships."""

    def __init__(self, record: DocumentRecord, catalog: Catalog):
        self.record = record
        self.catalog = catalog
        self.doc = doc_key(record.doc_id)
        self.matches = catalog.find(record.text)
        self.entities: dict[str, EntityRef] = {}
        self.relationships: list[RelationshipRef] = []
        self.warnings: list[str] = []

    @property
    def body_matches(self):
        return [m for m in self.matches if m.start >= self.record.body_offset]

    def entity(self, label: str, entity_id: str, name: str, origin: str, *, resolved: bool = True,
               mentions=(), spans=(), properties: dict | None = None) -> str:
        key = entity_key(label, entity_id)
        e = self.entities.get(key)
        if e is None:
            e = self.entities[key] = EntityRef(key=key, label=label, id=entity_id, name=name, origin=origin,
                                               resolved=resolved)
        elif ORIGIN_RANK.get(origin, 0) > ORIGIN_RANK.get(e.origin, 0):
            e.origin = origin
        for m in mentions:
            if m and m not in e.mentions:
                e.mentions.append(m)
        for s in spans:
            if list(s) not in e.spans:
                e.spans.append(list(s))
        if properties:
            e.properties.update(properties)
        return key

    def catalog_entity(self, entry: CatalogEntry, origin: str) -> str:
        """Adds a catalog entity with every catalog match of it in the text as a mention and span."""
        hits = [m for m in self.matches if m.entry.key == entry.key]
        return self.entity(entry.label, entry.id, entry.name, origin,
                           mentions=[m.surface for m in hits], spans=[[m.start, m.end] for m in hits])

    def rel(self, source: str, rel_type: str, target: str, evidence: str, method: str,
            properties: dict | None = None) -> None:
        self.relationships.append(RelationshipRef(source=source, type=rel_type, target=target,
                                                  evidence=clip(evidence), method=method,
                                                  properties=dict(properties or {})))

    def warn(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)

    def merge(self, other: "GraphBuilder") -> None:
        """Adds `other`'s entities and every relationship (source, type, target) not present yet."""
        for e in other.entities.values():
            self.entity(e.label, e.id, e.name, e.origin, resolved=e.resolved, mentions=e.mentions, spans=e.spans,
                        properties=e.properties)
        have = {(r.source, r.type, r.target) for r in self.relationships}
        for r in other.relationships:
            if (r.source, r.type, r.target) not in have:
                have.add((r.source, r.type, r.target))
                self.relationships.append(r)
        for w in other.warnings:
            self.warn(w)

    def extraction(self, engine: str) -> Extraction:
        for e in self.entities.values():
            e.spans.sort()
        r = self.record
        document = {"id": r.doc_id, "title": r.title, "doc_type": r.doc_type, "date": r.date,
                    "source_system": r.source_system, "source_path": r.source_path}
        return Extraction(doc_id=r.doc_id, engine=engine, document=document, entities=list(self.entities.values()),
                          relationships=list(self.relationships), warnings=list(self.warnings))


# ---------------------------------------------------------------------------- header facts
class HeaderPerson(NamedTuple):
    key: str
    evidence: str


def resolve_person(catalog: Catalog, name: str = "", email: str = "") -> CatalogEntry | None:
    """Catalog person for a header name, by e-mail address first, then by name or alias."""
    if email:
        entry = catalog.emails.get(email.strip().lower())
        if entry is not None:
            return entry
    for candidate in (name, name.split("(", 1)[0]):     # "Name (Organization)" -> "Name"
        if candidate.strip():
            entry = catalog.person_by_name(candidate)
            if entry is not None:
                return entry
    return None


def meeting_committees(onto: Ontology, title: str, meeting_type: str) -> list[Committee]:
    """Committees holding a meeting: its type is one of a committee's meeting types, or its title
    contains the committee's name."""
    mtype = (meeting_type or "").strip().lower()
    return [c for c in onto.committees.values()
            if mtype in {t.lower() for t in c.meeting_types} or find_phrase(title, c.name)]


def infer_meeting_type(onto: Ontology, title: str) -> str:
    for c in onto.committees.values():
        if c.meeting_types and find_phrase(title, c.name):
            return c.meeting_types[0]
    return ""


def add_header_facts(b: GraphBuilder, onto: Ontology, title_index: dict[str, str] | None = None,
                     meeting: tuple[str, str, str] | None = None) -> str | None:
    """Adds the document-structure facts. `meeting` = (title, date, meeting_type) overrides the
    record's header for meeting notes. Returns the meeting key for meeting notes."""
    record, md = b.record, b.record.metadata or {}
    meeting_key = None
    if record.doc_type == "Meeting Notes":
        title, date, mtype = meeting or (record.title, record.date, md.get("meeting_type") or "")
        meeting_key = _add_meeting(b, onto, title, date, mtype)
        for p in md.get("participants") or []:
            name = p.get("name", "") if isinstance(p, dict) else str(p)
            person = _header_person(b, name, "", "Participants")
            if person and meeting_key:
                b.rel(person.key, "ATTENDED", meeting_key, person.evidence, "header")
    _add_authors(b, md)
    _add_email_people(b, md)
    if record.doc_type == "CRM Note" or md.get("client_id") or md.get("client_name"):
        _add_crm_client(b, md)
    if md.get("borrower"):
        _add_borrower(b, md["borrower"])
    if md.get("decision_ref"):
        _add_decision_ref(b, md["decision_ref"])
    if md.get("cited_titles"):
        _add_citations(b, md["cited_titles"], title_index)
    return meeting_key


def _header_person(b: GraphBuilder, name: str, email: str, field: str) -> HeaderPerson | None:
    name, email = (name or "").strip(), (email or "").strip()
    if "<" in name and "@" in name and not email:       # "Name <address>" in a single field
        parsed_name, email = parseaddr(name)
        name = parsed_name or name
    text, head_end = b.record.text, b.record.body_offset
    entry = resolve_person(b.catalog, name, email)
    display = re.sub(r"\s*\([^)]*\)\s*$", "", name).strip() or email     # drop a trailing "(Organization)"
    if not display:
        return None
    evidence = header_evidence(text, head_end, [n for n in (name, email, entry.name if entry else "") if n],
                               f"{field}: {display}")
    if entry is not None:
        return HeaderPerson(b.catalog_entity(entry, "header"), evidence)
    if not slug(display):
        b.warn(f"{field} entry '{display}' cannot be identified")
        return None
    key = b.entity("Person", new_entity_id("Person", display), display, "header", resolved=False,
                   mentions=[display], spans=phrase_spans(text, display, 0, head_end))
    b.warn(f"{field} '{display}' is not in the catalog; proposed as unresolved {key}")
    return HeaderPerson(key, evidence)


def _add_meeting(b: GraphBuilder, onto: Ontology, title: str, date: str, meeting_type: str) -> str | None:
    if not (title and date):
        b.warn("meeting notes without a title or date: no Meeting entity")
        return None
    text, head_end = b.record.text, b.record.body_offset
    meeting_type = meeting_type or infer_meeting_type(onto, title)
    title_span = find_phrase(text, title, 0, head_end)
    key = b.entity("Meeting", meeting_id(date, title), title, "header",
                   mentions=[text[slice(*title_span)]] if title_span else [],
                   spans=[list(title_span)] if title_span else [],
                   properties={"date": date, "meeting_type": meeting_type})
    title_evidence = header_evidence(text, head_end, [title], title)
    b.rel(b.doc, "RECORDS", key, title_evidence, "header")
    for committee in meeting_committees(onto, title, meeting_type):
        entry = b.catalog.by_key.get(entity_key("Committee", committee.id))
        ckey = (b.catalog_entity(entry, "header") if entry is not None
                else b.entity("Committee", committee.id, committee.name, "header"))
        evidence = header_evidence(text, head_end, [committee.name, meeting_type], title)
        b.rel(key, "HELD_BY", ckey, evidence, "header")
    for m in b.catalog.find(title):
        if m.entry.label == "Client":
            b.rel(key, "FOR_CLIENT", b.catalog_entity(m.entry, "header"), title_evidence, "header")
    return key


def _add_authors(b: GraphBuilder, md: dict) -> None:
    names = [str(a) for a in md.get("authors") or []]
    if md.get("owner") and md["owner"] not in names:
        names.append(str(md["owner"]))
    field = _AUTHOR_FIELD.get(b.record.doc_type, "Author")
    for name in names:
        person = _header_person(b, name, "", field)
        if person:
            b.rel(person.key, "AUTHORED", b.doc, person.evidence, "header")


def _add_email_people(b: GraphBuilder, md: dict) -> None:
    if md.get("sender") or md.get("sender_email"):
        person = _header_person(b, md.get("sender") or "", md.get("sender_email") or "", "From")
        if person:
            b.rel(person.key, "SENT", b.doc, person.evidence, "header")
    for field, names_key, emails_key in (("To", "to", "to_emails"), ("Cc", "cc", "cc_emails")):
        for name, email in pair_addresses(md.get(names_key) or [], md.get(emails_key) or []):
            person = _header_person(b, name, email, field)
            if person:
                b.rel(b.doc, "SENT_TO", person.key, person.evidence, "header")


def pair_addresses(names: list, emails: list) -> list[tuple[str, str]]:
    """Display names with their addresses (lists from one header are aligned when equally long)."""
    names, emails = [str(n) for n in names], [str(e) for e in emails]
    if len(names) == len(emails):
        return list(zip(names, emails))
    return [(n, "") for n in names] if names else [("", e) for e in emails]


def _add_crm_client(b: GraphBuilder, md: dict) -> None:
    cid, cname = str(md.get("client_id") or ""), str(md.get("client_name") or "")
    if not (cid or cname):
        b.warn("CRM note without a client field: no ABOUT relationship")
        return
    entry = b.catalog.by_id.get(cid) if cid else None
    if entry is None or entry.label != "Client":
        entry = b.catalog.lookup(cname) if cname else None
    if entry is None or entry.label != "Client":
        b.warn(f"CRM client '{cname or cid}' is not in the catalog: no ABOUT relationship")
        return
    evidence = header_evidence(b.record.text, b.record.body_offset, [n for n in (cname, entry.name, cid) if n],
                               f"Client: {cname or entry.name}")
    b.rel(b.doc, "ABOUT", b.catalog_entity(entry, "header"), evidence, "header")


def _add_borrower(b: GraphBuilder, borrower: str) -> None:
    text, head_end = b.record.text, b.record.body_offset
    entry = b.catalog.lookup(borrower)
    if entry is not None and entry.label == "Company":
        key = b.catalog_entity(entry, "header")
    else:
        key = b.entity("Company", new_entity_id("Company", borrower), borrower, "header", resolved=False,
                       mentions=[borrower], spans=phrase_spans(text, borrower))
        b.warn(f"borrower '{borrower}' is not in the catalog; proposed as unresolved {key}")
    b.rel(b.doc, "ABOUT", key, header_evidence(text, head_end, [borrower], f"Borrower: {borrower}"), "header")


def _add_decision_ref(b: GraphBuilder, decision_ref: str) -> None:
    entry = b.catalog.by_id.get(decision_ref)
    if entry is None or entry.label != "Decision":
        b.warn(f"decision reference {decision_ref} is not in the IC decision log: no PROPOSES relationship")
        return
    evidence = header_evidence(b.record.text, b.record.body_offset, [decision_ref],
                               f"Decision Reference: {decision_ref}")
    b.rel(b.doc, "PROPOSES", b.catalog_entity(entry, "header"), evidence, "header")


def _add_citations(b: GraphBuilder, titles: list, title_index: dict[str, str] | None) -> None:
    if title_index is None:
        b.warn("cited documents not resolved: no title index (extract the document with its corpus)")
        return
    text = b.record.text
    for title in map(str, titles):
        cited = title_index.get(normalize_title(title))
        if cited is None:
            b.warn(f"unresolved citation: no document titled '{title}' in the corpus")
            continue
        if cited == b.record.doc_id:
            continue
        spans = phrase_spans(text, title)
        key = b.entity("Document", cited, title, "header", mentions=[title] if spans else [], spans=spans)
        b.rel(b.doc, "CITES", key, header_evidence(text, len(text), [title], f"Supporting Documents: {title}"),
              "header")


# ---------------------------------------------------------------------------- text facts
def add_text_facts(b: GraphBuilder, onto: Ontology, meeting_key: str | None) -> None:
    """MENTIONS / REFERENCES / DISCUSSED for every catalog entity found in the body (first mention
    as evidence). Committee and decision mentions are entities but the ontology allows no MENTIONS."""
    mention_targets = set(onto.relationships["MENTIONS"].to_labels)
    discussed_targets = set(onto.relationships["DISCUSSED"].to_labels)
    seen: set[str] = set()
    for m in b.body_matches:
        if m.entry.key in seen:
            continue
        seen.add(m.entry.key)
        key = b.catalog_entity(m.entry, "text")
        evidence = evidence_at(b.record.text, m.start, m.end)
        if m.entry.label in mention_targets:
            b.rel(b.doc, "MENTIONS", key, evidence, "text")
        if m.entry.label == "Decision":
            b.rel(b.doc, "REFERENCES", key, evidence, "text")
        if meeting_key and m.entry.label in discussed_targets:
            b.rel(meeting_key, "DISCUSSED", key, evidence, "text")


def add_decided(b: GraphBuilder, meeting_key: str | None) -> None:
    """Meeting-DECIDED->Decision when the meeting is held by a committee, the decision id appears in
    the body and the decision log dates the decision on the meeting day."""
    if not meeting_key or meeting_key not in b.entities:
        return
    if not any(r.type == "HELD_BY" and r.source == meeting_key for r in b.relationships):
        return
    meeting_date = b.entities[meeting_key].properties.get("date")
    if not meeting_date:
        return
    log, seen = decision_log(), set()
    for m in b.body_matches:
        if m.entry.label != "Decision" or m.entry.key in seen:
            continue
        seen.add(m.entry.key)
        if log.get(m.entry.id, {}).get("date") == meeting_date:
            b.rel(meeting_key, "DECIDED", b.catalog_entity(m.entry, "text"),
                  evidence_at(b.record.text, m.start, m.end), "text")


def decision_date(decision_id: str) -> str | None:
    return decision_log().get(decision_id, {}).get("date")


# ---------------------------------------------------------------------------- engine
class RulesExtractor:
    """Deterministic extraction: document structure + catalog and vocabulary matches in the body."""

    def __init__(self, catalog: Catalog | None = None, ontology: Ontology | None = None):
        self.catalog = catalog or load_catalog()
        self.onto = ontology or load_ontology()

    def extract(self, record: DocumentRecord, title_index: dict[str, str] | None = None) -> Extraction:
        b = GraphBuilder(record, self.catalog)
        meeting_key = add_header_facts(b, self.onto, title_index)
        add_text_facts(b, self.onto, meeting_key)
        add_decided(b, meeting_key)
        return b.extraction(ENGINE)
