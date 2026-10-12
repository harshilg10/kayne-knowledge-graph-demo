"""Extraction: rules engine, shared semantic mapping (finalize), orchestration and recall (no Neo4j needed).

Records are composed directly from the manifest (no dependency on kgdemo.ingest), in the canonical text
format of docs/ARCHITECTURE.md: header block (title line and `Key: value` lines), a blank line, the body.
"""
from __future__ import annotations

import json

import pytest

from kgdemo import world as w
from kgdemo.catalog import normalize_text
from kgdemo.config import SOURCE_DOCS_DIR
from kgdemo.eval_extraction import describe, evaluate, expected_entities
from kgdemo.extract_rules import EVIDENCE_MAX, RulesExtractor, decision_date, evidence_at
from kgdemo.extraction import build_title_index, extract_all, extract_record, finalize
from kgdemo.manifest import DocSpec, doc_specs
from kgdemo.models import DocumentRecord, EntityRef, Extraction, RelationshipRef, doc_key, meeting_id, split_key
from kgdemo.ontology import load_ontology

HERO_TEXT = ("Investment Committee Meeting\n\nDate: 2026-01-15\n\nParticipants:\nDouglas Whitfield\nMeredith Calloway\n\n"
             "Discussion:\nWe remain bullish on Nvidia and other AI infrastructure providers.\n"
             "The technology team believes demand for GPU capacity will continue through 2027.\n")
HERO_MEETING = "Meeting:MTG-20260115-INVESTMENT-COMMITTEE-MEETING"
HERO_DOC = "Document:DOC-MN-03"
DISCLAIMER = "This document is for internal use only and does not constitute investment advice."


# ---------------------------------------------------------------------------- record composition
def hero_record(text: str = HERO_TEXT) -> DocumentRecord:
    return DocumentRecord(
        doc_id="DOC-MN-03", doc_type="Meeting Notes", title="Investment Committee Meeting", date="2026-01-15",
        source_system="Document Management", source_path="data/unstructured/meeting_notes/DOC-MN-03__ic.md", text=text,
        body_offset=text.index("Discussion:"),
        metadata={"participants": [{"name": "Douglas Whitfield", "organization": None},
                                   {"name": "Meredith Calloway", "organization": None}],
                  "meeting_type": "Investment Committee"})


def _organization(name: str) -> str | None:
    person = w.person_by_name(name)
    return None if person["person_type"] == "employee" else person["organization"]


def _listed(name: str) -> str:
    """How a header lists a person: external people as `Name (Organization)`."""
    org = _organization(name)
    return f"{name} ({org})" if org else name


def _address(name: str) -> str:
    return f"{name} <{w.person_by_name(name)['email']}>"


