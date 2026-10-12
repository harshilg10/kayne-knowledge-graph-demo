"""The semantic model and the identity catalog (no Neo4j needed)."""
from __future__ import annotations

from kgdemo.catalog import load_catalog, normalize_text
from kgdemo.ontology import load_ontology

HERO = ("Investment Committee Meeting\n\nDate: 2026-01-15\n\nParticipants:\nDouglas Whitfield\nMeredith Calloway\n\n"
        "Discussion:\nWe remain bullish on Nvidia and other AI infrastructure providers.\n"
        "The technology team believes demand for GPU capacity will continue through 2027.\n")


def test_ontology_has_the_brief_entities_and_relationships():
    onto = load_ontology()
    for label in ["Person", "Company", "Fund", "Theme", "Document", "Meeting", "Account", "Client"]:
        assert label in onto.entities
    assert onto.allows("ATTENDED", "Person", "Meeting")
    assert onto.allows("DISCUSSED", "Meeting", "Theme")
    assert onto.allows("MENTIONS", "Document", "Company")
    assert onto.allows("OWNS", "Client", "Fund")
    assert onto.allows("INVESTED_IN", "Fund", "Company")
    assert onto.allows("ADVISED_BY", "Client", "Advisor")
    assert not onto.allows("ATTENDED", "Company", "Meeting")
    assert not onto.allows("MENTIONS", "Document", "Committee")


def test_ontology_counts():
    onto = load_ontology()
    assert len(onto.themes) == 10
    assert len(onto.concepts) == 45
    assert onto.theme_for_concept("CON-GPU").name == "AI Infrastructure"
    assert onto.committees["COM-IC"].charter.endswith("commitments.")


def test_hero_note_matches_the_expected_entities():
    cat = load_catalog()
    found = {(m.entry.label, m.entry.name) for m in cat.find(HERO)}
    assert found == {("Committee", "Investment Committee"), ("Person", "Douglas Whitfield"), ("Person", "Meredith Calloway"),
                     ("Company", "Nvidia"), ("Theme", "AI Infrastructure"), ("Concept", "GPU Capacity")}


def test_longest_match_and_case_rules():
    cat = load_catalog()
    found = [(m.entry.label, m.entry.name, m.surface) for m in cat.find(
        "We added to the AI Infrastructure Fund. A 5 micron feature. Micron and Meta Platforms. Metal prices.")]
    assert ("Fund", "Arbor Peak AI Infrastructure Fund", "AI Infrastructure Fund") in found
    assert not any(label == "Theme" for label, _, _ in found)
    assert ("Company", "Micron", "Micron") in found
    assert ("Company", "Meta", "Meta Platforms") in found
    assert sum(1 for _, name, _ in found if name == "Micron") == 1
    assert not any(surface == "Metal" for _, _, surface in found)


def test_decision_ids_beat_committee_alias():
    cat = load_catalog()
    found = [(m.entry.label, m.surface) for m in cat.find("The IC approved IC-2026-004 on Thursday.")]
    assert found == [("Committee", "IC"), ("Decision", "IC-2026-004")]


def test_names_split_across_lines_and_typography():
    cat = load_catalog()
    text = normalize_text("Meredith\nCalloway met Dr. Leah Goldberg — Pemberton Grid Consulting’s lead.")
    names = {m.entry.name for m in cat.find(text)}
    assert {"Meredith Calloway", "Leah Goldberg", "Pemberton Grid Consulting"} <= names


def test_lookup_is_identity_resolution():
    cat = load_catalog()
    assert cat.lookup("NVDA").name == "Nvidia"
    assert cat.lookup("Taiwan Semiconductor").name == "TSMC"
    assert cat.lookup("gpu capacity").name == "GPU Capacity"
    assert cat.lookup("PCF II").name == "Arbor Peak Private Credit Fund II"
    assert cat.lookup("Nobody Inc") is None
