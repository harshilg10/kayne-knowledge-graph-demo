"""Loads the semantic model (ontology/semantic_model.yaml) into typed objects."""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from .config import ONTOLOGY_PATH


@dataclass(frozen=True)
class EntityType:
    label: str
    display_name: str
    description: str
    key: str
    caption: str
    properties: tuple[str, ...]
    sources: tuple[str, ...]
    extractable: bool
    is_a: str | None = None
    technical: bool = False


@dataclass(frozen=True)
class RelType:
    type: str
    from_labels: tuple[str, ...]
    to_labels: tuple[str, ...]
    origin: str            # structured | extracted | derived
    description: str
    technical: bool = False


@dataclass(frozen=True)
class Concept:
    id: str
    name: str
    theme_id: str
    synonyms: tuple[str, ...]


@dataclass(frozen=True)
class Theme:
    id: str
    name: str
    definition: str
    synonyms: tuple[str, ...]
    concept_ids: tuple[str, ...]


@dataclass(frozen=True)
class Committee:
    id: str
    name: str
    aliases: tuple[str, ...]
    charter: str
    meeting_types: tuple[str, ...] = ()


@dataclass
class Ontology:
    model: dict
    entities: dict[str, EntityType]
    relationships: dict[str, RelType]
    themes: dict[str, Theme]
    concepts: dict[str, Concept]
    theme_links: list[dict]
    committees: dict[str, Committee]
    rules: list[dict]
    exposure_factors: dict[str, float]
    guideline_pct: float
    sources: list[dict]
    raw: dict = field(repr=False, default_factory=dict)

    # -- helpers ---------------------------------------------------------------
    def labels(self, include_technical: bool = True) -> list[str]:
        return [l for l, e in self.entities.items() if include_technical or not e.technical]

    def rel_types(self, include_technical: bool = True) -> list[str]:
        return [t for t, r in self.relationships.items() if include_technical or not r.technical]

    def allows(self, rel_type: str, from_label: str, to_label: str) -> bool:
        """Domain/range check. An Advisor is also a Person (is_a)."""
        rel = self.relationships.get(rel_type)
        if rel is None:
            return False
        return self._fits(from_label, rel.from_labels) and self._fits(to_label, rel.to_labels)

    def _fits(self, label: str, allowed: tuple[str, ...]) -> bool:
        if label in allowed:
            return True
        parent = self.entities.get(label).is_a if label in self.entities else None
        return parent in allowed if parent else False

    def theme_for_concept(self, concept_id: str) -> Theme:
        return self.themes[self.concepts[concept_id].theme_id]

    def theme_by_name(self, name: str) -> Theme:
        for t in self.themes.values():
            if t.name.lower() == name.lower():
                return t
        raise KeyError(name)


@lru_cache(maxsize=4)
def load_ontology(path: str | Path = ONTOLOGY_PATH) -> Ontology:
    raw = yaml.safe_load(Path(path).read_text())
    entities = {}
    for e in raw["entities"]:
        entities[e["label"]] = EntityType(
            label=e["label"], display_name=e.get("display_name", e["label"]), description=e["description"],
            key=e["key"], caption=e["caption"], properties=tuple(e.get("properties", [])),
            sources=tuple(e.get("sources", [])), extractable=bool(e.get("extractable", False)),
            is_a=e.get("is_a"), technical=bool(e.get("technical", False)))
    relationships = {}
    for r in raw["relationships"]:
        if r["type"] in relationships:
            raise ValueError(f"duplicate relationship type {r['type']}")
        relationships[r["type"]] = RelType(
            type=r["type"], from_labels=tuple(r["from"]), to_labels=tuple(r["to"]), origin=r["origin"],
            description=r["description"], technical=bool(r.get("technical", False)))
    themes, concepts = {}, {}
    for t in raw["vocabulary"]["themes"]:
        cids = []
        for c in t.get("concepts", []):
            concepts[c["id"]] = Concept(id=c["id"], name=c["name"], theme_id=t["id"], synonyms=tuple(c["synonyms"]))
            cids.append(c["id"])
        themes[t["id"]] = Theme(id=t["id"], name=t["name"], definition=t["definition"],
                                synonyms=tuple(t.get("synonyms", [])), concept_ids=tuple(cids))
    committees = {c["id"]: Committee(id=c["id"], name=c["name"], aliases=tuple(c.get("aliases", [])),
                                     charter=c.get("charter", ""), meeting_types=tuple(c.get("meeting_types", [])))
                  for c in raw["vocabulary"].get("committees", [])}
    onto = Ontology(
        model=raw["model"], entities=entities, relationships=relationships, themes=themes, concepts=concepts,
        theme_links=list(raw["vocabulary"].get("theme_links", [])), committees=committees,
        rules=list(raw.get("rules", [])), exposure_factors=dict(raw["exposure_model"]["factors"]),
        guideline_pct=float(raw["exposure_model"]["guideline_pct"]), sources=list(raw.get("sources", [])), raw=raw)
    _validate(onto)
    return onto


def _validate(onto: Ontology) -> None:
    for r in onto.relationships.values():
        for label in r.from_labels + r.to_labels:
            if label not in onto.entities:
                raise ValueError(f"relationship {r.type} references unknown label {label}")
        if r.origin not in {"structured", "extracted", "derived"}:
            raise ValueError(f"relationship {r.type} has bad origin {r.origin}")
    for link in onto.theme_links:
        if link["from"] not in onto.themes or link["to"] not in onto.themes:
            raise ValueError(f"bad theme link {link}")
    seen: dict[str, str] = {}
    for t in onto.themes.values():
        for form in (t.name,) + t.synonyms:
            key = form.lower()
            if key in seen and seen[key] != t.id:
                raise ValueError(f"vocabulary form '{form}' used by {seen[key]} and {t.id}")
            seen[key] = t.id
    for c in onto.concepts.values():
        for form in (c.name,) + c.synonyms:
            key = form.lower()
            if key in seen and seen[key] != c.id:
                raise ValueError(f"vocabulary form '{form}' used by {seen[key]} and {c.id}")
            seen[key] = c.id