def compose_record(spec: DocSpec, body: str) -> DocumentRecord:
    """A DocumentRecord in the canonical text format, with the metadata an ingester would parse."""
    titles = {s.doc_id: s.title for s in doc_specs()}
    tail: list[str] = []
    if spec.doc_type == "Meeting Notes":
        m = w.meeting_by_key(spec.meeting_key)
        head = [spec.title, f"Date: {spec.date}"]
        if spec.fixed_body is None:                     # the hero note omits it (the type is in the title)
            head.append(f"Meeting Type: {m['meeting_type']}")
        head += ["Participants:", *map(_listed, m["participants"])]
        metadata = {"participants": [{"name": n, "organization": _organization(n)} for n in m["participants"]],
                    "meeting_type": m["meeting_type"]}
    elif spec.doc_type == "IC Memo":
        cited = [titles[c] for c in spec.cites]
        head = ["ARBOR PEAK WEALTH PARTNERS", "INVESTMENT COMMITTEE MEMORANDUM", "To: Investment Committee",
                f"From: {', '.join(spec.authors)}", f"Date: {spec.date}", f"Subject: {spec.title}",
                f"Decision Reference: {spec.decision_ref}",
                f"For Meeting: Investment Committee Meeting, {spec.for_meeting_date}"]
        if cited:
            tail.append("Supporting Documents:\n" + "\n".join(cited))
        tail.append(DISCLAIMER)
        metadata = {"authors": list(spec.authors), "decision_ref": spec.decision_ref,
                    "for_meeting_date": spec.for_meeting_date, "cited_titles": cited}
    elif spec.doc_type == "Research Report":
        head = ["ARBOR PEAK WEALTH PARTNERS | RESEARCH", spec.title, f"Authors: {', '.join(spec.authors)}",
                f"Published: {spec.date}"]
        tail.append(DISCLAIMER)
        metadata = {"authors": list(spec.authors)}
    elif spec.doc_type == "Due Diligence":
        head = ["ARBOR PEAK WEALTH PARTNERS | PRIVATE CREDIT DUE DILIGENCE", spec.title,
                f"Borrower: {spec.borrower}", f"Prepared by: {', '.join(map(_listed, spec.authors))}",
                f"Date: {spec.date}"]
        tail.append(DISCLAIMER)
        metadata = {"authors": list(spec.authors), "borrower": spec.borrower}
    elif spec.doc_type == "Email":
        head = [spec.title, f"From: {_address(spec.sender)}", f"To: {', '.join(map(_address, spec.to))}"]
        if spec.cc:
            head.append(f"Cc: {', '.join(map(_address, spec.cc))}")
        head.append(f"Date: {spec.date}")
        metadata = {"sender": spec.sender, "sender_email": w.person_by_name(spec.sender)["email"],
                    "to": list(spec.to), "cc": list(spec.cc),
                    "to_emails": [w.person_by_name(n)["email"] for n in spec.to],
                    "cc_emails": [w.person_by_name(n)["email"] for n in spec.cc]}
    elif spec.doc_type == "CRM Note":
        client = w.client_by_id(spec.client_id)
        head = [spec.title, f"Date: {spec.date}", f"Client: {client['name']}", f"Owner: {spec.authors[0]}",
                f"Type: {spec.crm_type}"]
        metadata = {"client_id": spec.client_id, "client_name": client["name"], "owner": spec.authors[0],
                    "crm_type": spec.crm_type}
    else:
        raise ValueError(spec.doc_type)
    header = normalize_text("\n".join(head) + "\n\n")
    text = header + normalize_text("\n\n".join([body.strip(), *tail]) + "\n")
    return DocumentRecord(doc_id=spec.doc_id, doc_type=spec.doc_type, title=spec.title, date=spec.date,
                          source_system=spec.source_system, source_path=f"data/unstructured/{spec.doc_id}", text=text,
                          body_offset=len(header), metadata=metadata)


def real_body(spec: DocSpec) -> str | None:
    if spec.fixed_body is not None:
        return spec.fixed_body
    path = SOURCE_DOCS_DIR / f"{spec.doc_id}.txt"
    return path.read_text() if path.exists() else None


def placeholder_body(spec: DocSpec) -> str:
    lines = [f"- The team reviewed {surface}." for surface in spec.must_mention] or ["- General discussion."]
    return "Discussion:\n" + "\n".join(lines)


@pytest.fixture(scope="module")
def corpus():
    """Every manifest document (authored body when it exists, a placeholder otherwise), extracted."""
    specs = doc_specs()
    records = {s.doc_id: compose_record(s, real_body(s) or placeholder_body(s)) for s in specs}
    index = build_title_index(list(records.values()))
    extractions = {d: extract_record(r, "rules", index) for d, r in records.items()}
    return specs, records, extractions


def _triples(ex: Extraction) -> set[tuple[str, str, str]]:
    return {(r.source, r.type, r.target) for r in ex.relationships}


def _person(name: str) -> str:
    return f"Person:{w.person_by_name(name)['id']}"


# ---------------------------------------------------------------------------- hero acceptance
def test_hero_note_exact_graph():
    ex = extract_record(hero_record(), engine="rules")
    assert ex.engine == "rules" and ex.warnings == []
    assert {e.key for e in ex.entities} == {
        "Person:PER-001", "Person:PER-002", HERO_MEETING, "Company:CMP-NVDA", "Theme:THM-AI", "Concept:CON-GPU",
        "Committee:COM-IC"}
    assert _triples(ex) == {
        (HERO_DOC, "RECORDS", HERO_MEETING),
        ("Person:PER-001", "ATTENDED", HERO_MEETING),
        ("Person:PER-002", "ATTENDED", HERO_MEETING),
        (HERO_MEETING, "DISCUSSED", "Company:CMP-NVDA"),
        (HERO_MEETING, "DISCUSSED", "Theme:THM-AI"),
        (HERO_MEETING, "DISCUSSED", "Concept:CON-GPU"),
        (HERO_DOC, "MENTIONS", "Company:CMP-NVDA"),
        (HERO_DOC, "MENTIONS", "Theme:THM-AI"),
        (HERO_DOC, "MENTIONS", "Concept:CON-GPU"),
        (HERO_MEETING, "HELD_BY", "Committee:COM-IC"),
    }
    assert len(ex.relationships) == 10
    assert not any(r.properties.get("inferred") for r in ex.relationships)     # the theme is named explicitly
    assert ex.meeting == {"id": "MTG-20260115-INVESTMENT-COMMITTEE-MEETING", "title": "Investment Committee Meeting",
                          "date": "2026-01-15", "meeting_type": "Investment Committee"}
    assert ex.document == {"id": "DOC-MN-03", "title": "Investment Committee Meeting", "doc_type": "Meeting Notes",
                           "date": "2026-01-15", "source_system": "Document Management",
                           "source_path": "data/unstructured/meeting_notes/DOC-MN-03__ic.md"}


