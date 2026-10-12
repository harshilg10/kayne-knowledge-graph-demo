"""Consistency of the world model, its exports and the document manifest (no Neo4j needed)."""
from __future__ import annotations

import csv
import re
from collections import Counter

import pytest

from kgdemo import manifest as mf
from kgdemo import world as w
from kgdemo.catalog import load_catalog
from kgdemo.config import AS_OF_DATE, HERO_DOC_ID, SOURCE_DOCS_DIR, STRUCTURED_DIR, UNSTRUCTURED_DIR

BLACKOUT = ("2025-09-01", "2025-10-31")   # no documents here (the corpus covers the IC cycle around it)


def test_master_data_is_mid_sized():
    assert len(w.people()) == 97          # 25 employees, 62 client contacts, 10 external contacts
    assert len(w.companies()) == 50
    assert len(w.FUNDS) == 10
    assert len(w.CLIENTS) == 40
    assert len(w.accounts()) == 78
    assert len(w.meetings()) == 21
    assert len(w.DECISIONS) == 8
    assert 2000 <= len(w.transactions()) <= 10000


def test_ids_and_names_are_unique():
    for rows in (w.people(), w.companies(), w.FUNDS, w.CLIENTS, w.accounts(), w.meetings(), w.DECISIONS):
        ids = [r["id"] for r in rows]
        assert len(ids) == len(set(ids))
    names = [p["name"] for p in w.people()]
    assert len(names) == len(set(names))


def test_references_resolve():
    person_ids = {p["id"] for p in w.people()}
    names = {p["name"] for p in w.people()}
    for c in w.CLIENTS:
        assert c["advisor_id"] in w.ADVISOR_IDS
    for f in w.FUNDS:
        assert f["pm_id"] in person_ids
    for m in w.meetings():
        assert set(m["participants"]) <= names, m["key"]
        for did in m["decision_ids"]:
            assert w.decision_by_id(did)["date"] == m["date"]
    company_ids = {c["id"] for c in w.companies()}
    for fid, positions in w.FUND_HOLDINGS.items():
        assert {cid for cid, _, _ in positions} <= company_ids
        assert sum(weight for _, weight, _ in positions) <= 100.0


def test_transactions_are_consistent():
    tx = w.transactions()
    assert len({t["id"] for t in tx}) == len(tx)
    accounts = {a["id"] for a in w.accounts()}
    funds = {f["id"] for f in w.FUNDS}
    known_decisions = {d["id"] for d in w.DECISIONS}
    for t in tx:
        assert t["account_id"] in accounts and t["fund_id"] in funds
        assert t["amount_usd"] > 0 and round(t["amount_usd"], 2) == t["amount_usd"]
        assert t["date"] <= AS_OF_DATE.isoformat() and w.is_business_day(t["date"]), t["id"]
        assert t["settle_date"] >= t["date"] and w.is_business_day(t["settle_date"]), t["id"]
        if t["txn_type"] in ("BUY", "SELL", "FEE", "CAPITAL_CALL"):
            assert t["price"] == w.nav(t["fund_id"], t["date"])
            assert abs(t["shares"] * t["price"] - t["amount_usd"]) <= 0.0005 * t["price"] + 0.01, t["id"]
        else:
            assert t["txn_type"] in ("INCOME", "DISTRIBUTION") and t["shares"] == "", t["id"]
        for token in t["order_reason"].replace("(", " ").replace(")", " ").split():
            if token.startswith("IC-"):
                assert token in known_decisions
    # trades implementing a decision happen on or after the decision date
    by_id = {d["id"]: d for d in w.DECISIONS}
    for t in tx:
        for did in by_id:
            if did in t["order_reason"]:
                assert t["date"] >= by_id[did]["date"], (t["id"], did)


def test_positions_never_negative():
    for d in sorted({t["date"] for t in w.transactions()}):
        for acct, positions in w.positions_at(d).items():
            for fund, value in positions.items():
                assert value >= -1e-6, (d, acct, fund, value)


