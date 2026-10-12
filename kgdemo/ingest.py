"""Ingestion: raw files (data/unstructured) -> DocumentRecord.

Behaves like a production ingestion pipeline: the files are the only input (nothing here reads the
manifest or the world model). One parser per format implements the raw file contract in
docs/ARCHITECTURE.md. Every record gets a clean canonical text - a header block (title line, then
"Key: value" lines), a blank line, then the body - with `body_offset` pointing at the body. Meeting notes
are already written that way, so their text is the normalized file content itself.

    python -m kgdemo.ingest        # data/unstructured -> build/extracted/documents.json, prints counts per type
"""
from __future__ import annotations

import argparse
import csv
import email
import email.policy
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

from docx import Document
from pypdf import PdfReader

from . import config
from .catalog import normalize_text
from .models import DOC_TYPES, DocumentRecord

# ---- the raw file contract (render_docs writes exactly this) -------------------
FOLDERS: dict[str, tuple[str, str]] = {          # folder -> (doc_type, file extension)
    "meeting_notes": ("Meeting Notes", ".md"),
    "ic_memos": ("IC Memo", ".docx"),
    "research": ("Research Report", ".pdf"),
    "due_diligence": ("Due Diligence", ".pdf"),
    "emails": ("Email", ".eml"),
    "crm": ("CRM Note", ".csv"),
}
SOURCE_SYSTEMS = {
    "Meeting Notes": "Document Management",
    "IC Memo": "Document Management",
    "Research Report": "Research Portal",
    "Due Diligence": "Deal Management",
    "Email": "Email",
    "CRM Note": "CRM",
}
CRM_EXPORT_NAME = "crm_notes_export.csv"
CRM_COLUMNS = ("NoteId", "CreatedDate", "ClientId", "ClientName", "Owner", "Type", "Subject", "Body")
LETTERHEAD = config.FIRM_NAME.upper()
MEMO_HEADING = "INVESTMENT COMMITTEE MEMORANDUM"
RESEARCH_BANNER = f"{LETTERHEAD} | RESEARCH"
DD_BANNER = f"{LETTERHEAD} | PRIVATE CREDIT DUE DILIGENCE"
SUPPORTING_DOCUMENTS = "Supporting Documents:"
DISCLAIMER = "Synthetic demo document - fictional firm, clients and people. Not investment advice."
DOCUMENTS_JSON = config.EXTRACTED_DIR / "documents.json"

# header fields each format carries, as written in the file
_MEMO_FIELDS = ("To", "From", "Date", "Subject", "Decision Reference", "For Meeting")
_PDF_FIELDS = {"Research Report": ("Authors", "Published"), "Due Diligence": ("Borrower", "Prepared by", "Date")}
_NOTE_FIELDS = {"date": "date", "meeting type": "meeting_type", "participants": "participants",
                "attendees": "participants"}

_FIELD_RE = re.compile(r"^([A-Za-z][A-Za-z ]{0,40}?)\s*:\s*(.*)$")
_ISO_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_DATE_FORMATS = ("%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%m/%d/%Y")
_LIST_ITEM_RE = re.compile(r"^(?:[-*\u2022]|\d+[.)])\s")
_PEOPLE_SEP_RE = re.compile(r"\s*(?:[,;]|\band\b)\s*(?![^()]*\))")   # separators outside parentheses
_NAME_ORG_RE = re.compile(r"^(.*?)\s*\(([^()]*)\)$")
_PDF_LINE_GAP = 1.5   # baselines closer than 1.5 x font size belong to the same paragraph


# =============================================================================
# public API
# =============================================================================
def ingest_all(raw_dir: Path = config.UNSTRUCTURED_DIR) -> list[DocumentRecord]:
    """Every document under `raw_dir`, sorted by doc_id. Raises ValueError on duplicate ids."""
    records: list[DocumentRecord] = []
    for folder, (_, ext) in FOLDERS.items():
        folder_dir = Path(raw_dir) / folder
        if not folder_dir.is_dir():
            continue
        for path in sorted(folder_dir.iterdir()):
            if path.is_file() and path.suffix.lower() == ext and not path.name.startswith((".", "~$")):
                records.extend(ingest_path(path))
    dupes = sorted(doc_id for doc_id, n in Counter(r.doc_id for r in records).items() if n > 1)
    if dupes:
        raise ValueError(f"duplicate document ids in {raw_dir}: {', '.join(dupes)}")
    return sorted(records, key=lambda r: r.doc_id)


