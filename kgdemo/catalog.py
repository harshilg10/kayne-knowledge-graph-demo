"""Entity catalog + gazetteer: the identity layer that links text mentions to graph entities.

The catalog is built the way a production pipeline would build it:
  * names, aliases and tickers come from the structured exports (master data)
  * themes, concepts and committees come from the semantic model vocabulary
Text matching is case-sensitive for names (so "micron" the unit never matches
Micron the company) and case-insensitive for vocabulary phrases.
"""
from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from .config import STRUCTURED_DIR
from .ontology import load_ontology

_WORD = r"A-Za-z0-9_"


def normalize_text(text: str) -> str:
    """Unicode/typography normalization applied to every document before matching."""
    text = unicodedata.normalize("NFKC", text)
    for a, b in (("‘", "'"), ("’", "'"), ("“", '"'), ("”", '"'), ("–", "-"),
                 ("—", "-"), ("−", "-"), (" ", " "), ("‐", "-"), ("‑", "-")):
        text = text.replace(a, b)
    return text


def _collapse(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


@dataclass(frozen=True)
class CatalogEntry:
    label: str                 # Person | Company | Fund | Client | Theme | Concept | Committee | Decision
    id: str
    name: str
    forms: tuple[str, ...]
    case_sensitive: bool
    theme_id: str | None = None  # for concepts

    @property
    def key(self) -> str:
        return f"{self.label}:{self.id}"


@dataclass(frozen=True)
class Match:
    entry: CatalogEntry
    start: int
    end: int
    surface: str


@dataclass
class Catalog:
    entries: list[CatalogEntry]
    by_key: dict[str, CatalogEntry] = field(default_factory=dict)
    by_id: dict[str, CatalogEntry] = field(default_factory=dict)
    by_form_cs: dict[str, CatalogEntry] = field(default_factory=dict)
    by_form_ci: dict[str, CatalogEntry] = field(default_factory=dict)
    emails: dict[str, CatalogEntry] = field(default_factory=dict)

    def __post_init__(self):
        for e in self.entries:
            if e.key in self.by_key:
                raise ValueError(f"duplicate catalog key {e.key}")
            self.by_key[e.key] = e
            self.by_id[e.id] = e
            for form in e.forms:
                norm = _collapse(form)
                table, k = (self.by_form_cs, norm) if e.case_sensitive else (self.by_form_ci, norm.lower())
                other = table.get(k)
                if other is not None and other.key != e.key:
                    raise ValueError(f"surface form '{form}' is ambiguous: {other.key} vs {e.key}")
                table[k] = e
        for form, e in self.by_form_cs.items():
            other = self.by_form_ci.get(form.lower())
            if other is not None and other.key != e.key:
                raise ValueError(f"surface form '{form}' collides across case rules: {e.key} vs {other.key}")
        self._regex_cs = _build_regex([f for e in self.entries if e.case_sensitive for f in e.forms], False)
        self._regex_ci = _build_regex([f for e in self.entries if not e.case_sensitive for f in e.forms], True)

    # -- lookups -----------------------------------------------------------------
    def lookup(self, surface: str) -> CatalogEntry | None:
        norm = _collapse(normalize_text(surface))
        return self.by_form_cs.get(norm) or self.by_form_ci.get(norm.lower())

    def of_label(self, label: str) -> list[CatalogEntry]:
        return [e for e in self.entries if e.label == label]

    def person_by_name(self, name: str) -> CatalogEntry | None:
        e = self.lookup(name)
        return e if e is not None and e.label == "Person" else None

    # -- matching ------------------------------------------------------------------
    def find(self, text: str) -> list[Match]:
        """All non-overlapping catalog mentions in `text`, longest match wins."""
        candidates: list[Match] = []
        for regex, table, ci in ((self._regex_cs, self.by_form_cs, False), (self._regex_ci, self.by_form_ci, True)):
            if regex is None:
                continue
            for m in regex.finditer(text):
                surface = m.group(1)
                key = _collapse(surface)
                entry = table.get(key.lower() if ci else key)
                if entry is not None:
                    candidates.append(Match(entry, m.start(1), m.start(1) + len(surface), surface))
        candidates.sort(key=lambda c: (-(c.end - c.start), c.start))
        taken: list[Match] = []
        occupied = []
        for c in candidates:
            if any(c.start < e and s < c.end for s, e in occupied):
                continue
            taken.append(c)
            occupied.append((c.start, c.end))
        taken.sort(key=lambda c: c.start)
        return taken


def _form_pattern(form: str) -> str:
    return r"\s+".join(re.escape(part) for part in _collapse(form).split(" "))


def _build_regex(forms: list[str], ignore_case: bool):
    uniq = sorted({_collapse(f) for f in forms if f.strip()}, key=lambda s: (-len(s), s))
    if not uniq:
        return None
    alternation = "|".join(_form_pattern(f) for f in uniq)
    pattern = rf"(?<![{_WORD}])(?=({alternation})(?![{_WORD}]))"
    return re.compile(pattern, re.IGNORECASE if ignore_case else 0)


def _read(path: Path) -> list[dict]:
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


def _split(value: str) -> list[str]:
    return [v for v in (value or "").split("|") if v]


@lru_cache(maxsize=2)
def load_catalog(structured_dir: str | Path = STRUCTURED_DIR) -> Catalog:
    sd = Path(structured_dir)
    if not (sd / "people.csv").exists():
        from .generate_structured import generate
        generate(sd)
    onto = load_ontology()
    entries: list[CatalogEntry] = []
    emails: dict[str, str] = {}
    for row in _read(sd / "people.csv") + _read(sd / "contacts.csv"):
        entries.append(CatalogEntry("Person", row["id"], row["name"], (row["name"], *_split(row["aliases"])), True))
        emails[row["email"].lower()] = row["id"]
    for row in _read(sd / "companies.csv"):
        entries.append(CatalogEntry("Company", row["id"], row["name"], (row["name"], *_split(row["aliases"])), True))
    for row in _read(sd / "funds.csv"):
        entries.append(CatalogEntry("Fund", row["id"], row["name"], (row["name"], *_split(row["aliases"])), True))
    for row in _read(sd / "clients.csv"):
        entries.append(CatalogEntry("Client", row["id"], row["name"], (row["name"], *_split(row["aliases"])), True))
    for row in _read(sd / "ic_decisions.csv"):
        entries.append(CatalogEntry("Decision", row["id"], row["id"], (row["id"],), True))
    for c in onto.committees.values():
        entries.append(CatalogEntry("Committee", c.id, c.name, (c.name, *c.aliases), True))
    for t in onto.themes.values():
        entries.append(CatalogEntry("Theme", t.id, t.name, (t.name, *t.synonyms), False))
    for c in onto.concepts.values():
        entries.append(CatalogEntry("Concept", c.id, c.name, (c.name, *c.synonyms), False, theme_id=c.theme_id))
    catalog = Catalog(entries)
    catalog.emails = {addr: catalog.by_id[pid] for addr, pid in emails.items()}
    return catalog