def test_lookthrough_story_holds():
    flagged = set(w.FLAGGED_OVERLAP_CLIENTS)
    june_others = {}
    for c in w.CLIENTS:
        june = w.look_through_exposure(c["id"], "THM-AI", "2026-06-15")["pct"]
        after = w.look_through_exposure(c["id"], "THM-AI", "2026-08-10")["pct"]
        now = w.look_through_exposure(c["id"], "THM-AI", AS_OF_DATE.isoformat())["pct"]
        if c["id"] in flagged:
            assert june > w.EXPOSURE_GUIDELINE_PCT, c["name"]
            assert after < 13.5 and now < w.EXPOSURE_GUIDELINE_PCT, c["name"]      # "about 13%" after the trades
        else:
            june_others[c["name"]] = june
            for month in ["2025-06-30", "2025-12-31", "2026-03-31", "2026-06-15", "2026-08-10", "2026-09-15",
                          AS_OF_DATE.isoformat()]:
                assert w.look_through_exposure(c["id"], "THM-AI", month)["pct"] < w.EXPOSURE_GUIDELINE_PCT
    # the documents: "next highest is Nakamura Family Partners; all other clients are below 13%"
    assert max(june_others, key=june_others.get) == "Nakamura Family Partners"
    assert max(june_others.values()) < 13.0


def test_manifest_shape():
    specs = mf.doc_specs()
    assert len(specs) == 101
    assert Counter(s.doc_type for s in specs) == {"CRM Note": 27, "Email": 22, "Meeting Notes": 21,
                                                  "Research Report": 15, "IC Memo": 8, "Due Diligence": 8}
    ids = [s.doc_id for s in specs]
    assert len(ids) == len(set(ids))
    by_id = {s.doc_id: s for s in specs}
    for s in specs:
        assert "2025-01-01" <= s.date <= AS_OF_DATE.isoformat()
        assert not (BLACKOUT[0] <= s.date <= BLACKOUT[1])
        for c in s.cites:
            assert by_id[c].date <= s.date
        if s.decision_ref:
            assert w.decision_by_id(s.decision_ref)["date"] == s.for_meeting_date
            assert s.date <= s.for_meeting_date
    meeting_keys = [s.meeting_key for s in specs if s.meeting_key]
    assert sorted(meeting_keys) == sorted(m["key"] for m in w.meetings())


def test_must_mentions_resolve_in_catalog():
    cat = load_catalog()
    for s in mf.doc_specs():
        for m in s.must_mention:
            assert cat.lookup(m) is not None, (s.doc_id, m)


def test_hero_document_is_the_brief_example():
    hero = mf.spec_by_id(HERO_DOC_ID)
    assert hero.title == "Investment Committee Meeting"
    assert hero.date == "2026-01-15"
    assert w.meeting_by_key(hero.meeting_key)["participants"] == ["Douglas Whitfield", "Meredith Calloway"]
    assert hero.fixed_body == ("Discussion:\nWe remain bullish on Nvidia and other AI infrastructure providers.\n"
                               "The technology team believes demand for GPU capacity will continue through 2027.")


@pytest.mark.parametrize("key,expected", [("hw_jun", 15.9), ("ok_jun", 16.3), ("sh_jun", 16.5), ("nk_jun", 12.7)])
def test_quoted_exposures_are_computed_not_typed(key, expected):
    assert mf.F[key] == expected


def test_single_name_cap_holds_after_ic_2026_011():
    for fund_id in w.THEMATIC_FUNDS:
        for company_id, weight, _ in w.FUND_HOLDINGS[fund_id]:
            assert weight <= w.SINGLE_NAME_CAP_PCT, (fund_id, company_id, weight)
    # before the trim Nvidia was about 12% of the AI Infrastructure Fund, as the documents say; now just under 10%
    nvda_now = dict((c, wt) for c, wt, _ in w.FUND_HOLDINGS["FND-AIX"])["CMP-NVDA"]
    assert round(w.fund_weight("FND-AIX", "CMP-NVDA", nvda_now, "2026-06-15")) == 12
    assert round(w.fund_weight("FND-AIX", "CMP-NVDA", nvda_now, AS_OF_DATE.isoformat())) == 10
    # Nvidia is about 8% of the Global Technology Fund
    assert round(dict((c, wt) for c, wt, _ in w.FUND_HOLDINGS["FND-GTF"])["CMP-NVDA"]) == 8
    # the trim moved weight within the theme, so the fund's theme exposure did not change
    assert w.fund_theme_factor("FND-AIX", "THM-AI", "2026-06-15") == pytest.approx(w.fund_theme_factor(
        "FND-AIX", "THM-AI", AS_OF_DATE.isoformat()))


