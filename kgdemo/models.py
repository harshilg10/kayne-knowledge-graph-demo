"""Shared data contracts between ingestion, extraction, loading and the app."""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

DOC_TYPES = ("Meeting Notes", "IC Memo", "Research Report", "Due Diligence", "Email", "CRM Note")


def meeting_id(meeting_date: str, title: str) -> str:
    """Deterministic meeting id from ISO date + title, e.g. MTG-20260115-INVESTMENT-COMMITTEE-MEETING."""
    slug = re.sub(r"[^A-Z0-9]+", "-", title.upper()).strip("-")
    return f"MTG-{meeting_date.replace('-', '')}-{slug}"


def entity_key(label: str, entity_id: str) -> str:
    return f"{label}:{entity_id}"


def doc_key(doc_id: str) -> str:
    return entity_key("Document", doc_id)


def split_key(key: str) -> tuple[str, str]:
    label, _, entity_id = key.partition(":")
    return label, entity_id


@dataclass
class DocumentRecord:
    """A parsed unstructured document, independent of its original file format."""
    doc_id: str
    doc_type: str                 # one of DOC_TYPES
    title: str
    date: str                     # ISO yyyy-mm-dd
    source_system: str
    source_path: str              # path relative to the project root (CRM rows: "...csv#DOC-CRM-01")
    text: str                     # full normalized text: header block + body
    body_offset: int              # index into `text` where the body starts
    metadata: dict = field(default_factory=dict)
    # metadata keys (present when applicable):
    #   participants: [{"name": str, "organization": str|None}]   meeting notes
    #   meeting_type: str                                           meeting notes
    #   authors: [str]                                              research, memo, DD (preparers)
    #   sender: str, sender_email: str, to: [str], cc: [str]        email (display names)
    #   to_emails: [str], cc_emails: [str]                          email
    #   client_id: str, client_name: str, owner: str, crm_type: str CRM note
    #   borrower: str                                               due diligence
    #   decision_ref: str, for_meeting_date: str                    IC memo
    #   cited_titles: [str]                                         IC memo supporting documents

    @property
    def body(self) -> str:
        return self.text[self.body_offset:]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "DocumentRecord":
        return cls(**d)


@dataclass
class EntityRef:
    key: str                      # "<Label>:<id>", e.g. "Person:PER-001", "Meeting:MTG-20260115-..."
    label: str
    id: str
    name: str
    mentions: list[str] = field(default_factory=list)       # surface forms found in the text
    spans: list[list[int]] = field(default_factory=list)    # [start, end) offsets into DocumentRecord.text
    origin: str = "text"          # text | header | inferred
    resolved: bool = True         # False = not in the catalog (candidate entity proposed by the LLM)
    properties: dict = field(default_factory=dict)


@dataclass
class RelationshipRef:
    source: str                   # entity key
    type: str                     # relationship type from the ontology
    target: str                   # entity key
    evidence: str = ""            # supporting text (<= 300 chars)
    method: str = ""              # header | text | vocabulary | rule | llm
    properties: dict = field(default_factory=dict)


@dataclass
class Extraction:
    doc_id: str
    engine: str                   # "rules" or "claude:<model>"
    document: dict                # {id, title, doc_type, date, source_system, source_path}
    entities: list[EntityRef] = field(default_factory=list)
    relationships: list[RelationshipRef] = field(default_factory=list)
    meeting: dict | None = None   # {id, title, date, meeting_type} when the document records a meeting
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Extraction":
        return cls(doc_id=d["doc_id"], engine=d["engine"], document=d["document"],
                   entities=[EntityRef(**e) for e in d.get("entities", [])],
                   relationships=[RelationshipRef(**r) for r in d.get("relationships", [])],
                   meeting=d.get("meeting"), warnings=list(d.get("warnings", [])))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False))

    @classmethod
    def load(cls, path: Path) -> "Extraction":
        return cls.from_dict(json.loads(Path(path).read_text()))
