"""Prints the authoring brief for one or more documents.

    python -m kgdemo.writer_packet DOC-RR-01 DOC-RR-02
"""
from __future__ import annotations

import sys

from . import world as w
from .catalog import load_catalog
from .manifest import DocSpec, doc_specs

STYLE_GUIDE = """\
AUTHORING RULES (synthetic demo corpus - fictional firm "Arbor Peak Wealth Partners")
1. Write ONLY the body. Title, date, participants/authors/from/to/subject, memo headers, the
   "Supporting Documents" list and disclaimers are rendered automatically - never repeat them,
   and never start a line with "Date:", "From:", "To:", "Subject:", "Participants:", etc.
2. Plain ASCII only: straight quotes, "-" for dashes, ">=" instead of special symbols. Light
   structure: section labels on their own line (e.g. "Discussion:"), bullets with "- ".
3. Mention EVERY required entity at least once using exactly the given wording (or a listed
   alias). Use people's full names at least once.
4. Never invent a named person, company, fund, client or IC decision id. Only use names from
   the catalog below. Generic references are fine ("an investment-grade hyperscale tenant",
   "our trading desk", "a regional utility").
5. Real public companies: views are the firm's own opinions. Do NOT state reported financial
   results, guidance figures, stock prices or real-world events as facts, and do not name or
   quote real executives. If you need a number, use the brief's numbers or label it clearly
   as an internal estimate.
6. Use the brief's numbers, dates and decision ids exactly. Do not invent other trade amounts,
   holdings or decision ids. Add realistic qualitative detail consistent with the brief.
7. Write as of the document date. Never reference anything that happens later (later
   decisions or meeting outcomes) except scheduled events named in the brief.
8. Respect "Do not use" phrases. Some documents intentionally never say "AI infrastructure":
   describe the topic with specific terms (GPU capacity, AI data centers, liquid cooling,
   hyperscaler capex, power demand...). This is deliberate for the semantic-search demo.
9. Style by type:
   - Meeting Notes: terse minutes. Sections "Discussion:", "Decisions:" (only if a decision
     was taken), "Action Items:". Attribute points to participants by name.
   - IC Memo: formal. Sections such as Recommendation, Background, Investment Thesis,
     Risks and Mitigants, Implementation.
   - Research Report: analytical. Sections such as Summary, Key Points, analysis, Risks,
     Portfolio Implications.
   - Due Diligence: Transaction Overview, Business Overview, Key Findings, Risks and
     Mitigants, Recommendation (adapt for a power assessment or legal summary).
   - Email: greeting, 1-4 short paragraphs, sign-off with the sender's name.
   - CRM Note: 2-6 terse factual sentences in third person (advisor's log).
10. Save the body as plain text to authoring/document_bodies/<DOC-ID>.txt, then run
    `.venv/bin/python -m kgdemo.validate_docs <DOC-ID> ...` and fix every error. Review every
    warning: rewrite any invented name; keep generic places/terms.
"""


def _header_preview(spec: DocSpec) -> list[str]:
    lines = [f"  type: {spec.doc_type}   date: {spec.date}   source system: {spec.source_system}",
             f"  title/subject: {spec.title}"]
    if spec.meeting_key:
        m = w.meeting_by_key(spec.meeting_key)
        lines.append(f"  meeting type: {m['meeting_type']}   participants: {', '.join(m['participants'])}")
        if m["decision_ids"]:
            lines.append(f"  decisions taken at this meeting: {', '.join(m['decision_ids'])}")
    if spec.authors:
        role = "owner (advisor)" if spec.doc_type == "CRM Note" else "authors/preparers"
        lines.append(f"  {role}: {', '.join(spec.authors)}")
    if spec.sender:
        lines.append(f"  from: {spec.sender}   to: {', '.join(spec.to)}" + (f"   cc: {', '.join(spec.cc)}" if spec.cc else ""))
    if spec.client_id:
        lines.append(f"  client: {w.client_by_id(spec.client_id)['name']}   note type: {spec.crm_type}")
    if spec.borrower:
        lines.append(f"  borrower / subject company: {spec.borrower}")
    if spec.decision_ref:
        lines.append(f"  proposes decision: {spec.decision_ref} (for the {spec.for_meeting_date} Investment Committee)")
    if spec.cites:
        titles = {s.doc_id: s.title for s in doc_specs()}
        lines.append("  supporting documents (rendered automatically): " + "; ".join(titles[c] for c in spec.cites))
    return lines


def packet(doc_ids: list[str]) -> str:
    specs = {s.doc_id: s for s in doc_specs()}
    out = [STYLE_GUIDE, "=" * 100]
    for did in doc_ids:
        s = specs[did]
        out.append(f"DOCUMENT {did}")
        out.extend(_header_preview(s))
        out.append(f"  length: {s.words[0]}-{s.words[1]} words")
        out.append(f"  MUST mention: {', '.join(s.must_mention)}")
        if s.avoid_phrases:
            out.append(f"  Do not use: {', '.join(repr(p) for p in s.avoid_phrases)}")
        out.append(f"  Brief: {s.brief}")
        out.append("-" * 100)
    out.append(catalog_listing())
    return "\n".join(out)


def catalog_listing() -> str:
    cat = load_catalog()
    people = {p["id"]: p for p in w.people()}
    lines = ["ALLOWED NAMED ENTITIES (canonical name [aliases])"]
    for label in ["Person", "Client", "Fund", "Company", "Committee", "Decision", "Theme", "Concept"]:
        lines.append(f"{label}:")
        for e in cat.of_label(label):
            extra = ""
            if label == "Person":
                p = people[e.id]
                extra = f" - {p['title']}, {p['organization']}"
            elif label == "Decision":
                d = w.decision_by_id(e.id)
                extra = f" - {d['date']}: {d['title']}"
            aliases = [f for f in e.forms if f != e.name]
            alias_txt = f" [{'; '.join(aliases)}]" if aliases and label not in ("Theme", "Concept") else ""
            if label in ("Theme", "Concept"):
                alias_txt = f" [{'; '.join(aliases[:6])}]"
            lines.append(f"  - {e.name}{alias_txt}{extra}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(packet(sys.argv[1:]))