def test_capital_call_adds_about_one_point():
    for cid in w.FLAGGED_OVERLAP_CLIENTS:
        before = w.look_through_exposure(cid, "THM-AI", "2026-09-14")["pct"]
        after = w.look_through_exposure(cid, "THM-AI", "2026-09-15")["pct"]
        assert 0.5 <= after - before <= 1.5


# =============================================================================
# documents quote the simulated numbers; the data carries no synthetic tells
# =============================================================================
def _exact(x: float) -> str:
    return f"${round(x):,}"


def _about(x: float) -> str:
    return f"about ${x / 1e6:.2f} million" if x >= 1e6 else f"about ${round(x, -3):,.0f}"


def _quoted_numbers() -> list[tuple[str, str]]:
    f = mf.F
    amt = {k: v["amount_usd"] for k, v in f.items() if isinstance(v, dict)}
    pct = {k: f"{f[k]}%" for k in ("hw_jun", "ok_jun", "sh_jun", "nk_jun")}
    hw_total = amt["hw_gtf_sell_trust"] + amt["hw_gtf_sell_ira"]
    return [
        ("CRM-03", _exact(amt["hw_aix_trust"])), ("CRM-03", _exact(amt["hw_aix_ira"])),
        ("CRM-05", _about(amt["hw_gtf_sell_trust"])), ("CRM-05", _about(amt["hw_gtf_sell_ira"])),
        ("CRM-08", _about(amt["ok_aix"])), ("CRM-09", _about(amt["ok_gtf_sell"])), ("CRM-09", pct["ok_jun"]),
        ("CRM-13", _exact(amt["lq_aix_trust"])), ("CRM-13", _exact(amt["lq_aix_ira"])),
        ("CRM-15", _exact(amt["rm_eif"])), ("CRM-18", _exact(amt["nk_call6"])), ("CRM-19", _exact(amt["nk_call7"])),
        ("CRM-20", f"${amt['dg_rmd']:,.2f}"), ("CRM-22", _exact(amt["sa_aix"])),
        ("CRM-23", _exact(amt["br_aix_joint"])), ("CRM-23", _exact(amt["br_aix_ira"])),
        ("CRM-24", _exact(amt["br_eif"])), ("CRM-25", _about(amt["sh_gtf_sell"])), ("CRM-25", pct["sh_jun"]),
        ("CRM-04", _exact(amt["hw_call6"])), ("CRM-06", _exact(amt["hw_call7"])),
        ("EM-01", _about(amt["hw_eif_2025"])), ("EM-08", _about(amt["hw_aix_trust"])),
        ("EM-08", _about(amt["hw_aix_ira"])), ("EM-10", _about(amt["ok_aix"])),
        ("EM-16", f"Hartwell Family Trust: {pct['hw_jun']}"), ("EM-16", f"Okafor Family Office: {pct['ok_jun']}"),
        ("EM-16", f"Sterling-Hayes Family Office: {pct['sh_jun']}"), ("EM-16", f"Nakamura Family Partners at {pct['nk_jun']}"),
        ("EM-18", pct["hw_jun"]), ("EM-18", _about(amt["hw_gtf_sell_trust"])), ("EM-18", _about(amt["hw_gtf_sell_ira"])),
        ("EM-19", pct["hw_jun"]),
        ("ICM-07", f"Hartwell Family Trust: {pct['hw_jun']}"), ("ICM-07", f"Okafor Family Office: {pct['ok_jun']}"),
        ("ICM-07", f"Sterling-Hayes Family Office: {pct['sh_jun']}"), ("ICM-07", f"Nakamura Family Partners at {pct['nk_jun']}"),
        ("ICM-07", _about(amt["ok_gtf_sell"])), ("ICM-07", f"${hw_total / 1e6:.2f} million for the Hartwell"),
        ("ICM-07", f"${amt['sh_gtf_sell'] / 1e6:.2f} million for the Sterling-Hayes"),
        ("MN-09", f"Hartwell Family Trust {pct['hw_jun']}, Okafor Family Office {pct['ok_jun']} and Sterling-Hayes "
                  f"Family Office {pct['sh_jun']}"),
        ("MN-13", f"Hartwell Family Trust {pct['hw_jun']}, Okafor Family Office {pct['ok_jun']} and Sterling-Hayes "
                  f"Family Office {pct['sh_jun']}"), ("MN-13", f"Nakamura Family Partners at {pct['nk_jun']}"),
        ("MN-15", _about(amt["hw_aix_trust"])), ("MN-15", _exact(amt["hw_aix_ira"])),
        ("MN-16", f"${amt['hw_gtf_sell_trust'] / 1e6:.2f} million"), ("MN-16", _exact(amt["hw_gtf_sell_ira"])),
        ("MN-16", f"from {pct['hw_jun']} as of June 15 to about {f['hw_aug']}%"), ("MN-17", _about(amt["ok_aix"])),
        ("EM-06", f"{f['ic004_accounts']} accounts across {f['ic004_clients']} clients"),
        ("ICM-03", f"about {f['ic004_accounts']} accounts for {f['ic004_clients']} clients"),
        ("EM-07", f"{f['ic004_accounts']} accounts in total"),
        ("EM-14", f"about {f['ic008_accounts']} accounts and roughly {f['ic008_total']}"),
        ("ICM-06", f"about {f['ic008_accounts']} accounts and roughly {f['ic008_total']}"),
        ("EM-02", f"the {f['ic019_accounts']} Growth taxable accounts"),
        ("ICM-02", f"across {f['ic019_accounts']} Growth taxable accounts"),
    ]