def test_hero_entities_carry_identity_mentions_and_spans():
    record = hero_record()
    ex = extract_record(record)
    by_key = {e.key: e for e in ex.entities}
    for key, surface, origin in [("Company:CMP-NVDA", "Nvidia", "text"),
                                 ("Theme:THM-AI", "AI infrastructure", "text"),
                                 ("Concept:CON-GPU", "GPU capacity", "text"),
                                 ("Person:PER-001", "Douglas Whitfield", "header"),
                                 ("Committee:COM-IC", "Investment Committee", "header")]:
        e = by_key[key]
        assert e.origin == origin and e.resolved and surface in e.mentions
        assert [record.text[s:t] for s, t in e.spans] == [surface]
    meeting = by_key[HERO_MEETING]
    assert meeting.name == "Investment Committee Meeting" and meeting.origin == "header"
    assert meeting.properties == {"date": "2026-01-15", "meeting_type": "Investment Committee"}


def test_hero_evidence_is_the_supporting_line():
    ex = extract_record(hero_record())
    evidence = {(r.type, r.target): r.evidence for r in ex.relationships}
    assert evidence[("MENTIONS", "Company:CMP-NVDA")] == (
        "We remain bullish on Nvidia and other AI infrastructure providers.")
    assert evidence[("DISCUSSED", "Concept:CON-GPU")] == ("The technology team believes demand for GPU capacity will "
                                                          "continue through 2027.")
    assert evidence[("ATTENDED", HERO_MEETING)].startswith("Participants: ")
    assert all(r.evidence and len(r.evidence) <= EVIDENCE_MAX for r in ex.relationships)
    assert {r.method for r in ex.relationships} == {"header", "text"}


def test_concept_alone_infers_the_theme_with_explanation():
    text = HERO_TEXT.replace("We remain bullish on Nvidia and other AI infrastructure providers.",
                             "We remain bullish on Nvidia.")
    ex = extract_record(hero_record(text))
    rels = {(r.source, r.type, r.target): r for r in ex.relationships}
    for source, rel_type in [(HERO_DOC, "MENTIONS"), (HERO_MEETING, "DISCUSSED")]:
        r = rels[(source, rel_type, "Theme:THM-AI")]
        assert r.properties == {"inferred": True, "via": "GPU Capacity"}
        assert r.method == "vocabulary"
        assert "GPU capacity" in r.evidence
    theme = next(e for e in ex.entities if e.key == "Theme:THM-AI")
    assert theme.origin == "inferred" and theme.mentions == [] and theme.spans == []


def test_meeting_type_is_inferred_from_the_title_when_missing():
    record = hero_record()
    record.metadata.pop("meeting_type")
    ex = extract_record(record)
    assert (HERO_MEETING, "HELD_BY", "Committee:COM-IC") in _triples(ex)
    assert ex.meeting["meeting_type"] == "Investment Committee"


# ---------------------------------------------------------------------------- finalize
def _raw(relationships: list[RelationshipRef], entities: list[EntityRef]) -> Extraction:
    return Extraction(doc_id="DOC-MN-03", engine="test", document={}, entities=entities, relationships=relationships)