def ingest_path(path: Path) -> list[DocumentRecord]:
    """Parses one raw file; its folder decides the format. A CRM export yields one record per row."""
    path = Path(path)
    if path.parent.name not in FOLDERS:
        raise ValueError(f"{path}: not inside a raw folder ({', '.join(FOLDERS)})")
    doc_type, ext = FOLDERS[path.parent.name]
    if path.suffix.lower() != ext:
        raise ValueError(f"{path}: expected a {ext} file for {doc_type}")
    source_path = _relative(path)
    doc_id = path.name.split("__", 1)[0] if "__" in path.name else path.stem
    try:
        if doc_type == "CRM Note":
            return _parse_crm_export(path, source_path)
        if doc_type == "Meeting Notes":
            return [parse_meeting_notes(path.read_text(encoding="utf-8"), doc_id, source_path)]
        if doc_type == "IC Memo":
            return [_parse_memo(path, doc_id, source_path)]
        if doc_type == "Email":
            return [_parse_email(path, doc_id, source_path)]
        return [_parse_pdf(path, doc_id, doc_type, source_path)]
    except ValueError as exc:
        raise ValueError(f"{path.name}: {exc}") from exc


def parse_meeting_notes(text: str, doc_id: str, source_path: str) -> DocumentRecord:
    """Meeting notes: a title line, then Date / Meeting Type / Participants lines, then the body.

    Participants come one per line after "Participants:" (up to a blank line) or as "Participants: A, B".
    A missing Meeting Type is inferred from the title. The record text is the normalized note itself.
    """
    text = _clean_body(text) + "\n"
    lines = text.split("\n")
    title = lines[0].lstrip("#").strip()
    if not title:
        raise ValueError("the meeting note is empty")
    if _field_key(title) in _NOTE_FIELDS:
        raise ValueError("the first line must be the meeting title")
    fields: dict[str, str] = {}
    participants: list[tuple[str, str | None]] = []
    i = 1
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        kv = _field(line)
        if kv is None or kv[0] not in _NOTE_FIELDS:
            break                                          # the body starts here
        key, value = _NOTE_FIELDS[kv[0]], kv[1]
        i += 1
        if key != "participants":
            fields[key] = value
            continue
        participants = _split_people(value)
        while not value and i < len(lines) and _is_participant_line(lines[i]):
            participants += _split_people(lines[i])        # one participant per line
            i += 1
    if not fields.get("date"):
        raise ValueError("missing a 'Date:' line")
    body_offset = sum(len(line) + 1 for line in lines[:i]) if i < len(lines) else len(text)
    meeting_type = fields.get("meeting_type") or (
        "Investment Committee" if "investment committee" in title.lower() else "General")
    return DocumentRecord(
        doc_id=doc_id, doc_type="Meeting Notes", title=title, date=_parse_date(fields["date"]),
        source_system=SOURCE_SYSTEMS["Meeting Notes"], source_path=source_path, text=text,
        body_offset=body_offset,
        metadata={"participants": [{"name": n, "organization": o} for n, o in participants],
                  "meeting_type": meeting_type})


# =============================================================================
# format parsers
# =============================================================================
def _parse_memo(path: Path, doc_id: str, source_path: str) -> DocumentRecord:
    paragraphs = [p for p in (_clean_line(par.text) for par in Document(str(path)).paragraphs) if p]
    _, fields, rest = _header_fields(paragraphs, _MEMO_FIELDS)    # the letterhead precedes the fields
    if rest and rest[-1] == DISCLAIMER:
        rest = rest[:-1]
    cited: list[str] = []
    if SUPPORTING_DOCUMENTS in rest:
        cut = len(rest) - 1 - rest[::-1].index(SUPPORTING_DOCUMENTS)
        rest, cited = rest[:cut], rest[cut + 1:]
    title, when = _required(fields, "Subject"), _parse_date(_required(fields, "Date"))
    body = _join_blocks(rest)
    if cited:
        body += ("\n\n" if body else "") + "\n".join([SUPPORTING_DOCUMENTS, *cited])
    text, offset = _compose(title, [(k, v) for k, v in fields.items() if k != "Subject"], body)
    metadata = _authors_metadata(fields.get("From", ""))
    if fields.get("Decision Reference"):
        metadata["decision_ref"] = fields["Decision Reference"]
    meeting_date = _ISO_DATE_RE.search(fields.get("For Meeting", ""))
    if meeting_date:
        metadata["for_meeting_date"] = _parse_date(meeting_date.group(1))
    metadata["cited_titles"] = cited
    return DocumentRecord(doc_id, "IC Memo", title, when, SOURCE_SYSTEMS["IC Memo"], source_path, text, offset,
                          metadata)