@pytest.mark.parametrize("doc,expected", _quoted_numbers(), ids=lambda v: str(v)[:40])
def test_documents_quote_the_simulated_numbers(doc, expected):
    assert expected in (SOURCE_DOCS_DIR / f"DOC-{doc}.txt").read_text()


def test_ic_2026_004_total_is_quoted_rounded():
    total = sum(t["amount_usd"] for t in w.transactions()
                if "IC-2026-004" in t["order_reason"] and t["txn_type"] == "BUY")
    assert round(total / 1e6) == 10
    for doc in ("EM-06", "ICM-03"):
        assert "roughly $10 million" in (SOURCE_DOCS_DIR / f"DOC-{doc}.txt").read_text()


TELLS = re.compile(r"\.example\b|Client XYZ|John Smith|Sarah Lee|Lorem ipsum|\bTODO\b|placeholder|\bfoo\b|\bdummy\b|"
                   r"555-\d{4}|test@", re.IGNORECASE)


def test_source_data_has_no_placeholder_tells():
    paths = sorted(STRUCTURED_DIR.glob("*.csv")) + sorted(SOURCE_DOCS_DIR.glob("*.txt"))
    paths += [p for p in UNSTRUCTURED_DIR.rglob("*") if p.suffix in (".md", ".eml", ".csv")]
    assert len(paths) > 100
    for path in paths:
        hits = TELLS.findall(path.read_text(encoding="utf-8"))
        assert not hits, (path.name, hits[:3])


def test_amounts_look_like_real_bookkeeping():
    with (STRUCTURED_DIR / "transactions.csv").open(newline="") as fh:
        amounts = [float(r["amount_usd"]) for r in csv.DictReader(fh)]
    round_10k = sum(1 for a in amounts if a % 10000 == 0)
    with_cents = sum(1 for a in amounts if round(a * 100) % 100)
    assert round_10k / len(amounts) < 0.01          # only client-specified amounts (grants, capital calls) are round
    assert with_cents / len(amounts) > 0.9
    with (STRUCTURED_DIR / "holdings.csv").open(newline="") as fh:
        values = [float(r["market_value"]) for r in csv.DictReader(fh)]
    assert all(v % 1000 for v in values)