def test_finalize_validates_domain_range_endpoints_and_duplicates():
    nvda = EntityRef(key="Company:CMP-NVDA", label="Company", id="CMP-NVDA", name="Nvidia")
    ic = EntityRef(key="Committee:COM-IC", label="Committee", id="COM-IC", name="Investment Committee")
    rels = [
        RelationshipRef(HERO_DOC, "MENTIONS", "Company:CMP-NVDA", "first", "text"),
        RelationshipRef(HERO_DOC, "MENTIONS", "Company:CMP-NVDA", "duplicate", "text"),
        RelationshipRef(HERO_DOC, "MENTIONS", "Committee:COM-IC", "not allowed", "text"),
        RelationshipRef("Company:CMP-NVDA", "ATTENDED", HERO_MEETING, "not allowed", "text"),
        RelationshipRef(HERO_DOC, "MENTIONS", "Fund:FND-AIX", "dangling", "text"),
        RelationshipRef(HERO_DOC, "SECRETLY_LIKES", "Company:CMP-NVDA", "unknown type", "text"),
        RelationshipRef(HERO_DOC, "CITES", HERO_DOC, "self-reference", "llm"),
        RelationshipRef(HERO_DOC, "MENTIONS", "Company:CMP-NVDA", "x" * 1000, "text"),
    ]
    ex = finalize(_raw(rels, [ic, nvda]), hero_record())
    assert [(r.type, r.target, r.evidence) for r in ex.relationships] == [("MENTIONS", "Company:CMP-NVDA", "first")]
    joined = "\n".join(ex.warnings)
    assert "does not allow Document -MENTIONS-> Committee" in joined
    assert "does not allow Company -ATTENDED-> Meeting" in joined
    assert "Fund:FND-AIX is not an extracted entity" in joined
    assert "SECRETLY_LIKES" in joined
    assert "a relationship needs two endpoints" in joined
    assert [e.key for e in ex.entities] == ["Committee:COM-IC", "Company:CMP-NVDA"]   # sorted by key


def test_finalize_truncates_evidence_and_is_idempotent():
    long_line = "x" * 1000
    nvda = EntityRef(key="Company:CMP-NVDA", label="Company", id="CMP-NVDA", name="Nvidia")
    gpu = EntityRef(key="Concept:CON-GPU", label="Concept", id="CON-GPU", name="GPU Capacity")
    rels = [RelationshipRef(HERO_DOC, "MENTIONS", "Concept:CON-GPU", long_line, "llm"),
            RelationshipRef(HERO_DOC, "MENTIONS", "Company:CMP-NVDA", "ok", "llm")]
    raw = _raw(rels, [gpu, nvda])
    once = finalize(raw, hero_record())
    assert all(len(r.evidence) <= EVIDENCE_MAX for r in once.relationships)
    assert [(r.type, r.source, r.target) for r in once.relationships] == sorted(
        (r.type, r.source, r.target) for r in once.relationships)
    assert finalize(once, hero_record()).to_dict() == once.to_dict()
    assert len(raw.relationships) == 2 and raw.relationships[0].evidence == long_line   # input untouched


def test_explicit_theme_link_suppresses_the_inferred_one():
    gpu = EntityRef(key="Concept:CON-GPU", label="Concept", id="CON-GPU", name="GPU Capacity")
    hbm = EntityRef(key="Concept:CON-HBM", label="Concept", id="CON-HBM", name="High-Bandwidth Memory")
    rels = [RelationshipRef(HERO_DOC, "MENTIONS", "Concept:CON-GPU", "gpu", "text"),
            RelationshipRef(HERO_DOC, "MENTIONS", "Concept:CON-HBM", "hbm", "text")]
    ex = finalize(_raw(rels, [gpu, hbm]), hero_record())
    inferred = [r for r in ex.relationships if r.target == "Theme:THM-AI"]
    assert len(inferred) == 1 and inferred[0].properties == {"inferred": True, "via": "GPU Capacity"}

    theme = EntityRef(key="Theme:THM-AI", label="Theme", id="THM-AI", name="AI Infrastructure")
    rels.append(RelationshipRef(HERO_DOC, "MENTIONS", "Theme:THM-AI", "explicit", "text"))
    ex = finalize(_raw(rels, [gpu, hbm, theme]), hero_record())
    theme_links = [r for r in ex.relationships if r.target == "Theme:THM-AI"]
    assert [(r.evidence, r.properties) for r in theme_links] == [("explicit", {})]