def _parse_pdf(path: Path, doc_id: str, doc_type: str, source_path: str) -> DocumentRecord:
    blocks = _pdf_blocks(_pdf_lines(path))
    preamble, fields, rest = _header_fields(blocks, _PDF_FIELDS[doc_type])
    if preamble and preamble[0].startswith(LETTERHEAD) and preamble[0] == preamble[0].upper():
        preamble = preamble[1:]                            # the banner line
    title = " ".join(preamble)                             # a title may arrive as more than one block
    if not title:
        raise ValueError("no title before the header fields")
    if rest and rest[-1] == DISCLAIMER:
        rest = rest[:-1]
    if doc_type == "Research Report":
        when, people = _required(fields, "Published"), fields.get("Authors", "")
    else:
        when, people = _required(fields, "Date"), fields.get("Prepared by", "")
    text, offset = _compose(title, list(fields.items()), _join_blocks(rest))
    metadata = _authors_metadata(people)
    if doc_type == "Due Diligence":
        metadata["borrower"] = _required(fields, "Borrower")
    return DocumentRecord(doc_id, doc_type, title, _parse_date(when), SOURCE_SYSTEMS[doc_type], source_path, text,
                          offset, metadata)


def _parse_email(path: Path, doc_id: str, source_path: str) -> DocumentRecord:
    msg = email.message_from_bytes(path.read_bytes(), policy=email.policy.default)
    title = _clean_line(str(msg.get("Subject", ""))) or "(no subject)"
    senders, to, cc = (_addresses(msg, h) for h in ("From", "To", "Cc"))
    if not senders:
        raise ValueError("missing a From header")
    date_header = msg["Date"]
    if date_header is None or date_header.datetime is None:
        raise ValueError("missing or invalid Date header")
    when = date_header.datetime.date().isoformat()        # the sender's local date
    part = msg.get_body(preferencelist=("plain",))
    body = _clean_body(part.get_content()) if part is not None else ""
    sender, sender_email = senders[0]
    text, offset = _compose(title, [("From", sender), ("To", ", ".join(n for n, _ in to)),
                                    ("Cc", ", ".join(n for n, _ in cc)), ("Date", when)], body)
    metadata = {"sender": sender, "sender_email": sender_email,
                "to": [n for n, _ in to], "cc": [n for n, _ in cc],
                "to_emails": [a for _, a in to], "cc_emails": [a for _, a in cc]}
    return DocumentRecord(doc_id, "Email", title, when, SOURCE_SYSTEMS["Email"], source_path, text, offset, metadata)


def _parse_crm_export(path: Path, source_path: str) -> list[DocumentRecord]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        missing = [c for c in CRM_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"CRM export lacks columns {', '.join(missing)}")
        rows = list(reader)
    return [_crm_record(row, source_path) for row in rows]


def _crm_record(row: dict[str, str], source_path: str) -> DocumentRecord:
    doc_id = _clean_line(row["NoteId"])
    if not doc_id:
        raise ValueError("CRM row without a NoteId")
    title, when = _clean_line(row["Subject"]), _parse_date(row["CreatedDate"])
    client_name, owner, crm_type = (_clean_line(row[c]) for c in ("ClientName", "Owner", "Type"))
    text, offset = _compose(title, [("Date", when), ("Client", client_name), ("Owner", owner), ("Type", crm_type)],
                            _clean_body(row["Body"]))
    metadata = {"client_id": _clean_line(row["ClientId"]), "client_name": client_name, "owner": owner,
                "crm_type": crm_type}
    return DocumentRecord(doc_id, "CRM Note", title, when, SOURCE_SYSTEMS["CRM Note"], f"{source_path}#{doc_id}",
                          text, offset, metadata)


