"""Writes the structured "system of record" exports (CSV) from the world model.

    python -m kgdemo.generate_structured
"""
from __future__ import annotations

import csv
from pathlib import Path

from . import world as w
from .config import AS_OF_DATE, STRUCTURED_DIR


def _write(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


def _pipe(values) -> str:
    return "|".join(values or [])


def _money(x) -> str:
    return "" if x in ("", None) else f"{x:.2f}"


def _qty(x, fund_id: str) -> str:
    return "" if x in ("", None) else f"{x:.{4 if fund_id == 'FND-PC2' else 3}f}"


def _price(x, fund_id: str) -> str:
    return "" if x in ("", None) else f"{x:.4f}" if fund_id == "FND-PC2" or x < 1 else f"{x:.2f}"


def generate(out_dir: Path = STRUCTURED_DIR) -> dict[str, int]:
    people = w.people()
    employees = [p for p in people if p["person_type"] == "employee"]
    contacts = [p for p in people if p["person_type"] != "employee"]
    counts = {}

    rows = [{**p, "committees": _pipe(f"{cid}:{role}" for cid, role in p["committees"]),
             "aliases": _pipe(p["aliases"])} for p in employees]
    _write(out_dir / "people.csv", ["id", "name", "title", "department", "email", "committees", "aliases"], rows)
    counts["people.csv"] = len(rows)

    rows = [{"id": p["id"], "name": p["name"], "title": p["title"], "organization": p["organization"],
             "email": p["email"], "contact_type": p["person_type"], "client_id": p["client_id"] or "",
             "company_id": p["company_id"] or "", "aliases": _pipe(p["aliases"])} for p in contacts]
    _write(out_dir / "contacts.csv",
           ["id", "name", "title", "organization", "email", "contact_type", "client_id", "company_id", "aliases"], rows)
    counts["contacts.csv"] = len(rows)

    by_id = {p["id"]: p for p in people}
    rows = [{"person_id": a["id"], "name": by_id[a["id"]]["name"], "title": by_id[a["id"]]["title"],
             "office": a["office"], "start_date": a["start_date"]} for a in w.ADVISORS]
    _write(out_dir / "advisors.csv", ["person_id", "name", "title", "office", "start_date"], rows)
    counts["advisors.csv"] = len(rows)

    rows = [{**c, "aliases": _pipe(c["aliases"])} for c in w.CLIENTS]
    _write(out_dir / "clients.csv", ["id", "name", "client_type", "segment", "risk_profile", "client_since", "city",
                                     "advisor_id", "aliases", "notes"], rows)
    counts["clients.csv"] = len(rows)

    rows = [{**a, "commitment_usd": _money(a["commitment_usd"])} for a in w.accounts()]
    _write(out_dir / "accounts.csv", list(w.ACCOUNT_FIELDS), rows)
    counts["accounts.csv"] = len(rows)

    rows = [{**h, "shares": _qty(h["shares"], h["fund_id"]), "price": _price(h["price"], h["fund_id"]),
             "market_value": _money(h["market_value"]), "cost_basis": _money(h["cost_basis"]),
             "unrealized_gain_loss": _money(h["unrealized_gain_loss"]), "pct_of_account": f"{h['pct_of_account']:.2f}"}
            for h in w.holdings()]
    _write(out_dir / "holdings.csv", ["account_id", "fund_id", "ticker", "shares", "price", "market_value",
                                      "cost_basis", "unrealized_gain_loss", "pct_of_account", "as_of"], rows)
    counts["holdings.csv"] = len(rows)

    rows = [{**t, "trade_date": t["date"], "shares": _qty(t["shares"], t["fund_id"]),
             "price": _price(t["price"], t["fund_id"]), "amount_usd": _money(t["amount_usd"])}
            for t in w.transactions()]
    _write(out_dir / "transactions.csv", ["id", "trade_date", "settle_date", "account_id", "fund_id", "txn_type",
                                          "shares", "price", "amount_usd", "order_reason"], rows)
    counts["transactions.csv"] = len(rows)

    as_of = AS_OF_DATE.isoformat()
    rows = [{**f, "themes": _pipe(f["themes"]), "aliases": _pipe(f["aliases"]),
             "nav": _price(w.nav(f["id"], as_of), f["id"]), "nav_date": as_of} for f in w.FUNDS]
    _write(out_dir / "funds.csv", ["id", "name", "ticker", "share_class", "asset_class", "strategy", "benchmark",
                                   "inception_date", "expense_ratio_pct", "aum_usd_m", "nav", "nav_date", "pm_id",
                                   "themes", "aliases"], rows)
    counts["funds.csv"] = len(rows)

    rows = [{**r, "nav": _price(r["nav"], r["fund_id"])} for r in w.nav_history()]
    _write(out_dir / "fund_nav.csv", ["date", "fund_id", "ticker", "nav"], rows)
    counts["fund_nav.csv"] = len(rows)

    rows = [{**c, "aliases": _pipe(c["aliases"])} for c in w.companies()]
    _write(out_dir / "companies.csv", list(w.COMPANY_FIELDS), rows)
    counts["companies.csv"] = len(rows)

    rows = [{"fund_id": fid, "company_id": cid, "weight_pct": f"{weight:.2f}", "since": since, "as_of": as_of}
            for fid, positions in w.FUND_HOLDINGS.items() for cid, weight, since in positions]
    _write(out_dir / "fund_holdings.csv", ["fund_id", "company_id", "weight_pct", "since", "as_of"], rows)
    counts["fund_holdings.csv"] = len(rows)

    rows = [{"company_id": cid, "theme_id": tid, "degree": degree}
            for cid, themes in w.COMPANY_THEMES.items() for tid, degree in themes.items()]
    _write(out_dir / "company_themes.csv", ["company_id", "theme_id", "degree"], rows)
    counts["company_themes.csv"] = len(rows)

    rows = [{**d, "affects_funds": _pipe(d["affects_funds"]), "affects_companies": _pipe(d["affects_companies"]),
             "affects_themes": _pipe(d["affects_themes"])} for d in w.DECISIONS]
    _write(out_dir / "ic_decisions.csv", ["id", "date", "title", "status", "vote", "direction", "summary",
                                          "affects_funds", "affects_companies", "affects_themes"], rows)
    counts["ic_decisions.csv"] = len(rows)
    return counts


if __name__ == "__main__":
    for name, n in generate().items():
        print(f"{name:22s} {n:5d} rows")