# ---------------------------------------------------------------------------- evidence and header facts
def test_evidence_uses_the_sentence_of_a_long_line_and_stays_short():
    filler = "The committee spent a long time on portfolio construction details and trading logistics. " * 4
    line = filler + "Meredith Calloway expects GPU capacity to stay tight through 2027. " + filler
    text = "Discussion:\n- " + line + "\nNext line."
    start = text.index("GPU capacity")
    ev = evidence_at(text, start, start + len("GPU capacity"))
    assert ev == "Meredith Calloway expects GPU capacity to stay tight through 2027."
    words = " ".join(["word"] * 120)
    text = f"{words} GPU capacity {words}."
    start = text.index("GPU capacity")
    ev = evidence_at(text, start, start + len("GPU capacity"))
    assert len(ev) <= EVIDENCE_MAX and "GPU capacity" in ev and ev.startswith("...") and ev.endswith("...")
    text = "- Dr. Leah Goldberg said power demand is rising. " + "x " * 200
    start = text.index("Leah Goldberg")
    assert evidence_at(text, start, start + 13).startswith("Dr. Leah Goldberg said power demand is rising.")


def test_unresolved_header_people_become_candidate_entities():
    record = hero_record()
    record.metadata["participants"].append({"name": "Jane Doe", "organization": "Acme Advisors"})
    record.text = record.text.replace("Meredith Calloway\n", "Meredith Calloway\nJane Doe (Acme Advisors)\n")
    record.body_offset = record.text.index("Discussion:")
    ex = extract_record(record)
    jane = next(e for e in ex.entities if e.label == "Person" and not e.resolved)
    assert jane.key == "Person:NEW-PERSON-JANE-DOE" and jane.name == "Jane Doe" and jane.origin == "header"
    assert ("Person:NEW-PERSON-JANE-DOE", "ATTENDED", HERO_MEETING) in _triples(ex)
    assert any("Jane Doe" in w_ and "not in the catalog" in w_ for w_ in ex.warnings)


def test_email_people_resolve_by_address_first():
    spec = next(s for s in doc_specs() if s.doc_id == "DOC-EM-01")
    record = compose_record(spec, placeholder_body(spec))
    record.metadata["sender"] = "M. Torres"                    # display name unknown to the catalog
    ex = extract_record(record)
    assert ("Person:PER-018", "SENT", "Document:DOC-EM-01") in _triples(ex)
    assert not ex.warnings


def test_citations_need_the_title_index():
    spec = next(s for s in doc_specs() if s.doc_id == "DOC-ICM-03")
    record = compose_record(spec, placeholder_body(spec))
    ex = extract_record(record)                              # no index
    assert not [r for r in ex.relationships if r.type == "CITES"]
    assert any("no title index" in w_ for w_ in ex.warnings)
    ex = extract_record(record, title_index={"some other title": "DOC-RR-99"})
    assert sum("unresolved citation" in w_ for w_ in ex.warnings) == len(spec.cites)


def test_title_index_normalizes_and_drops_ambiguous_titles():
    def rec(doc_id, title):
        return DocumentRecord(doc_id, "Research Report", title, "2026-01-01", "Research Portal", "", title, 0)
    index = build_title_index([rec("DOC-A", "GPU  Demand Outlook \u2013 2026"), rec("DOC-B", "Same"),
                               rec("DOC-C", "same")])
    assert index == {"gpu demand outlook - 2026": "DOC-A"}


# ---------------------------------------------------------------------------- whole corpus
def test_every_relationship_is_allowed_by_the_semantic_model(corpus):
    specs, _, extractions = corpus
    onto = load_ontology()
    assert len(extractions) == len(specs) == 101
    for doc_id, ex in extractions.items():
        assert ex.warnings == [], (doc_id, ex.warnings)
        keys = {e.key for e in ex.entities} | {doc_key(doc_id)}
        for r in ex.relationships:
            assert onto.allows(r.type, split_key(r.source)[0], split_key(r.target)[0]), (doc_id, r)
            assert r.source in keys and r.target in keys, (doc_id, r)
            assert r.evidence and len(r.evidence) <= EVIDENCE_MAX, (doc_id, r)