# =============================================================================
# PDF layout: lines with positions -> paragraphs
# =============================================================================
@dataclass(frozen=True)
class _PdfLine:
    page: int
    y: float          # baseline height on the page, in points
    size: float       # rendered font size, in points
    text: str


def _pdf_lines(path: Path) -> list[_PdfLine]:
    """Text lines in content order with their baseline and font size (pypdf's text visitor)."""
    lines: list[_PdfLine] = []
    for page_no, page in enumerate(PdfReader(path).pages):
        chunks: list[tuple[str, list[float], list[float], float]] = []
        page.extract_text(visitor_text=lambda text, cm, tm, font, size: chunks.append((text, cm, tm, size)))
        current: list[tuple[str, tuple[float, float]]] = []
        for text, cm, tm, size in chunks:
            for k, piece in enumerate(text.split("\n")):
                if k:                                      # pypdf ends every line with "\n"
                    lines.extend(_finish_line(page_no, current))
                    current = []
                current.append((piece, _baseline(cm, tm, size)))
        lines.extend(_finish_line(page_no, current))
    return lines


def _finish_line(page_no: int, pieces: list[tuple[str, tuple[float, float]]]) -> list[_PdfLine]:
    text = _clean_line("".join(piece for piece, _ in pieces))
    if not text:
        return []
    y, size = next(pos for piece, pos in pieces if piece.strip())
    return [_PdfLine(page_no, y, size, text)]


def _baseline(cm: list[float], tm: list[float], font_size: float) -> tuple[float, float]:
    """Baseline height and rendered font size of a chunk: text matrix x current transformation matrix."""
    _, _, c, d, e, f = tm
    cm_a, cm_b, cm_c, cm_d, _, cm_f = cm
    y = e * cm_b + f * cm_d + cm_f
    return y, font_size * math.hypot(c * cm_a + d * cm_c, c * cm_b + d * cm_d)


def _pdf_blocks(lines: list[_PdfLine]) -> list[str]:
    """Rejoins wrapped lines into paragraphs.

    A line continues the previous one when it is on the same page, in the same font size and within normal
    line spacing below it (or on the same baseline). Paragraph spacing, a size change or a new page starts a
    new block. Lines are joined with a space: the renderer never hyphenates, so no word is split.
    """
    blocks: list[str] = []
    prev: _PdfLine | None = None
    for line in lines:
        continues = (prev is not None and line.page == prev.page and abs(line.size - prev.size) < 0.1
                     and -0.5 < prev.y - line.y < _PDF_LINE_GAP * line.size)
        if continues:
            blocks[-1] = f"{blocks[-1]} {line.text}"
        else:
            blocks.append(line.text)
        prev = line
    return blocks


# =============================================================================
# text helpers
# =============================================================================
def _clean_line(text: str) -> str:
    """normalize_text and collapse all whitespace: for one-line values, docx paragraphs and PDF lines."""
    return " ".join(normalize_text(text).split())


def _clean_body(text: str) -> str:
    """normalize_text, LF line endings, no trailing spaces, no leading/trailing blank lines."""
    text = normalize_text(text).replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip() for line in text.split("\n")).strip()


def _join_blocks(blocks: list[str]) -> str:
    """Paragraphs separated by a blank line; a label ending in ':' sits directly above what follows it and
    consecutive list items stay on consecutive lines."""
    out: list[str] = []
    for i, block in enumerate(blocks):
        if i:
            prev = blocks[i - 1]
            tight = prev.endswith(":") or bool(_LIST_ITEM_RE.match(prev) and _LIST_ITEM_RE.match(block))
            out.append("\n" if tight else "\n\n")
        out.append(block)
    return "".join(out)


def _compose(title: str, fields: list[tuple[str, str]], body: str) -> tuple[str, int]:
    """Canonical text = title line + "Key: value" lines + blank line + body; returns (text, body_offset)."""
    header = "\n".join([title, *(f"{key}: {value}" for key, value in fields if value)])
    if not body:
        return header + "\n", len(header) + 1
    return f"{header}\n\n{body}\n", len(header) + 2