def test_meeting_structure_and_decisions(corpus):
    specs, records, extractions = corpus
    for spec in specs:
        ex = extractions[spec.doc_id]
        decided = [r for r in ex.relationships if r.type == "DECIDED"]
        if spec.doc_type != "Meeting Notes":
            assert not decided and ex.meeting is None, spec.doc_id
            continue
        m = w.meeting_by_key(spec.meeting_key)
        mkey = f"Meeting:{m['id']}"
        triples = _triples(ex)
        assert ex.meeting["id"] == m["id"] == meeting_id(spec.date, spec.title)
        assert (doc_key(spec.doc_id), "RECORDS", mkey) in triples
        assert {s for s, t, o in triples if t == "ATTENDED"} == {_person(n) for n in m["participants"]}
        assert {o for s, t, o in triples if t == "HELD_BY"} == (
            {f"Committee:{m['committee_id']}"} if m["committee_id"] else set()), spec.doc_id
        assert {o for s, t, o in triples if t == "FOR_CLIENT"} == (
            {f"Client:{m['client_id']}"} if m["client_id"] else set()), spec.doc_id
        body = records[spec.doc_id].body
        expected = {d for d in m["decision_ids"] if d in body} if m["committee_id"] else set()
        assert {split_key(r.target)[1] for r in decided} == expected, spec.doc_id
        for r in decided:                       # only committee meetings, only decisions taken that day
            assert r.source == mkey and decision_date(split_key(r.target)[1]) == m["date"]


def test_documents_structure_by_type(corpus):
    specs, _, extractions = corpus
    for spec in specs:
        ex, doc = extractions[spec.doc_id], doc_key(spec.doc_id)
        triples = _triples(ex)
        authored = {s for s, t, o in triples if t == "AUTHORED" and o == doc}
        if spec.doc_type == "IC Memo":
            assert {o for s, t, o in triples if t == "CITES"} == {doc_key(c) for c in spec.cites}, spec.doc_id
            assert (doc, "PROPOSES", f"Decision:{spec.decision_ref}") in triples
            assert authored == {_person(a) for a in spec.authors}
        elif spec.doc_type in ("Research Report", "Due Diligence"):
            assert authored == {_person(a) for a in spec.authors}
        if spec.doc_type == "Due Diligence":
            borrower = next(e for e in ex.entities if e.name == spec.borrower)
            assert {o for s, t, o in triples if t == "ABOUT"} == {borrower.key}
        if spec.doc_type == "Email":
            assert {s for s, t, o in triples if t == "SENT"} == {_person(spec.sender)}
            assert {o for s, t, o in triples if t == "SENT_TO"} == {_person(n) for n in spec.to + spec.cc}
        if spec.doc_type == "CRM Note":
            assert {o for s, t, o in triples if t == "ABOUT"} == {f"Client:{spec.client_id}"}
            assert authored == {_person(spec.authors[0])}
        if spec.doc_type != "IC Memo":
            assert not [t for s, t, o in triples if t in ("CITES", "PROPOSES")], spec.doc_id


def test_rules_recall_on_authored_bodies_is_complete(corpus):
    specs, _, extractions = corpus
    authored = [extractions[s.doc_id] for s in specs if real_body(s) is not None]
    report = evaluate(authored)
    misses = "\n".join(f"  {doc_id}: missing {', '.join(describe(k) for k in d['missing'])}"
                       for doc_id, d in report["per_doc"].items() if d["missing"])
    assert not report["manifest_problems"], report["manifest_problems"]
    assert report["recall"] == 1.0, f"rules-engine recall {report['recall']:.1%} on authored bodies:\n{misses}"


def test_rules_recall_on_placeholder_bodies_is_complete():
    """Independent of the authored corpus: every expected entity of every manifest document is found."""
    specs = doc_specs()
    records = [compose_record(s, s.fixed_body or placeholder_body(s)) for s in specs]
    index = build_title_index(records)
    report = evaluate([extract_record(r, "rules", index) for r in records])
    assert report["documents"] == len(specs) and report["recall"] == 1.0, report
    assert report["not_extracted"] == [] and report["unknown_documents"] == []


def test_expected_entities_of_the_hero_note():
    spec = next(s for s in doc_specs() if s.doc_id == "DOC-MN-03")
    keys, problems = expected_entities(spec)
    assert keys == {"Person:PER-001", "Person:PER-002", HERO_MEETING} and problems == []