def _field(line: str) -> tuple[str, str] | None:
    """("key", "value") for a "Key: value" line (key lowercased), else None."""
    m = _FIELD_RE.match(line.strip())
    return (m.group(1).strip().lower(), m.group(2).strip()) if m else None


def _field_key(line: str) -> str | None:
    kv = _field(line)
    return kv[0] if kv else None


def _header_fields(blocks: list[str], keys: tuple[str, ...]) -> tuple[list[str], dict[str, str], list[str]]:
    """Splits blocks into (preamble, header fields in file order, rest).

    The header is the first run of "Key: value" blocks whose keys are in `keys`; whatever precedes it
    (letterhead, banner, title) is the preamble and the rest is the body.
    """
    canonical = {key.lower(): key for key in keys}
    start = next((i for i, b in enumerate(blocks) if _field_key(b) in canonical), len(blocks))
    fields: dict[str, str] = {}
    i = start
    while i < len(blocks):
        kv = _field(blocks[i])
        if kv is None or kv[0] not in canonical or canonical[kv[0]] in fields:
            break
        fields[canonical[kv[0]]] = kv[1]
        i += 1
    return blocks[:start], fields, blocks[i:]


def _required(fields: dict[str, str], key: str) -> str:
    if not fields.get(key):
        raise ValueError(f"missing a '{key}:' header")
    return fields[key]


def _is_participant_line(line: str) -> bool:
    """A name line in a participant list; a blank line, a label or a sentence ends the list."""
    line = line.strip()
    return bool(line) and ":" not in line and len(line) <= 100 and line[-1] not in ".!?"


def _split_people(value: str) -> list[tuple[str, str | None]]:
    """'A, B (Org)' -> [("A", None), ("B", "Org")]; also splits on ';' and 'and', never inside parentheses."""
    people = []
    for item in _PEOPLE_SEP_RE.split(_clean_line(value)):
        item = re.sub(r"^(?:[-*\u2022]\s*)+", "", item).strip()      # tolerate bulleted participant lists
        if not item:
            continue
        m = _NAME_ORG_RE.match(item)
        people.append((m.group(1), m.group(2).strip() or None) if m and m.group(1) else (item, None))
    return people


def _authors_metadata(value: str) -> dict:
    """authors (names only) plus author_organizations for authors written as 'Name (Organization)'."""
    people = _split_people(value)
    metadata: dict = {"authors": [name for name, _ in people]}
    organizations = {name: org for name, org in people if org}
    if organizations:
        metadata["author_organizations"] = organizations
    return metadata


def _addresses(msg: EmailMessage, header: str) -> list[tuple[str, str]]:
    """[(display name, lowercase address)] of an address header; the address stands in for a missing name."""
    value = msg.get(header)
    if value is None:
        return []
    return [(_clean_line(a.display_name) or a.addr_spec.lower(), a.addr_spec.lower()) for a in value.addresses]


def _parse_date(value: str) -> str:
    """ISO yyyy-mm-dd from an ISO date (optionally followed by a time) or a common written form."""
    value = _clean_line(value)
    iso = re.match(r"^(\d{4}-\d{2}-\d{2})(?:$|[T ])", value)
    candidates = [(iso.group(1), "%Y-%m-%d")] if iso else []
    for text, fmt in candidates + [(value, fmt) for fmt in _DATE_FORMATS]:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"unrecognized date {value!r}")


def _relative(path: Path) -> str:
    """Path relative to the project root (absolute when the file lives elsewhere)."""
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(config.ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


# =============================================================================
# CLI
# =============================================================================
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Parse the raw documents into DocumentRecords.")
    parser.add_argument("--raw-dir", type=Path, default=config.UNSTRUCTURED_DIR)
    parser.add_argument("--out", type=Path, default=DOCUMENTS_JSON)
    args = parser.parse_args(argv)
    records = ingest_all(args.raw_dir)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps([r.to_dict() for r in records], indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    counts = Counter(r.doc_type for r in records)
    for doc_type in DOC_TYPES:
        print(f"{doc_type:<16} {counts.get(doc_type, 0):>4}")
    print(f"{'total':<16} {len(records):>4}  -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