# ---------------------------------------------------------------------------- orchestration
def test_extract_all_writes_files_and_removes_stale_ones(tmp_path):
    specs = [s for s in doc_specs() if s.doc_id in ("DOC-MN-03", "DOC-ICM-03", "DOC-RR-01", "DOC-EM-04")]
    records = [compose_record(s, s.fixed_body or placeholder_body(s)) for s in specs]
    (tmp_path / "DOC-OLD-01.json").write_text("{}")
    (tmp_path / "documents.json").write_text("[]")              # ingest's record dump lives here too
    out = extract_all(records, engine="rules", out_dir=tmp_path)
    assert [e.doc_id for e in out] == sorted(r.doc_id for r in records)
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(
        [f"{r.doc_id}.json" for r in records] + ["documents.json"])
    saved = Extraction.load(tmp_path / "DOC-ICM-03.json")
    assert saved.to_dict() == next(e for e in out if e.doc_id == "DOC-ICM-03").to_dict()
    assert ("Document:DOC-ICM-03", "CITES", "Document:DOC-RR-01") in _triples(saved)   # index over the batch
    assert json.loads((tmp_path / "DOC-MN-03.json").read_text())["meeting"]["id"] == HERO_MEETING.split(":")[1]
    assert extract_all([], out_dir=tmp_path) == [] and (tmp_path / "DOC-MN-03.json").exists()


def test_eval_cli_reads_the_extraction_directory(tmp_path, capsys):
    from kgdemo import eval_extraction
    specs = {s.doc_id: s for s in doc_specs()}
    records = [compose_record(specs[d], placeholder_body(specs[d])) for d in ("DOC-RR-01", "DOC-CRM-01")]
    extract_all(records, out_dir=tmp_path)
    (tmp_path / "documents.json").write_text("[]")
    (tmp_path / "DOC-BROKEN.json").write_text("{not json")
    assert eval_extraction.main(["--dir", str(tmp_path), "--strict"]) == 0
    out = capsys.readouterr().out
    assert "2 documents evaluated: recall 100.0%" in out and "unreadable extraction DOC-BROKEN.json" in out
    assert "documents.json" not in out
    saved = Extraction.load(tmp_path / "DOC-RR-01.json")
    saved.entities = [e for e in saved.entities if e.key != "Company:CMP-NVDA"]
    saved.save(tmp_path / "DOC-RR-01.json")
    assert eval_extraction.main(["--dir", str(tmp_path), "--strict"]) == 1
    assert "DOC-RR-01" in (report := capsys.readouterr().out) and "Company:CMP-NVDA (Nvidia)" in report


def test_extraction_cli(monkeypatch, tmp_path, capsys):
    import sys
    from types import SimpleNamespace
    from kgdemo import config, extraction
    specs = {s.doc_id: s for s in doc_specs()}
    records = [compose_record(specs[d], placeholder_body(specs[d])) for d in ("DOC-ICM-03", "DOC-RR-01", "DOC-EM-04")]
    monkeypatch.setitem(sys.modules, "kgdemo.ingest", SimpleNamespace(ingest_all=lambda raw_dir: records))
    monkeypatch.setattr(config, "EXTRACTED_DIR", tmp_path)
    (tmp_path / "DOC-EM-04.json").write_text("{}")
    assert extraction.main(["DOC-ICM-03"]) == 0                 # one document, citations over the corpus
    assert sorted(p.name for p in tmp_path.iterdir()) == ["DOC-EM-04.json", "DOC-ICM-03.json"]
    assert ("Document:DOC-ICM-03", "CITES", "Document:DOC-RR-01") in _triples(
        Extraction.load(tmp_path / "DOC-ICM-03.json"))
    assert extraction.main([]) == 0
    assert sorted(p.name for p in tmp_path.iterdir()) == ["DOC-EM-04.json", "DOC-ICM-03.json", "DOC-RR-01.json"]
    assert Extraction.load(tmp_path / "DOC-EM-04.json").doc_id == "DOC-EM-04"
    assert extraction.main(["DOC-NOPE"]) == 2
    out = capsys.readouterr().out
    assert "DOC-ICM-03" in out and "3 documents" in out and "unknown document ids: DOC-NOPE" in out


def test_unknown_engine_is_rejected():
    with pytest.raises(ValueError):
        extract_record(hero_record(), engine="gpt")
    with pytest.raises(ValueError):
        extract_all([hero_record()], engine="gpt")


def test_rules_extractor_returns_a_raw_extraction():
    raw = RulesExtractor().extract(hero_record())
    assert raw.engine == "rules" and raw.meeting is None          # finalize adds the meeting dict
    assert finalize(raw, hero_record()).meeting["id"] == HERO_MEETING.split(":")[1]
