"""The "world" behind the demo: one consistent book of business for a mid-sized wealth manager.

The firm (Arbor Peak Wealth Partners), its people, clients, accounts, funds and private borrowers are
fictional; listed companies are real and appear only as fund holdings and research subjects.

This module is the single source of truth for:
  * master data (people, clients, advisors, accounts, funds, companies)
  * pricing (a daily NAV series per fund, with distributions)
  * the investment story (IC decisions, meetings) and every account flow (trades, income, fees,
    contributions, withdrawals, capital calls), replayed in shares so holdings, trades and
    point-in-time look-through exposure always reconcile
  * look-through exposure arithmetic (keeps documents and data consistent)

`generate_structured.py` turns it into CSV exports; the document manifest (`manifest.py`) computes the
numbers quoted in documents from it.
"""
from __future__ import annotations

import math
import random
import re
import zlib
from bisect import bisect_right
from datetime import date, timedelta

from .config import AS_OF_DATE, FIRM_EMAIL_DOMAIN, FIRM_NAME
from .models import meeting_id  # noqa: F401  (shared rule with the extractor)


def _email(name: str, domain: str) -> str:
    first, last = name.lower().split(" ", 1)
    return f"{re.sub(r'[^a-z]', '', first)}.{re.sub(r'[^a-z]', '', last)}@{domain}"


def _seed(*parts: str) -> int:
    return zlib.crc32("|".join(parts).encode())


# =============================================================================
# PEOPLE
# =============================================================================
_EMPLOYEES = [
    # id, name, title, department, committees [(committee_id, role)]
    ("PER-001", "Douglas Whitfield", "Chief Investment Officer", "Investment Office", [("COM-IC", "Chair"), ("COM-RISK", "Member")]),
    ("PER-002", "Meredith Calloway", "Head of Technology Research", "Research", [("COM-IC", "Member")]),
    ("PER-003", "Brendan Kessler", "Portfolio Manager, AI Infrastructure Fund", "Portfolio Management", [("COM-IC", "Member")]),
    ("PER-004", "Rebecca Thornton", "Portfolio Manager, Energy Infrastructure Fund", "Portfolio Management", [("COM-IC", "Member")]),
    ("PER-005", "Marcus Bell", "Head of Private Credit", "Private Credit", [("COM-IC", "Member")]),
    ("PER-006", "Elena Vasquez", "Chief Risk Officer", "Risk", [("COM-IC", "Member"), ("COM-RISK", "Chair")]),
    ("PER-007", "Philip Ashworth", "Head of Wealth Management", "Wealth Management", [("COM-IC", "Member"), ("COM-RISK", "Member")]),
    ("PER-008", "Olivia Grant", "Portfolio Manager, Global Technology Fund", "Portfolio Management", []),
    ("PER-009", "Arjun Mehta", "Senior Analyst, Semiconductors", "Research", []),
    ("PER-010", "Natalie Brooks", "Power & Utilities Analyst; Portfolio Manager, Clean Energy Transition Fund", "Research", []),
    ("PER-011", "Wade Pruitt", "Senior Analyst, Midstream Energy", "Research", []),
    ("PER-012", "Priya Nair", "Vice President, Private Credit Underwriting", "Private Credit", []),
    ("PER-013", "Daniel Cho", "Portfolio Manager, Cybersecurity Leaders Fund", "Portfolio Management", []),
    ("PER-014", "Hannah Schultz", "Portfolio Manager, Healthcare Innovation Fund", "Portfolio Management", []),
    ("PER-015", "Stephen Albrecht", "Portfolio Manager, Fixed Income", "Portfolio Management", []),
    ("PER-016", "Lucas Meyer", "Senior Risk Analyst", "Risk", [("COM-RISK", "Member")]),
    ("PER-017", "Grace Holloway", "Chief Compliance Officer", "Compliance", [("COM-RISK", "Member")]),
    ("PER-018", "Michael Torres", "Senior Wealth Advisor", "Wealth Management", []),
    ("PER-019", "Jennifer Walsh", "Senior Wealth Advisor", "Wealth Management", []),
    ("PER-020", "Andre Washington", "Wealth Advisor", "Wealth Management", []),
    ("PER-021", "Laura Chen", "Wealth Advisor", "Wealth Management", []),
    ("PER-022", "Victor Alvarez", "Wealth Advisor", "Wealth Management", []),
    ("PER-023", "Lauren Pacheco", "Associate Wealth Advisor", "Wealth Management", []),
    ("PER-024", "Trevor Iwasaki", "Head of Trading", "Operations", []),
    ("PER-025", "Courtney Bianchi", "Client Service Associate", "Wealth Management", []),
]

_CLIENT_CONTACTS = [
    # id, name, title/role, client_id, email domain
    ("PER-026", "Robert Hartwell", "Trustee", "C-001", "hartwellfamily.com"),
    ("PER-027", "Elaine Hartwell", "Co-Trustee", "C-001", "hartwellfamily.com"),
    ("PER-028", "Chinedu Okafor", "Principal", "C-002", "okaforfo.com"),
    ("PER-029", "Ngozi Okafor", "Chief Financial Officer", "C-002", "okaforfo.com"),
    ("PER-030", "Margaret Bellamy", "Executive Director", "C-003", "bellamyfoundation.org"),
    ("PER-031", "Erik Lindqvist", "Grantor and Trustee", "C-004", "lindqvistfamily.com"),
    ("PER-032", "Carlos Ramirez", "Primary Client", "C-005", "ramirezfamily.com"),
    ("PER-033", "Sofia Ramirez", "Co-Client", "C-005", "ramirezfamily.com"),
    ("PER-034", "Diane Whitman", "President", "C-006", "whitmanfoundation.org"),
    ("PER-035", "Kenji Nakamura", "Managing Partner", "C-007", "nakamurapartners.com"),
    ("PER-036", "Maria Delgado", "Trustee", "C-008", "delgadofamily.com"),
    ("PER-037", "Helen Marsh", "Chief Financial Officer", "C-009", "staldric.org"),
    ("PER-038", "Patrick Brennan", "Primary Client", "C-010", "brennanfamily.com"),
    ("PER-039", "Caroline Sterling-Hayes", "Principal", "C-011", "sterlinghayes.com"),
    ("PER-040", "Irina Volkov", "Primary Client", "C-012", "volkovfamily.com"),
    ("PER-051", "William Prescott", "Primary Client", "C-013", "prescottfamily.com"),
    ("PER-052", "Anne Prescott", "Co-Client", "C-013", "prescottfamily.com"),
    ("PER-053", "Harold Whitcomb", "Trustee", "C-014", "whitcombtrust.com"),
    ("PER-054", "Judith Whitcomb", "Co-Trustee", "C-014", "whitcombtrust.com"),
    ("PER-055", "Folake Adeyemi", "Primary Client", "C-015", "adeyemifamily.com"),
    ("PER-056", "Tunde Adeyemi", "Co-Client", "C-015", "adeyemifamily.com"),
    ("PER-057", "Marc Thibodeaux", "Primary Client", "C-016", "thibodeauxfamily.com"),
    ("PER-058", "Celeste Thibodeaux", "Co-Client", "C-016", "thibodeauxfamily.com"),
    ("PER-059", "Rosa Garza", "Executive Director", "C-017", "garzafoundation.org"),
    ("PER-060", "Vikram Raghavan", "Primary Client", "C-018", "raghavanfamily.com"),
    ("PER-061", "Anjali Raghavan", "Co-Client", "C-018", "raghavanfamily.com"),
    ("PER-062", "Jerzy Kowalczyk", "Primary Client", "C-019", "kowalczykfamily.com"),
    ("PER-063", "Ewa Kowalczyk", "Co-Client", "C-019", "kowalczykfamily.com"),
    ("PER-064", "Lionel Fairbanks", "Trustee", "C-020", "fairbankstrust.org"),
    ("PER-065", "Darnell Odum", "Primary Client", "C-021", "odumfamily.com"),
    ("PER-066", "Keisha Odum", "Co-Client", "C-021", "odumfamily.com"),
    ("PER-067", "Hiroshi Takahashi", "Primary Client", "C-022", "takahashifamily.com"),
    ("PER-068", "Emily Takahashi", "Co-Client", "C-022", "takahashifamily.com"),
    ("PER-069", "Nils Bergstrom", "Trustee", "C-023", "bergstromfamily.com"),
    ("PER-070", "Karin Bergstrom", "Co-Trustee", "C-023", "bergstromfamily.com"),
    ("PER-071", "Ruth Weiss", "President", "C-024", "weissfoundation.org"),
    ("PER-072", "Ernesto Villarreal", "Primary Client", "C-025", "villarrealfamily.com"),
    ("PER-073", "Gloria Villarreal", "Co-Client", "C-025", "villarrealfamily.com"),
    ("PER-074", "Sean Kerrigan", "Trustee", "C-026", "kerrigantrust.com"),
    ("PER-075", "Colleen Kerrigan", "Co-Trustee", "C-026", "kerrigantrust.com"),
    ("PER-076", "Adrian Castellanos", "Primary Client", "C-027", "castellanosfamily.com"),
    ("PER-077", "Mariana Castellanos", "Co-Client", "C-027", "castellanosfamily.com"),
    ("PER-078", "Anders Lindahl", "Primary Client", "C-028", "lindahlfamily.com"),
    ("PER-079", "Kristin Lindahl", "Co-Client", "C-028", "lindahlfamily.com"),
    ("PER-080", "Lars Haugen", "Primary Client", "C-029", "haugenfamily.com"),
    ("PER-081", "Ingrid Haugen", "Co-Client", "C-029", "haugenfamily.com"),
    ("PER-082", "Dana Feldman", "Treasurer", "C-030", "cascadewetlands.org"),
    ("PER-083", "Clayton Montgomery", "Primary Client", "C-031", "montgomeryfamily.com"),
    ("PER-084", "Beverly Montgomery", "Co-Client", "C-031", "montgomeryfamily.com"),
    ("PER-085", "Anthony Ferraro", "Managing Partner", "C-032", "ferraropartners.com"),
    ("PER-086", "Simone Delacroix", "Primary Client", "C-033", "delacroixfamily.com"),
    ("PER-087", "Peter Varga", "Primary Client", "C-034", "vargafamily.com"),
    ("PER-088", "Julia Varga", "Co-Client", "C-034", "vargafamily.com"),
    ("PER-089", "Mark Sorensen", "Trustee", "C-035", "sorensentrust.com"),
    ("PER-090", "Luis Medina", "Primary Client", "C-036", "medinafamily.com"),
    ("PER-091", "Teresa Medina", "Co-Client", "C-036", "medinafamily.com"),
    ("PER-092", "Gordon Pike", "Chief Financial Officer", "C-037", "holliscreek.org"),
    ("PER-093", "Farhan Rahman", "Primary Client", "C-038", "rahmanfamily.com"),
    ("PER-094", "Nadia Rahman", "Co-Client", "C-038", "rahmanfamily.com"),
    ("PER-095", "Walter Brandt", "Grantor and Trustee", "C-039", "brandttrust.com"),
    ("PER-096", "Jonah Kaplan", "Primary Client", "C-040", "kaplanreyes.com"),
    ("PER-097", "Isabel Reyes", "Co-Client", "C-040", "kaplanreyes.com"),
]

_EXTERNAL_CONTACTS = [
    # id, name, title, company_id, email domain, aliases
    ("PER-041", "Leah Goldberg", "Managing Director", "CMP-PEMBERTON", "pembertongrid.com", ["Dr. Leah Goldberg"]),
    ("PER-042", "Owen Fitzgerald", "Chief Executive Officer", "CMP-COBALT", "cobaltridgedc.com", []),
    ("PER-043", "Alicia Moreno", "Chief Financial Officer", "CMP-COBALT", "cobaltridgedc.com", []),
    ("PER-044", "Henrik Larsen", "Chief Executive Officer", "CMP-POLARLOOP", "polarloopcooling.com", []),
    ("PER-045", "Janet Pryor", "Chief Financial Officer", "CMP-OSTRANDER", "ostranderpower.com", []),
    ("PER-046", "Sophie Laurent", "Chief Executive Officer", "CMP-LARKSPUR", "larkspurfiber.com", []),
    ("PER-047", "Ray Dawson", "Chief Executive Officer", "CMP-MESQUITE", "mesquitedraw.com", []),
    ("PER-048", "Nina Castillo", "Chief Financial Officer", "CMP-HARBORLIGHT", "harborlighthealth.com", []),
    ("PER-049", "George Abernathy", "Partner", "CMP-CALDWELL", "caldwellpierce.com", []),
    ("PER-050", "Paul Whitaker", "Chief Financial Officer", "CMP-CORBEL", "corbellogistics.com", []),
]

ADVISORS = [
    # person_id, office, start_date
    {"id": "PER-018", "office": "Dallas", "start_date": "2011-06-01"},
    {"id": "PER-019", "office": "Houston", "start_date": "2013-09-16"},
    {"id": "PER-020", "office": "Chicago", "start_date": "2016-01-11"},
    {"id": "PER-021", "office": "Los Angeles", "start_date": "2015-03-02"},
    {"id": "PER-022", "office": "San Antonio", "start_date": "2018-08-20"},
    {"id": "PER-023", "office": "Seattle", "start_date": "2022-02-07"},
]
ADVISOR_IDS = {a["id"] for a in ADVISORS}

_PEOPLE_CACHE: list[dict] | None = None


def people() -> list[dict]:
    global _PEOPLE_CACHE
    if _PEOPLE_CACHE is None:
        out = []
        for pid, name, title, dept, committees in _EMPLOYEES:
            out.append({
                "id": pid, "name": name, "title": title, "department": dept,
                "person_type": "employee", "organization": FIRM_NAME,
                "email": _email(name, FIRM_EMAIL_DOMAIN), "aliases": [],
                "committees": committees, "client_id": None, "company_id": None,
                "is_advisor": pid in ADVISOR_IDS,
            })
        for pid, name, title, client_id, domain in _CLIENT_CONTACTS:
            out.append({
                "id": pid, "name": name, "title": title, "department": "",
                "person_type": "client_contact", "organization": client_by_id(client_id)["name"],
                "email": _email(name, domain), "aliases": [], "committees": [],
                "client_id": client_id, "company_id": None, "is_advisor": False,
            })
        for pid, name, title, company_id, domain, aliases in _EXTERNAL_CONTACTS:
            out.append({
                "id": pid, "name": name, "title": title, "department": "",
                "person_type": "external", "organization": company_by_id(company_id)["name"],
                "email": _email(name, domain), "aliases": aliases, "committees": [],
                "client_id": None, "company_id": company_id, "is_advisor": False,
            })
        _PEOPLE_CACHE = sorted(out, key=lambda p: p["id"])
    return [dict(p) for p in _PEOPLE_CACHE]


def person_by_name(name: str) -> dict:
    for p in people():
        if p["name"] == name:
            return p
    raise KeyError(name)


def person_by_id(pid: str) -> dict:
    for p in people():
        if p["id"] == pid:
            return p
    raise KeyError(pid)


# =============================================================================
# CLIENTS
# =============================================================================
def _client(cid, name, client_type, segment, risk, since, city, advisor, aliases=(), notes=""):
    return {"id": cid, "name": name, "client_type": client_type, "segment": segment, "risk_profile": risk,
            "client_since": since, "city": city, "advisor_id": advisor, "aliases": list(aliases), "notes": notes}


CLIENTS = [
    _client("C-001", "Hartwell Family Trust", "Trust", "UHNW", "Growth", "2014-05-12", "Dallas, TX", "PER-018",
            ["Hartwell family", "Hartwell Trust", "Hartwell trust"],
            "Trustees Robert and Elaine Hartwell. Client-directed technology overweight since 2023. Sensitive to "
            "single-stock concentration. PCF II commitment $7.0M."),
    _client("C-002", "Okafor Family Office", "Family Office", "UHNW", "Growth", "2018-03-05", "Houston, TX", "PER-019",
            ["Okafor family", "Okafor office"],
            "Client-directed technology overweight since 2023. Interested in private credit. PCF II commitment $9.0M."),
    _client("C-003", "Bellamy Foundation", "Foundation", "Institutional", "Balanced", "2016-09-01", "Chicago, IL",
            "PER-020", [], "Investment policy statement excludes fossil-fuel infrastructure (midstream and "
            "pipelines). Grants paid semiannually (June, December)."),
    _client("C-004", "Lindqvist Revocable Trust", "Trust", "HNW", "Balanced", "2019-01-15", "Minneapolis, MN", "PER-021",
            ["Lindqvist Trust", "Lindqvist trust"], "Erik Lindqvist takes annual RMD from his IRA in December."),
    _client("C-005", "Ramirez Household", "Household", "HNW", "Balanced", "2020-06-01", "San Antonio, TX", "PER-022",
            ["Ramirez family"], "Funding daughter's university tuition from the joint account each August."),
    _client("C-006", "Whitman Charitable Foundation", "Foundation", "Institutional", "Conservative", "2015-04-20",
            "Denver, CO", "PER-020", ["Whitman Foundation"], "Annual grant distribution each February."),
    _client("C-007", "Nakamura Family Partners", "Family Partnership", "UHNW", "Growth", "2017-11-02",
            "Los Angeles, CA", "PER-021", ["Nakamura family"], "Growth model. PCF II commitment $3.0M."),
    _client("C-008", "Delgado Family Trust", "Trust", "HNW", "Conservative", "2021-02-10", "Phoenix, AZ", "PER-022",
            ["Delgado Trust", "Delgado trust"], "Income-focused; monthly withdrawal of $9,000 from the trust. "
            "Bond income paid to cash."),
    _client("C-009", "St. Aldric School Endowment", "Endowment", "Institutional", "Balanced", "2013-08-30",
            "Boston, MA", "PER-019", ["St. Aldric Endowment", "St. Aldric endowment"],
            "5% annual spending policy, drawn quarterly."),
    _client("C-010", "Brennan Household", "Household", "HNW", "Growth", "2022-03-14", "Austin, TX", "PER-018",
            ["Brennan family"], "Quarterly contribution of $10,000 to the joint account."),
    _client("C-011", "Sterling-Hayes Family Office", "Family Office", "UHNW", "Growth", "2019-07-08", "New York, NY",
            "PER-018", ["Sterling-Hayes family", "Sterling-Hayes office"],
            "Client-directed technology overweight since 2023. PCF II commitment $8.0M."),
    _client("C-012", "Volkov Household", "Household", "HNW", "Conservative", "2023-05-22", "Seattle, WA", "PER-023",
            ["Volkov family"], "Monthly withdrawal of $3,500 from the individual account."),
    _client("C-013", "Prescott Household", "Household", "HNW", "Growth", "2016-10-03", "Dallas, TX", "PER-018",
            ["Prescott family"], "Quarterly contribution of $15,000 to the joint account; Anne funds her Roth IRA "
            "each April."),
    _client("C-014", "Whitcomb Family Trust", "Trust", "UHNW", "Balanced", "2012-03-19", "University Park, TX",
            "PER-018", ["Whitcomb Trust"], "Monthly trust distribution of $25,000. Harold Whitcomb takes his RMD "
            "in December."),
    _client("C-015", "Adeyemi Household", "Household", "HNW", "Growth", "2021-08-09", "Plano, TX", "PER-018",
            ["Adeyemi family"], "Quarterly contribution of $20,000 to the joint account."),
    _client("C-016", "Thibodeaux Household", "Household", "HNW", "Balanced", "2017-05-22", "Houston, TX", "PER-019",
            ["Thibodeaux family"], ""),
    _client("C-017", "Garza Family Foundation", "Foundation", "Institutional", "Balanced", "2014-11-10",
            "Houston, TX", "PER-019", ["Garza Foundation"], "Grants paid semiannually (May, November)."),
    _client("C-018", "Raghavan Household", "Household", "HNW", "Growth", "2020-02-03", "Sugar Land, TX", "PER-019",
            ["Raghavan family"], "Quarterly contribution of $15,000 to the joint account."),
    _client("C-019", "Kowalczyk Household", "Household", "HNW", "Balanced", "2018-09-17", "Evanston, IL", "PER-020",
            ["Kowalczyk family"], ""),
    _client("C-020", "Fairbanks Charitable Trust", "Trust", "Institutional", "Conservative", "2011-04-04",
            "Chicago, IL", "PER-020", [], "5% annual unitrust payout in December."),
    _client("C-021", "Odum Household", "Household", "HNW", "Growth", "2022-06-13", "Oak Park, IL", "PER-020",
            ["Odum family"], "Quarterly contribution of $12,000 to the joint account; Keisha funds her Roth IRA "
            "each April."),
    _client("C-022", "Takahashi Household", "Household", "HNW", "Balanced", "2015-07-27", "Pasadena, CA", "PER-021",
            ["Takahashi family"], ""),
    _client("C-023", "Bergstrom Family Trust", "Trust", "UHNW", "Growth", "2013-02-25", "Santa Monica, CA",
            "PER-021", ["Bergstrom Trust"], "Growth model at target weights."),
    _client("C-024", "Weiss Family Foundation", "Foundation", "Institutional", "Balanced", "2016-01-19",
            "Los Angeles, CA", "PER-021", ["Weiss Foundation"], "Quarterly grant draws of $125,000."),
    _client("C-025", "Villarreal Household", "Household", "HNW", "Conservative", "2019-10-07", "San Antonio, TX",
            "PER-022", ["Villarreal family"], "Retired; monthly withdrawal of $6,500. Ernesto takes his RMD in "
            "December. Bond income paid to cash."),
    _client("C-026", "Kerrigan Family Trust", "Trust", "HNW", "Balanced", "2018-04-16", "Boerne, TX", "PER-022",
            ["Kerrigan Trust"], ""),
    _client("C-027", "Castellanos Household", "Household", "HNW", "Growth", "2023-01-23", "San Antonio, TX",
            "PER-022", ["Castellanos family"], "Quarterly contribution of $10,000 to the joint account."),
    _client("C-028", "Lindahl Household", "Household", "HNW", "Growth", "2021-11-01", "Bellevue, WA", "PER-023",
            ["Lindahl family"], "Quarterly contribution of $25,000 to the joint account."),
    _client("C-029", "Haugen Household", "Household", "HNW", "Balanced", "2019-03-11", "Seattle, WA", "PER-023",
            ["Haugen family"], ""),
    _client("C-030", "Cascade Wetlands Conservancy", "Endowment", "Institutional", "Conservative", "2020-09-14",
            "Tacoma, WA", "PER-023", [], "Annual operating draw of $150,000 each March."),
    _client("C-031", "Montgomery Household", "Household", "HNW", "Conservative", "2011-09-12", "Dallas, TX",
            "PER-018", ["Montgomery family"], "Retired; monthly withdrawal of $12,500. Clayton and Beverly take "
            "RMDs in December. Bond income paid to cash."),
    _client("C-032", "Ferraro Family Partners", "Family Partnership", "UHNW", "Growth", "2016-06-06", "Houston, TX",
            "PER-019", ["Ferraro family"], ""),
    _client("C-033", "Delacroix Household", "Household", "HNW", "Balanced", "2019-05-20", "Chicago, IL", "PER-020",
            [], ""),
    _client("C-034", "Varga Household", "Household", "HNW", "Growth", "2022-10-24", "Irvine, CA", "PER-021",
            ["Varga family"], "Quarterly contribution of $9,000 to the joint account."),
    _client("C-035", "Sorensen Family Trust", "Trust", "UHNW", "Balanced", "2017-08-28", "Seattle, WA", "PER-023",
            ["Sorensen Trust"], ""),
    _client("C-036", "Medina Household", "Household", "HNW", "Balanced", "2021-04-12", "San Antonio, TX", "PER-022",
            ["Medina family"], ""),
    _client("C-037", "Hollis Creek Day School Endowment", "Endowment", "Institutional", "Balanced", "2015-09-08",
            "Fort Worth, TX", "PER-018", ["Hollis Creek Endowment"], "4.5% annual spending policy, drawn quarterly."),
    _client("C-038", "Rahman Household", "Household", "HNW", "Growth", "2023-09-18", "Houston, TX", "PER-019",
            ["Rahman family"], "Quarterly contribution of $18,000 to the joint account."),
    _client("C-039", "Brandt Revocable Trust", "Trust", "HNW", "Conservative", "2014-12-01", "Naperville, IL",
            "PER-020", ["Brandt Trust"], "Monthly withdrawal of $7,500 from the trust. Walter Brandt takes his RMD "
            "in December. Bond income paid to cash."),
    _client("C-040", "Kaplan-Reyes Household", "Household", "HNW", "Balanced", "2020-11-16", "Los Angeles, CA",
            "PER-021", [], "Isabel funds her Roth IRA each April."),
]
_CLIENT_INDEX = {c["id"]: c for c in CLIENTS}


def client_by_id(cid: str) -> dict:
    if cid in _CLIENT_INDEX:
        return _CLIENT_INDEX[cid]
    raise KeyError(cid)


def client_by_name(name: str) -> dict:
    for c in CLIENTS:
        if c["name"] == name:
            return c
    raise KeyError(name)


# =============================================================================
# COMPANIES (security master + private deal register + vendor register)
# =============================================================================
# id, name, legal_name, ticker, kind, sector, industry, country, aliases
COMPANIES = [
    ("CMP-NVDA", "Nvidia", "NVIDIA Corporation", "NVDA", "public", "Information Technology", "Semiconductors", "US", ["NVIDIA", "NVIDIA Corporation", "NVDA"]),
    ("CMP-AMD", "AMD", "Advanced Micro Devices, Inc.", "AMD", "public", "Information Technology", "Semiconductors", "US", ["Advanced Micro Devices"]),
    ("CMP-AVGO", "Broadcom", "Broadcom Inc.", "AVGO", "public", "Information Technology", "Semiconductors", "US", ["AVGO"]),
    ("CMP-TSM", "TSMC", "Taiwan Semiconductor Manufacturing Company Limited", "TSM", "public", "Information Technology", "Semiconductors", "TW", ["Taiwan Semiconductor", "Taiwan Semiconductor Manufacturing"]),
    ("CMP-MU", "Micron", "Micron Technology, Inc.", "MU", "public", "Information Technology", "Semiconductors", "US", ["Micron Technology"]),
    ("CMP-ANET", "Arista Networks", "Arista Networks, Inc.", "ANET", "public", "Information Technology", "Communications Equipment", "US", ["Arista", "ANET"]),
    ("CMP-MRVL", "Marvell", "Marvell Technology, Inc.", "MRVL", "public", "Information Technology", "Semiconductors", "US", ["Marvell Technology", "MRVL"]),
    ("CMP-ASML", "ASML", "ASML Holding N.V.", "ASML", "public", "Information Technology", "Semiconductor Equipment", "NL", ["ASML Holding"]),
    ("CMP-AMAT", "Applied Materials", "Applied Materials, Inc.", "AMAT", "public", "Information Technology", "Semiconductor Equipment", "US", ["AMAT"]),
    ("CMP-VRT", "Vertiv", "Vertiv Holdings Co", "VRT", "public", "Industrials", "Electrical Equipment", "US", ["Vertiv Holdings"]),
    ("CMP-ETN", "Eaton", "Eaton Corporation plc", "ETN", "public", "Industrials", "Electrical Equipment", "IE", ["Eaton Corporation"]),
    ("CMP-DELL", "Dell Technologies", "Dell Technologies Inc.", "DELL", "public", "Information Technology", "Technology Hardware", "US", ["Dell"]),
    ("CMP-MSFT", "Microsoft", "Microsoft Corporation", "MSFT", "public", "Information Technology", "Software", "US", ["MSFT"]),
    ("CMP-GOOGL", "Alphabet", "Alphabet Inc.", "GOOGL", "public", "Communication Services", "Interactive Media", "US", ["Google", "GOOGL"]),
    ("CMP-AMZN", "Amazon", "Amazon.com, Inc.", "AMZN", "public", "Consumer Discretionary", "Broadline Retail", "US", ["Amazon.com", "Amazon Web Services", "AWS", "AMZN"]),
    ("CMP-META", "Meta", "Meta Platforms, Inc.", "META", "public", "Communication Services", "Interactive Media", "US", ["Meta Platforms", "META"]),
    ("CMP-ORCL", "Oracle", "Oracle Corporation", "ORCL", "public", "Information Technology", "Software", "US", ["ORCL"]),
    ("CMP-EQIX", "Equinix", "Equinix, Inc.", "EQIX", "public", "Real Estate", "Data Center REITs", "US", ["EQIX"]),
    ("CMP-DLR", "Digital Realty", "Digital Realty Trust, Inc.", "DLR", "public", "Real Estate", "Data Center REITs", "US", ["Digital Realty Trust"]),
    ("CMP-AMT", "American Tower", "American Tower Corporation", "AMT", "public", "Real Estate", "Telecom Tower REITs", "US", []),
    ("CMP-CEG", "Constellation Energy", "Constellation Energy Corporation", "CEG", "public", "Utilities", "Electric Utilities", "US", ["Constellation", "CEG"]),
    ("CMP-VST", "Vistra", "Vistra Corp.", "VST", "public", "Utilities", "Independent Power Producers", "US", ["Vistra Corp"]),
    ("CMP-NEE", "NextEra Energy", "NextEra Energy, Inc.", "NEE", "public", "Utilities", "Electric Utilities", "US", ["NextEra"]),
    ("CMP-GEV", "GE Vernova", "GE Vernova Inc.", "GEV", "public", "Industrials", "Electrical Equipment", "US", ["Vernova"]),
    ("CMP-PWR", "Quanta Services", "Quanta Services, Inc.", "PWR", "public", "Industrials", "Construction & Engineering", "US", ["Quanta"]),
    ("CMP-WMB", "Williams Companies", "The Williams Companies, Inc.", "WMB", "public", "Energy", "Oil & Gas Midstream", "US", ["The Williams Companies", "WMB"]),
    ("CMP-KMI", "Kinder Morgan", "Kinder Morgan, Inc.", "KMI", "public", "Energy", "Oil & Gas Midstream", "US", ["KMI"]),
    ("CMP-ET", "Energy Transfer", "Energy Transfer LP", "ET", "public", "Energy", "Oil & Gas Midstream", "US", ["Energy Transfer LP"]),
    ("CMP-EPD", "Enterprise Products Partners", "Enterprise Products Partners L.P.", "EPD", "public", "Energy", "Oil & Gas Midstream", "US", ["Enterprise Products", "EPD"]),
    ("CMP-LNG", "Cheniere Energy", "Cheniere Energy, Inc.", "LNG", "public", "Energy", "Oil & Gas Midstream", "US", ["Cheniere"]),
    ("CMP-TRGP", "Targa Resources", "Targa Resources Corp.", "TRGP", "public", "Energy", "Oil & Gas Midstream", "US", ["Targa", "TRGP"]),
    ("CMP-CRWD", "CrowdStrike", "CrowdStrike Holdings, Inc.", "CRWD", "public", "Information Technology", "Software", "US", ["CRWD"]),
    ("CMP-PANW", "Palo Alto Networks", "Palo Alto Networks, Inc.", "PANW", "public", "Information Technology", "Software", "US", ["PANW"]),
    ("CMP-ZS", "Zscaler", "Zscaler, Inc.", "ZS", "public", "Information Technology", "Software", "US", []),
    ("CMP-FTNT", "Fortinet", "Fortinet, Inc.", "FTNT", "public", "Information Technology", "Software", "US", ["FTNT"]),
    ("CMP-LLY", "Eli Lilly", "Eli Lilly and Company", "LLY", "public", "Health Care", "Pharmaceuticals", "US", ["Lilly", "LLY"]),
    ("CMP-NVO", "Novo Nordisk", "Novo Nordisk A/S", "NVO", "public", "Health Care", "Pharmaceuticals", "DK", ["NVO"]),
    ("CMP-ISRG", "Intuitive Surgical", "Intuitive Surgical, Inc.", "ISRG", "public", "Health Care", "Health Care Equipment", "US", ["ISRG"]),
    ("CMP-BSX", "Boston Scientific", "Boston Scientific Corporation", "BSX", "public", "Health Care", "Health Care Equipment", "US", ["BSX"]),
    ("CMP-FSLR", "First Solar", "First Solar, Inc.", "FSLR", "public", "Information Technology", "Semiconductors", "US", ["FSLR"]),
    ("CMP-FLNC", "Fluence Energy", "Fluence Energy, Inc.", "FLNC", "public", "Industrials", "Electrical Equipment", "US", ["Fluence"]),
    # private borrowers (fictional)
    ("CMP-COBALT", "Cobalt Ridge Data Centers", "Cobalt Ridge Data Centers LLC", "", "private", "Real Estate", "Data Centers", "US", ["Cobalt Ridge"]),
    ("CMP-POLARLOOP", "Polar Loop Cooling Systems", "Polar Loop Cooling Systems, Inc.", "", "private", "Industrials", "Thermal Management", "US", ["Polar Loop"]),
    ("CMP-OSTRANDER", "Ostrander Power Constructors", "Ostrander Power Constructors LLC", "", "private", "Industrials", "Construction & Engineering", "US", ["Ostrander Power", "Ostrander"]),
    ("CMP-LARKSPUR", "Larkspur Fiber Networks", "Larkspur Fiber Networks LLC", "", "private", "Communication Services", "Telecom Services", "US", ["Larkspur Fiber"]),
    ("CMP-MESQUITE", "Mesquite Draw Midstream", "Mesquite Draw Midstream LLC", "", "private", "Energy", "Oil & Gas Midstream", "US", ["Mesquite Draw"]),
    ("CMP-HARBORLIGHT", "Harborlight Health Partners", "Harborlight Health Partners LLC", "", "private", "Health Care", "Health Care Services", "US", ["Harborlight"]),
    ("CMP-CORBEL", "Corbel Logistics", "Corbel Logistics Inc.", "", "private", "Industrials", "Logistics", "US", ["Corbel"]),
    # service providers (fictional)
    ("CMP-PEMBERTON", "Pemberton Grid Consulting", "Pemberton Grid Consulting LLC", "", "service_provider", "Industrials", "Professional Services", "US", ["Pemberton Grid", "Pemberton"]),
    ("CMP-CALDWELL", "Caldwell & Pierce LLP", "Caldwell & Pierce LLP", "", "service_provider", "Industrials", "Legal Services", "US", ["Caldwell & Pierce"]),
]
COMPANY_FIELDS = ("id", "name", "legal_name", "ticker", "kind", "sector", "industry", "country", "aliases")


def companies() -> list[dict]:
    return [dict(zip(COMPANY_FIELDS, row)) for row in COMPANIES]


def company_by_id(cid: str) -> dict:
    for c in companies():
        if c["id"] == cid:
            return c
    raise KeyError(cid)


def company_by_name(name: str) -> dict:
    for c in companies():
        if c["name"] == name:
            return c
    raise KeyError(name)


# Company -> Theme exposure (degree high / medium / low)
COMPANY_THEMES = {
    "CMP-NVDA": {"THM-AI": "high", "THM-SEMI": "high"},
    "CMP-AMD": {"THM-AI": "high", "THM-SEMI": "high"},
    "CMP-AVGO": {"THM-AI": "high", "THM-SEMI": "medium"},
    "CMP-TSM": {"THM-AI": "high", "THM-SEMI": "high"},
    "CMP-MU": {"THM-AI": "medium", "THM-SEMI": "medium"},
    "CMP-ANET": {"THM-AI": "high"},
    "CMP-MRVL": {"THM-AI": "medium", "THM-SEMI": "medium"},
    "CMP-ASML": {"THM-SEMI": "high"},
    "CMP-AMAT": {"THM-SEMI": "high"},
    "CMP-VRT": {"THM-AI": "high", "THM-POWER": "medium"},
    "CMP-ETN": {"THM-POWER": "high", "THM-AI": "medium"},
    "CMP-DELL": {"THM-AI": "medium"},
    "CMP-MSFT": {"THM-AI": "medium", "THM-CYBER": "low"},
    "CMP-GOOGL": {"THM-AI": "medium"},
    "CMP-AMZN": {"THM-AI": "medium"},
    "CMP-META": {"THM-AI": "medium"},
    "CMP-ORCL": {"THM-AI": "medium"},
    "CMP-EQIX": {"THM-DIGITAL-RE": "high", "THM-AI": "medium"},
    "CMP-DLR": {"THM-DIGITAL-RE": "high", "THM-AI": "medium"},
    "CMP-AMT": {"THM-DIGITAL-RE": "high"},
    "CMP-CEG": {"THM-POWER": "high", "THM-TRANSITION": "medium"},
    "CMP-VST": {"THM-POWER": "high"},
    "CMP-NEE": {"THM-TRANSITION": "high", "THM-POWER": "medium"},
    "CMP-GEV": {"THM-POWER": "high", "THM-TRANSITION": "medium"},
    "CMP-PWR": {"THM-POWER": "high", "THM-TRANSITION": "medium"},
    "CMP-WMB": {"THM-ENERGY": "high", "THM-POWER": "medium"},
    "CMP-KMI": {"THM-ENERGY": "high", "THM-POWER": "medium"},
    "CMP-ET": {"THM-ENERGY": "high"},
    "CMP-EPD": {"THM-ENERGY": "high"},
    "CMP-LNG": {"THM-ENERGY": "high"},
    "CMP-TRGP": {"THM-ENERGY": "high"},
    "CMP-CRWD": {"THM-CYBER": "high"},
    "CMP-PANW": {"THM-CYBER": "high"},
    "CMP-ZS": {"THM-CYBER": "high"},
    "CMP-FTNT": {"THM-CYBER": "high"},
    "CMP-LLY": {"THM-HEALTH": "high"},
    "CMP-NVO": {"THM-HEALTH": "high"},
    "CMP-ISRG": {"THM-HEALTH": "high"},
    "CMP-BSX": {"THM-HEALTH": "high"},
    "CMP-FSLR": {"THM-TRANSITION": "high"},
    "CMP-FLNC": {"THM-TRANSITION": "high"},
    "CMP-COBALT": {"THM-AI": "high", "THM-DIGITAL-RE": "high", "THM-POWER": "medium"},
    "CMP-POLARLOOP": {"THM-AI": "high"},
    "CMP-OSTRANDER": {"THM-POWER": "high", "THM-AI": "medium"},
    "CMP-LARKSPUR": {"THM-DIGITAL-RE": "medium", "THM-AI": "low"},
    "CMP-MESQUITE": {"THM-ENERGY": "high", "THM-POWER": "medium"},
    "CMP-HARBORLIGHT": {"THM-HEALTH": "medium"},
}


# =============================================================================
# FUNDS
# =============================================================================
def _fund(fid, name, ticker, asset_class, strategy, inception, aum, pm, themes, aliases, share_class, er, benchmark):
    return {"id": fid, "name": name, "ticker": ticker, "asset_class": asset_class, "strategy": strategy,
            "inception_date": inception, "aum_usd_m": aum, "pm_id": pm, "themes": themes, "aliases": aliases,
            "share_class": share_class, "expense_ratio_pct": er, "benchmark": benchmark}


FUNDS = [
    _fund("FND-AIX", "Arbor Peak AI Infrastructure Fund", "APKAX", "Equity",
          "Thematic equity: AI compute, networking, memory, power and cooling", "2023-04-03", 1243.6, "PER-003",
          ["THM-AI"], ["AI Infrastructure Fund", "APKAX"], "Institutional", 0.85, "MSCI ACWI Index"),
    _fund("FND-GTF", "Arbor Peak Global Technology Fund", "APKGX", "Equity", "Large-cap global technology leaders",
          "2015-01-05", 2861.2, "PER-008", [], ["Global Technology Fund", "Global Tech Fund", "APKGX"],
          "Institutional", 0.68, "MSCI World Information Technology Index"),
    _fund("FND-EIF", "Arbor Peak Energy Infrastructure Fund", "APKEX", "Equity",
          "Midstream pipelines and power-generation infrastructure", "2019-06-03", 978.4, "PER-004",
          ["THM-ENERGY", "THM-POWER"], ["Energy Infrastructure Fund", "APKEX"], "Institutional", 0.79,
          "Alerian Midstream Energy Index"),
    _fund("FND-PC2", "Arbor Peak Private Credit Fund II", "", "Private Credit",
          "Senior secured direct lending to middle-market companies", "2024-01-16", 318.5, "PER-005",
          ["THM-CREDIT"], ["Private Credit Fund II", "PCF II"], "LP Interest", 1.25,
          "Morningstar LSTA US Leveraged Loan Index"),
    _fund("FND-DIR", "Arbor Peak Digital Infrastructure Real Estate Fund", "APKDX", "Real Estate",
          "Data center, tower and fiber real estate securities", "2021-03-01", 412.7, "PER-008",
          ["THM-DIGITAL-RE"], ["Digital Infrastructure Real Estate Fund", "Digital Infrastructure Fund", "APKDX"],
          "Institutional", 0.74, "FTSE Nareit All Equity REITs Index"),
    _fund("FND-CYB", "Arbor Peak Cybersecurity Leaders Fund", "APKCX", "Equity", "Cybersecurity platform leaders",
          "2022-05-02", 352.9, "PER-013", ["THM-CYBER"], ["Cybersecurity Leaders Fund", "APKCX"],
          "Institutional", 0.82, "Nasdaq CTA Cybersecurity Index"),
    _fund("FND-HCI", "Arbor Peak Healthcare Innovation Fund", "APKHX", "Equity",
          "Therapeutics and medical technology", "2018-02-01", 761.3, "PER-014", ["THM-HEALTH"],
          ["Healthcare Innovation Fund", "APKHX"], "Institutional", 0.77, "MSCI World Health Care Index"),
    _fund("FND-CET", "Arbor Peak Clean Energy Transition Fund", "APKTX", "Equity",
          "Renewables, storage and grid modernization", "2020-10-01", 428.8, "PER-010", ["THM-TRANSITION"],
          ["Clean Energy Transition Fund", "APKTX"], "Institutional", 0.81, "S&P Global Clean Energy Transition Index"),
    _fund("FND-CFI", "Arbor Peak Core Fixed Income Fund", "APKBX", "Fixed Income", "Investment-grade core bonds",
          "2012-07-02", 3147.5, "PER-015", ["THM-RATES"], ["Core Fixed Income Fund", "APKBX"], "Institutional",
          0.38, "Bloomberg US Aggregate Bond Index"),
    _fund("FND-MUN", "Arbor Peak Municipal Income Fund", "APKMX", "Fixed Income", "Tax-exempt municipal bonds",
          "2014-04-01", 1819.4, "PER-015", ["THM-RATES"], ["Municipal Income Fund", "APKMX"], "Institutional",
          0.42, "Bloomberg Municipal Bond Index"),
]


def fund_by_id(fid: str) -> dict:
    for f in FUNDS:
        if f["id"] == fid:
            return f
    raise KeyError(fid)


# Fund -> company positions as of AS_OF_DATE: (company_id, weight % of NAV, held since). Weights cover the
# names in the security master; the balance of each fund is in other holdings and cash.
FUND_HOLDINGS = {
    "FND-AIX": [("CMP-NVDA", 9.94, "2023-04-03"), ("CMP-AVGO", 9.12, "2023-04-03"), ("CMP-TSM", 8.47, "2023-04-03"),
                ("CMP-AMD", 6.58, "2023-04-03"), ("CMP-MU", 5.63, "2023-09-05"), ("CMP-ANET", 6.11, "2023-04-03"),
                ("CMP-MRVL", 4.36, "2024-02-12"), ("CMP-ASML", 3.87, "2023-04-03"), ("CMP-AMAT", 3.42, "2024-06-03"),
                ("CMP-VRT", 6.24, "2023-04-03"), ("CMP-ETN", 4.91, "2023-04-03"), ("CMP-EQIX", 3.78, "2023-04-03"),
                ("CMP-DLR", 3.36, "2024-01-08"), ("CMP-MSFT", 4.05, "2023-04-03"), ("CMP-ORCL", 3.18, "2024-09-03"),
                ("CMP-DELL", 2.87, "2024-11-04"), ("CMP-CEG", 3.06, "2025-02-03"), ("CMP-PWR", 2.94, "2025-02-03")],
    "FND-GTF": [("CMP-MSFT", 8.86, "2015-01-05"), ("CMP-GOOGL", 6.12, "2015-01-05"), ("CMP-AMZN", 5.87, "2015-01-05"),
                ("CMP-META", 5.41, "2016-03-01"), ("CMP-NVDA", 8.17, "2017-05-01"), ("CMP-AVGO", 4.92, "2019-02-04"),
                ("CMP-ORCL", 3.88, "2021-06-01"), ("CMP-CRWD", 3.96, "2020-08-03"), ("CMP-PANW", 4.07, "2018-05-01"),
                ("CMP-TSM", 3.91, "2018-01-02"), ("CMP-AMD", 2.84, "2020-01-06"), ("CMP-ANET", 2.93, "2022-02-01"),
                ("CMP-ASML", 2.78, "2019-07-01"), ("CMP-ZS", 2.41, "2021-03-01"), ("CMP-FTNT", 2.36, "2021-03-01"),
                ("CMP-DELL", 1.97, "2024-05-01")],
    "FND-EIF": [("CMP-WMB", 9.21, "2019-06-03"), ("CMP-KMI", 8.14, "2019-06-03"), ("CMP-ET", 7.86, "2019-06-03"),
                ("CMP-EPD", 7.12, "2019-06-03"), ("CMP-LNG", 6.93, "2020-02-03"), ("CMP-TRGP", 5.87, "2021-05-03"),
                ("CMP-CEG", 6.74, "2024-03-01"), ("CMP-VST", 5.91, "2024-03-01"), ("CMP-GEV", 5.18, "2024-04-15"),
                ("CMP-PWR", 4.13, "2024-04-15"), ("CMP-ETN", 2.96, "2025-01-06")],
    # private credit: par outstanding as % of fund NAV
    "FND-PC2": [("CMP-COBALT", 13.87, "2026-04-20"), ("CMP-POLARLOOP", 6.19, "2026-09-15"),
                ("CMP-OSTRANDER", 8.94, "2024-06-10"), ("CMP-LARKSPUR", 7.83, "2024-09-03"),
                ("CMP-MESQUITE", 10.21, "2025-03-18"), ("CMP-HARBORLIGHT", 10.86, "2024-03-01"),
                ("CMP-CORBEL", 9.12, "2024-11-12")],
    "FND-DIR": [("CMP-EQIX", 9.87, "2021-03-01"), ("CMP-DLR", 9.64, "2021-03-01"), ("CMP-AMT", 9.21, "2021-03-01")],
    "FND-CYB": [("CMP-CRWD", 9.83, "2022-05-02"), ("CMP-PANW", 9.91, "2022-05-02"), ("CMP-ZS", 9.46, "2022-05-02"),
                ("CMP-FTNT", 9.58, "2022-05-02"), ("CMP-MSFT", 7.84, "2022-05-02")],
    "FND-HCI": [("CMP-LLY", 9.92, "2018-02-01"), ("CMP-NVO", 8.37, "2019-04-01"), ("CMP-ISRG", 9.68, "2018-02-01"),
                ("CMP-BSX", 9.41, "2020-06-01")],
    "FND-CET": [("CMP-NEE", 9.78, "2020-10-01"), ("CMP-FSLR", 9.36, "2020-10-01"), ("CMP-FLNC", 5.83, "2022-01-03"),
                ("CMP-GEV", 9.69, "2024-04-15"), ("CMP-CEG", 8.94, "2022-02-01"), ("CMP-PWR", 6.12, "2023-03-01")],
    "FND-CFI": [],
    "FND-MUN": [],
}

# IC-2026-011 adopted a 10% single-name cap in thematic funds. FUND_HOLDINGS above are the post-cap weights
# (as of AS_OF_DATE); before each fund's implementation date its positions carried these weights instead.
# In the AI Infrastructure Fund the 2 points trimmed from Nvidia went to Broadcom and AMD (the July Nvidia
# position review), so the fund's AI Infrastructure exposure is identical before and after the trim.
THEMATIC_FUNDS = {"FND-AIX", "FND-CYB", "FND-DIR", "FND-HCI", "FND-CET", "FND-EIF"}
SINGLE_NAME_CAP_PCT = 10.0
CAP_IMPLEMENTED = {"FND-AIX": "2026-07-27", "FND-CYB": "2026-08-14", "FND-DIR": "2026-08-14",
                   "FND-HCI": "2026-08-14", "FND-CET": "2026-08-14"}
PRE_CAP_WEIGHTS = {
    "FND-AIX": {"CMP-NVDA": 11.94, "CMP-AVGO": 8.12, "CMP-AMD": 5.58},
    "FND-CYB": {"CMP-CRWD": 14.87, "CMP-PANW": 15.12, "CMP-ZS": 11.94, "CMP-FTNT": 12.06},
    "FND-DIR": {"CMP-EQIX": 17.85, "CMP-DLR": 15.92, "CMP-AMT": 14.13},
    "FND-HCI": {"CMP-LLY": 13.96, "CMP-ISRG": 12.11, "CMP-BSX": 10.87},
    "FND-CET": {"CMP-NEE": 13.92},
}


def fund_weight(fund_id: str, company_id: str, weight_now: float, as_of: str) -> float:
    """Weight of a holding at `as_of`, honouring the pre-cap weights before the cap was implemented."""
    if as_of < CAP_IMPLEMENTED.get(fund_id, "0000-00-00"):
        return PRE_CAP_WEIGHTS.get(fund_id, {}).get(company_id, weight_now)
    return weight_now


EXPOSURE_FACTORS = {"high": 1.0, "medium": 0.5, "low": 0.25}
EXPOSURE_GUIDELINE_PCT = 15.0


# =============================================================================
# CALENDAR (NYSE trading days)
# =============================================================================
NYSE_HOLIDAYS = {
    "2025-01-01", "2025-01-09", "2025-01-20", "2025-02-17", "2025-04-18", "2025-05-26", "2025-06-19",
    "2025-07-04", "2025-09-01", "2025-11-27", "2025-12-25",
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19", "2026-07-03",
    "2026-09-07", "2026-11-26", "2026-12-25",
}


def is_business_day(iso: str) -> bool:
    return date.fromisoformat(iso).weekday() < 5 and iso not in NYSE_HOLIDAYS


def business_days(start: str, end: str) -> list[str]:
    d0, d1 = date.fromisoformat(start), date.fromisoformat(end)
    out, d = [], d0
    while d <= d1:
        if is_business_day(d.isoformat()):
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def next_business_day(iso: str, n: int = 1) -> str:
    d = date.fromisoformat(iso)
    while n > 0:
        d += timedelta(days=1)
        if is_business_day(d.isoformat()):
            n -= 1
    return d.isoformat()


def on_or_after(iso: str) -> str:
    return iso if is_business_day(iso) else next_business_day(iso)


def _last_business_day_of_month(year: int, month: int) -> str:
    d = date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1)
    while not is_business_day(d.isoformat()):
        d -= timedelta(days=1)
    return d.isoformat()


# =============================================================================
# PRICING - daily NAV per fund (deterministic)
# =============================================================================
PRICING_START = "2024-12-31"
_QUARTER_ENDS = ["2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31", "2026-03-31", "2026-06-30", "2026-09-30"]
# NAV on 2024-12-31, daily volatility, quarterly total returns Q1 2025 .. Q3 2026
_NAV_SPECS = {
    "FND-AIX": (17.86, 0.0205, [-0.151, 0.196, 0.074, 0.012, 0.024, 0.047, 0.039]),
    "FND-GTF": (48.37, 0.0138, [-0.097, 0.128, 0.047, 0.014, 0.006, 0.036, 0.027]),
    "FND-EIF": (27.15, 0.0108, [0.054, -0.016, 0.034, 0.041, 0.063, 0.021, 0.034]),
    "FND-DIR": (21.42, 0.0117, [-0.039, 0.054, 0.021, 0.006, 0.029, 0.024, 0.016]),
    "FND-CYB": (16.88, 0.0171, [-0.076, 0.149, 0.024, 0.011, -0.031, 0.059, 0.036]),
    "FND-HCI": (31.05, 0.0109, [0.016, -0.081, 0.006, 0.069, 0.034, -0.014, 0.021]),
    "FND-CET": (12.64, 0.0183, [-0.091, 0.112, 0.124, 0.061, 0.044, 0.021, 0.029]),
    # bond funds: price returns (income is paid monthly, see _MONTHLY_INCOME)
    "FND-CFI": (9.47, 0.0024, [0.009, -0.003, 0.006, 0.002, -0.004, -0.005, 0.006]),
    "FND-MUN": (10.82, 0.0016, [-0.006, -0.012, 0.005, 0.011, -0.001, -0.003, 0.004]),
}
# Private Credit Fund II strikes NAV quarterly (the Q3 2026 mark is not struck until mid-November).
PC2_NAV_MARKS = [("2024-01-16", 10.0000), ("2024-12-31", 10.0812), ("2025-03-31", 10.1047),
                 ("2025-06-30", 10.0893), ("2025-09-30", 10.1384), ("2025-12-31", 10.1716),
                 ("2026-03-31", 10.1602), ("2026-06-30", 10.2075)]
# distributions: fund -> [(ex/pay date, kind, income rate, capital-gain rate)] as a fraction of NAV
_DISTRIBUTIONS = {
    "FND-AIX": [("2025-12-16", "Year-end", 0.0021, 0.0318)],
    "FND-GTF": [("2025-12-16", "Year-end", 0.0038, 0.0461)],
    "FND-CYB": [("2025-12-16", "Year-end", 0.0, 0.0207)],
    "FND-HCI": [("2025-12-16", "Year-end", 0.0044, 0.0289)],
    "FND-CET": [("2025-12-16", "Year-end", 0.0118, 0.0)],
    "FND-DIR": [(d, "Quarterly", 0.0068, 0.0) for d in
                ["2025-03-27", "2025-06-26", "2025-09-25", "2025-12-18", "2026-03-26", "2026-06-25", "2026-09-24"]],
    "FND-EIF": [(d, "Quarterly", 0.0104, 0.0) for d in
                ["2025-02-13", "2025-05-15", "2025-08-14", "2025-11-13", "2026-02-12", "2026-05-14", "2026-08-13"]],
}
# bond funds: monthly income dividend per share, paid (and reinvested) on the last business day of the month
_MONTHLY_INCOME = {"FND-CFI": {"2025": 0.0327, "2026": 0.0319}, "FND-MUN": {"2025": 0.0298, "2026": 0.0291}}
PC2_DISTRIBUTION_RATE = 0.022   # quarterly income distribution, fraction of the latest NAV

_NAV_CACHE: dict[str, dict[str, float]] | None = None


def _build_navs() -> dict[str, dict[str, float]]:
    days = business_days(PRICING_START, AS_OF_DATE.isoformat())
    out: dict[str, dict[str, float]] = {}
    for fid, (start, vol, returns) in _NAV_SPECS.items():
        rng = random.Random(_seed("nav", fid))
        level, total_return = start, {days[0]: start}
        prev_end = days[0]
        for q_end, ret in zip(_QUARTER_ENDS, returns):
            seg = [d for d in days if prev_end < d <= q_end]
            shocks = [rng.gauss(0.0, vol) for _ in seg]
            cum, running = [], 0.0
            for s in shocks:
                running += s
                cum.append(running)
            n, target = len(seg), math.log(1.0 + ret)
            for i, d in enumerate(seg):        # Brownian bridge pinned to the quarter's return
                frac = (i + 1) / n
                total_return[d] = level * math.exp(cum[i] - frac * cum[-1] + frac * target)
            level, prev_end = total_return[seg[-1]], q_end
        factor, navs = 1.0, {}
        ex_rates = {d: inc + cg for d, _kind, inc, cg in _DISTRIBUTIONS.get(fid, [])}
        for d in days:
            if d in ex_rates:
                factor *= 1.0 - ex_rates[d]
            navs[d] = round(total_return[d] * factor, 2)
        out[fid] = navs
    marks = PC2_NAV_MARKS
    out["FND-PC2"] = {d: next(v for m, v in reversed(marks) if m <= d) for d in days}
    return out


def nav(fund_id: str, as_of: str) -> float:
    """NAV per share at the close of `as_of` (the last trading day on or before it)."""
    global _NAV_CACHE
    if _NAV_CACHE is None:
        _NAV_CACHE = _build_navs()
    series = _NAV_CACHE[fund_id]
    if as_of in series:
        return series[as_of]
    keys = _NAV_KEYS.setdefault(fund_id, sorted(series))
    i = bisect_right(keys, as_of)
    if i == 0:
        raise ValueError(f"no NAV for {fund_id} on or before {as_of}")
    return series[keys[i - 1]]


_NAV_KEYS: dict[str, list[str]] = {}


def nav_history() -> list[dict]:
    """Daily NAV rows (pricing feed export); Private Credit Fund II reports its quarterly marks only."""
    nav("FND-CFI", PRICING_START)          # builds the cache
    rows = []
    for fid in sorted(_NAV_CACHE):
        ticker = fund_by_id(fid)["ticker"]
        if fid == "FND-PC2":
            rows += [{"date": d, "fund_id": fid, "ticker": ticker, "nav": v} for d, v in PC2_NAV_MARKS]
            continue
        for d, value in sorted(_NAV_CACHE[fid].items()):
            rows.append({"date": d, "fund_id": fid, "ticker": ticker, "nav": value})
    return rows


# =============================================================================
# ACCOUNTS (portfolio accounting)
# =============================================================================
ACCOUNTS = [
    # id, client_id, name, account_type, custodian, tax_status, opened_date, registration
    ("ACC-1001", "C-001", "Hartwell Family Trust - Taxable", "Trust", "Schwab", "Taxable", "2014-05-12",
     "Robert J. Hartwell & Elaine M. Hartwell TTEES, Hartwell Family Trust U/A DTD 04/28/2014"),
    ("ACC-1002", "C-001", "Robert Hartwell - Rollover IRA", "IRA", "Schwab", "Tax-deferred", "2016-02-01",
     "Charles Schwab & Co Inc CUST IRA Rollover FBO Robert J. Hartwell"),
    ("ACC-1003", "C-001", "Hartwell Family Trust - Private Investments", "Private Investments",
     "Arbor Peak Private Markets", "Taxable", "2024-01-16",
     "Hartwell Family Trust - LP interest, Arbor Peak Private Credit Fund II, L.P."),
    ("ACC-1004", "C-002", "Okafor Family Office - Taxable", "Family Office", "Fidelity", "Taxable", "2018-03-05",
     "Okafor Family Holdings LLC"),
    ("ACC-1005", "C-002", "Okafor Family Office - Private Investments", "Private Investments",
     "Arbor Peak Private Markets", "Taxable", "2024-01-16",
     "Okafor Family Holdings LLC - LP interest, Arbor Peak Private Credit Fund II, L.P."),
    ("ACC-1006", "C-003", "Bellamy Foundation - Endowment Pool", "Foundation", "Pershing", "Tax-exempt", "2016-09-01",
     "The Bellamy Foundation"),
    ("ACC-1007", "C-004", "Lindqvist Revocable Trust", "Trust", "Fidelity", "Taxable", "2019-01-15",
     "Erik A. Lindqvist TTEE, Erik A. Lindqvist Revocable Trust U/A DTD 11/02/2018"),
    ("ACC-1008", "C-004", "Erik Lindqvist - IRA", "IRA", "Fidelity", "Tax-deferred", "2019-01-15",
     "Fidelity Management Trust Co CUST IRA FBO Erik A. Lindqvist"),
    ("ACC-1009", "C-005", "Ramirez Joint Taxable", "Joint", "Schwab", "Taxable", "2020-06-01",
     "Carlos M. Ramirez & Sofia L. Ramirez JTWROS"),
    ("ACC-1010", "C-005", "Carlos Ramirez - IRA", "IRA", "Schwab", "Tax-deferred", "2020-06-01",
     "Charles Schwab & Co Inc CUST IRA FBO Carlos M. Ramirez"),
    ("ACC-1011", "C-005", "Sofia Ramirez - Roth IRA", "Roth IRA", "Schwab", "Tax-free", "2020-06-01",
     "Charles Schwab & Co Inc CUST Roth IRA FBO Sofia L. Ramirez"),
    ("ACC-1012", "C-006", "Whitman Charitable Foundation", "Foundation", "Pershing", "Tax-exempt", "2015-04-20",
     "Whitman Charitable Foundation"),
    ("ACC-1013", "C-007", "Nakamura Family Partners - Taxable", "Partnership", "Pershing", "Taxable", "2017-11-02",
     "Nakamura Family Partners LP"),
    ("ACC-1014", "C-007", "Nakamura Family Partners - Private Investments", "Private Investments",
     "Arbor Peak Private Markets", "Taxable", "2024-01-16",
     "Nakamura Family Partners LP - LP interest, Arbor Peak Private Credit Fund II, L.P."),
    ("ACC-1015", "C-008", "Delgado Family Trust", "Trust", "Schwab", "Taxable", "2021-02-10",
     "Maria E. Delgado TTEE, Delgado Family Trust U/A DTD 09/14/2020"),
    ("ACC-1016", "C-008", "Maria Delgado - IRA", "IRA", "Schwab", "Tax-deferred", "2021-02-10",
     "Charles Schwab & Co Inc CUST IRA FBO Maria E. Delgado"),
    ("ACC-1017", "C-009", "St. Aldric School Endowment", "Endowment", "Pershing", "Tax-exempt", "2013-08-30",
     "Trustees of St. Aldric School - Endowment Fund"),
    ("ACC-1018", "C-010", "Brennan Joint Taxable", "Joint", "Fidelity", "Taxable", "2022-03-14",
     "Patrick J. Brennan & Megan R. Brennan JTWROS"),
    ("ACC-1019", "C-010", "Patrick Brennan - IRA", "IRA", "Fidelity", "Tax-deferred", "2022-03-14",
     "Fidelity Management Trust Co CUST IRA Rollover FBO Patrick J. Brennan"),
    ("ACC-1020", "C-011", "Sterling-Hayes Family Office - Taxable", "Family Office", "Pershing", "Taxable",
     "2019-07-08", "Sterling-Hayes Family Office LLC"),
    ("ACC-1021", "C-011", "Sterling-Hayes Family Office - Private Investments", "Private Investments",
     "Arbor Peak Private Markets", "Taxable", "2024-01-16",
     "Sterling-Hayes Family Office LLC - LP interest, Arbor Peak Private Credit Fund II, L.P."),
    ("ACC-1022", "C-012", "Irina Volkov - Individual", "Individual", "Schwab", "Taxable", "2023-05-22",
     "Irina V. Volkov"),
    ("ACC-1023", "C-012", "Irina Volkov - Roth IRA", "Roth IRA", "Schwab", "Tax-free", "2023-05-22",
     "Charles Schwab & Co Inc CUST Roth IRA FBO Irina V. Volkov"),
    ("ACC-1024", "C-013", "Prescott Joint Taxable", "Joint", "Schwab", "Taxable", "2016-10-03",
     "William T. Prescott & Anne C. Prescott JTWROS"),
    ("ACC-1025", "C-013", "William Prescott - Rollover IRA", "IRA", "Schwab", "Tax-deferred", "2016-10-03",
     "Charles Schwab & Co Inc CUST IRA Rollover FBO William T. Prescott"),
    ("ACC-1026", "C-013", "Anne Prescott - Roth IRA", "Roth IRA", "Schwab", "Tax-free", "2018-01-08",
     "Charles Schwab & Co Inc CUST Roth IRA FBO Anne C. Prescott"),
    ("ACC-1027", "C-014", "Whitcomb Family Trust", "Trust", "Schwab", "Taxable", "2012-03-19",
     "Harold G. Whitcomb & Judith A. Whitcomb TTEES, Whitcomb Family Trust U/A DTD 02/06/2012"),
    ("ACC-1028", "C-014", "Harold Whitcomb - IRA", "IRA", "Schwab", "Tax-deferred", "2012-03-19",
     "Charles Schwab & Co Inc CUST IRA FBO Harold G. Whitcomb"),
    ("ACC-1029", "C-015", "Adeyemi Joint Taxable", "Joint", "Fidelity", "Taxable", "2021-08-09",
     "Folake O. Adeyemi & Tunde A. Adeyemi JTWROS"),
    ("ACC-1030", "C-015", "Folake Adeyemi - Rollover IRA", "IRA", "Fidelity", "Tax-deferred", "2021-08-09",
     "Fidelity Management Trust Co CUST IRA Rollover FBO Folake O. Adeyemi"),
    ("ACC-1031", "C-015", "Tunde Adeyemi - Roth IRA", "Roth IRA", "Fidelity", "Tax-free", "2021-08-09",
     "Fidelity Management Trust Co CUST Roth IRA FBO Tunde A. Adeyemi"),
    ("ACC-1032", "C-016", "Thibodeaux Joint Taxable", "Joint", "Pershing", "Taxable", "2017-05-22",
     "Marc P. Thibodeaux & Celeste M. Thibodeaux JTWROS"),
    ("ACC-1033", "C-016", "Marc Thibodeaux - IRA", "IRA", "Pershing", "Tax-deferred", "2017-05-22",
     "Pershing LLC CUST IRA FBO Marc P. Thibodeaux"),
    ("ACC-1034", "C-017", "Garza Family Foundation", "Foundation", "Pershing", "Tax-exempt", "2014-11-10",
     "The Garza Family Foundation"),
    ("ACC-1035", "C-018", "Raghavan Joint Taxable", "Joint", "Schwab", "Taxable", "2020-02-03",
     "Vikram S. Raghavan & Anjali R. Raghavan JTWROS"),
    ("ACC-1036", "C-018", "Vikram Raghavan - Rollover IRA", "IRA", "Schwab", "Tax-deferred", "2020-02-03",
     "Charles Schwab & Co Inc CUST IRA Rollover FBO Vikram S. Raghavan"),
    ("ACC-1037", "C-019", "Kowalczyk Joint Taxable", "Joint", "Fidelity", "Taxable", "2018-09-17",
     "Jerzy K. Kowalczyk & Ewa M. Kowalczyk JTWROS"),
    ("ACC-1038", "C-019", "Jerzy Kowalczyk - IRA", "IRA", "Fidelity", "Tax-deferred", "2018-09-17",
     "Fidelity Management Trust Co CUST IRA FBO Jerzy K. Kowalczyk"),
    ("ACC-1039", "C-020", "Fairbanks Charitable Trust", "Trust", "Pershing", "Tax-exempt", "2011-04-04",
     "Lionel H. Fairbanks TTEE, Fairbanks Charitable Remainder Unitrust U/A DTD 03/01/2011"),
    ("ACC-1040", "C-021", "Odum Joint Taxable", "Joint", "Schwab", "Taxable", "2022-06-13",
     "Darnell L. Odum & Keisha N. Odum JTWROS"),
    ("ACC-1041", "C-021", "Darnell Odum - Rollover IRA", "IRA", "Schwab", "Tax-deferred", "2022-06-13",
     "Charles Schwab & Co Inc CUST IRA Rollover FBO Darnell L. Odum"),
    ("ACC-1042", "C-021", "Keisha Odum - Roth IRA", "Roth IRA", "Schwab", "Tax-free", "2022-06-13",
     "Charles Schwab & Co Inc CUST Roth IRA FBO Keisha N. Odum"),
    ("ACC-1043", "C-022", "Takahashi Living Trust", "Trust", "Schwab", "Taxable", "2015-07-27",
     "Hiroshi Takahashi & Emily S. Takahashi TTEES, Takahashi Living Trust U/A DTD 06/19/2015"),
    ("ACC-1044", "C-022", "Hiroshi Takahashi - IRA", "IRA", "Schwab", "Tax-deferred", "2015-07-27",
     "Charles Schwab & Co Inc CUST IRA FBO Hiroshi Takahashi"),
    ("ACC-1045", "C-023", "Bergstrom Family Trust - Taxable", "Trust", "Pershing", "Taxable", "2013-02-25",
     "Nils E. Bergstrom & Karin L. Bergstrom TTEES, Bergstrom Family Trust U/A DTD 01/30/2013"),
    ("ACC-1046", "C-023", "Nils Bergstrom - Rollover IRA", "IRA", "Pershing", "Tax-deferred", "2013-02-25",
     "Pershing LLC CUST IRA Rollover FBO Nils E. Bergstrom"),
    ("ACC-1047", "C-024", "Weiss Family Foundation", "Foundation", "Pershing", "Tax-exempt", "2016-01-19",
     "Harlan and Ruth Weiss Family Foundation"),
    ("ACC-1048", "C-025", "Villarreal Joint Taxable", "Joint", "Schwab", "Taxable", "2019-10-07",
     "Ernesto R. Villarreal & Gloria A. Villarreal JTWROS"),
    ("ACC-1049", "C-025", "Ernesto Villarreal - IRA", "IRA", "Schwab", "Tax-deferred", "2019-10-07",
     "Charles Schwab & Co Inc CUST IRA FBO Ernesto R. Villarreal"),
    ("ACC-1050", "C-026", "Kerrigan Family Trust", "Trust", "Fidelity", "Taxable", "2018-04-16",
     "Sean P. Kerrigan & Colleen M. Kerrigan TTEES, Kerrigan Family Trust U/A DTD 03/22/2018"),
    ("ACC-1051", "C-027", "Castellanos Joint Taxable", "Joint", "Schwab", "Taxable", "2023-01-23",
     "Adrian J. Castellanos & Mariana Castellanos JTWROS"),
    ("ACC-1052", "C-027", "Adrian Castellanos - Roth IRA", "Roth IRA", "Schwab", "Tax-free", "2023-01-23",
     "Charles Schwab & Co Inc CUST Roth IRA FBO Adrian J. Castellanos"),
    ("ACC-1053", "C-028", "Lindahl Joint Taxable", "Joint", "Fidelity", "Taxable", "2021-11-01",
     "Anders M. Lindahl & Kristin E. Lindahl JTWROS"),
    ("ACC-1054", "C-028", "Anders Lindahl - Rollover IRA", "IRA", "Fidelity", "Tax-deferred", "2021-11-01",
     "Fidelity Management Trust Co CUST IRA Rollover FBO Anders M. Lindahl"),
    ("ACC-1055", "C-028", "Kristin Lindahl - Roth IRA", "Roth IRA", "Fidelity", "Tax-free", "2021-11-01",
     "Fidelity Management Trust Co CUST Roth IRA FBO Kristin E. Lindahl"),
    ("ACC-1056", "C-029", "Haugen Joint Taxable", "Joint", "Schwab", "Taxable", "2019-03-11",
     "Lars O. Haugen & Ingrid K. Haugen JTWROS"),
    ("ACC-1057", "C-029", "Lars Haugen - IRA", "IRA", "Schwab", "Tax-deferred", "2019-03-11",
     "Charles Schwab & Co Inc CUST IRA FBO Lars O. Haugen"),
    ("ACC-1058", "C-030", "Cascade Wetlands Conservancy - Endowment", "Endowment", "Pershing", "Tax-exempt",
     "2020-09-14", "Cascade Wetlands Conservancy - Board Designated Endowment"),
    ("ACC-1059", "C-031", "Montgomery Joint Taxable", "Joint", "Schwab", "Taxable", "2011-09-12",
     "Clayton W. Montgomery & Beverly J. Montgomery JTWROS"),
    ("ACC-1060", "C-031", "Clayton Montgomery - IRA", "IRA", "Schwab", "Tax-deferred", "2011-09-12",
     "Charles Schwab & Co Inc CUST IRA FBO Clayton W. Montgomery"),
    ("ACC-1061", "C-031", "Beverly Montgomery - IRA", "IRA", "Schwab", "Tax-deferred", "2011-09-12",
     "Charles Schwab & Co Inc CUST IRA FBO Beverly J. Montgomery"),
    ("ACC-1062", "C-032", "Ferraro Family Partners", "Partnership", "Pershing", "Taxable", "2016-06-06",
     "Ferraro Family Partners LP"),
    ("ACC-1063", "C-033", "Simone Delacroix - Individual", "Individual", "Fidelity", "Taxable", "2019-05-20",
     "Simone A. Delacroix"),
    ("ACC-1064", "C-033", "Simone Delacroix - Rollover IRA", "IRA", "Fidelity", "Tax-deferred", "2019-05-20",
     "Fidelity Management Trust Co CUST IRA Rollover FBO Simone A. Delacroix"),
    ("ACC-1065", "C-034", "Varga Joint Taxable", "Joint", "Schwab", "Taxable", "2022-10-24",
     "Peter Varga & Julia K. Varga JTWROS"),
    ("ACC-1066", "C-034", "Peter Varga - Roth IRA", "Roth IRA", "Schwab", "Tax-free", "2022-10-24",
     "Charles Schwab & Co Inc CUST Roth IRA FBO Peter Varga"),
    ("ACC-1067", "C-035", "Sorensen Family Trust", "Trust", "Pershing", "Taxable", "2017-08-28",
     "Mark D. Sorensen TTEE, Sorensen Family Trust U/A DTD 07/11/2017"),
    ("ACC-1068", "C-035", "Mark Sorensen - Rollover IRA", "IRA", "Pershing", "Tax-deferred", "2017-08-28",
     "Pershing LLC CUST IRA Rollover FBO Mark D. Sorensen"),
    ("ACC-1069", "C-036", "Medina Joint Taxable", "Joint", "Schwab", "Taxable", "2021-04-12",
     "Luis A. Medina & Teresa G. Medina JTWROS"),
    ("ACC-1070", "C-036", "Luis Medina - IRA", "IRA", "Schwab", "Tax-deferred", "2021-04-12",
     "Charles Schwab & Co Inc CUST IRA FBO Luis A. Medina"),
    ("ACC-1071", "C-037", "Hollis Creek Day School Endowment", "Endowment", "Pershing", "Tax-exempt", "2015-09-08",
     "Hollis Creek Day School - Endowment Fund"),
    ("ACC-1072", "C-038", "Rahman Joint Taxable", "Joint", "Fidelity", "Taxable", "2023-09-18",
     "Farhan Rahman & Nadia S. Rahman JTWROS"),
    ("ACC-1073", "C-038", "Farhan Rahman - Rollover IRA", "IRA", "Fidelity", "Tax-deferred", "2023-09-18",
     "Fidelity Management Trust Co CUST IRA Rollover FBO Farhan Rahman"),
    ("ACC-1074", "C-039", "Brandt Revocable Trust", "Trust", "Fidelity", "Taxable", "2014-12-01",
     "Walter F. Brandt TTEE, Walter F. Brandt Revocable Trust U/A DTD 10/20/2014"),
    ("ACC-1075", "C-039", "Walter Brandt - IRA", "IRA", "Fidelity", "Tax-deferred", "2014-12-01",
     "Fidelity Management Trust Co CUST IRA FBO Walter F. Brandt"),
    ("ACC-1076", "C-040", "Kaplan-Reyes Joint Taxable", "Joint", "Schwab", "Taxable", "2020-11-16",
     "Jonah D. Kaplan & Isabel M. Reyes JTWROS"),
    ("ACC-1077", "C-040", "Jonah Kaplan - IRA", "IRA", "Schwab", "Tax-deferred", "2020-11-16",
     "Charles Schwab & Co Inc CUST IRA FBO Jonah D. Kaplan"),
    ("ACC-1078", "C-040", "Isabel Reyes - Roth IRA", "Roth IRA", "Schwab", "Tax-free", "2020-11-16",
     "Charles Schwab & Co Inc CUST Roth IRA FBO Isabel M. Reyes"),
]
ACCOUNT_FIELDS = ("id", "account_number", "client_id", "name", "registration", "account_type", "custodian",
                  "tax_status", "model", "opened_date", "commitment_usd")
PRIVATE_ACCOUNT_TYPE = "Private Investments"
FOSSIL_FUEL_EXCLUSION = {"C-003"}            # Bellamy Foundation IPS
# Private Credit Fund II commitments (USD)
PC2_COMMITMENTS = {"ACC-1003": 7_000_000, "ACC-1005": 9_000_000, "ACC-1014": 3_000_000, "ACC-1021": 8_000_000}
PC2_CALLED_BEFORE_2025 = 0.60                # capital calls #1-#5 (2024)


def _account_number(aid: str, custodian: str) -> str:
    rng = random.Random(_seed("acct", aid))
    if custodian == "Schwab":
        return f"{rng.randint(1000, 9999)}-{rng.randint(1000, 9999)}"
    if custodian == "Fidelity":
        return f"Z{rng.randint(10, 99)}-{rng.randint(100000, 999999)}"
    if custodian == "Pershing":
        return f"7AP-{rng.randint(100000, 999999)}"
    return f"PCF2-LP-{int(aid[-4:]) - 1000:04d}"


def _is_retirement(account_type: str) -> bool:
    return account_type in ("IRA", "Roth IRA")


def account_model(aid: str, client_id: str, account_type: str) -> str:
    """Model portfolio the account is managed to (drives model-change trades)."""
    if account_type == PRIVATE_ACCOUNT_TYPE:
        return "Private Markets"
    risk = client_by_id(client_id)["risk_profile"]
    model = risk
    if client_id in FOSSIL_FUEL_EXCLUSION:
        model += " - Fossil Fuel Screen"
    if client_id in TECH_OVERWEIGHT_CLIENTS:
        model += " - Client-Directed Technology Overweight"
    return model


TECH_OVERWEIGHT_CLIENTS = {"C-001", "C-002", "C-011"}

_ACCOUNTS_CACHE: list[dict] | None = None


def accounts() -> list[dict]:
    global _ACCOUNTS_CACHE
    if _ACCOUNTS_CACHE is None:
        out = []
        for aid, cid, name, atype, custodian, tax, opened, registration in ACCOUNTS:
            out.append({"id": aid, "account_number": _account_number(aid, custodian), "client_id": cid,
                        "name": name, "registration": registration, "account_type": atype, "custodian": custodian,
                        "tax_status": tax, "model": account_model(aid, cid, atype), "opened_date": opened,
                        "commitment_usd": PC2_COMMITMENTS.get(aid, "")})
        _ACCOUNTS_CACHE = out
    return [dict(a) for a in _ACCOUNTS_CACHE]


def account_by_id(aid: str) -> dict:
    for a in accounts():
        if a["id"] == aid:
            return a
    raise KeyError(aid)


def accounts_for_client(cid: str) -> list[dict]:
    return [a for a in accounts() if a["client_id"] == cid]


# Model sleeves used to build opening positions (% of account), before the 2025-2026 model changes
_MODEL_WEIGHTS = {
    "G-TX": {"FND-AIX": 5, "FND-GTF": 16, "FND-DIR": 5, "FND-HCI": 7, "FND-CET": 5, "FND-MUN": 32, "FND-CFI": 30},
    "G-IRA": {"FND-AIX": 5, "FND-GTF": 16, "FND-HCI": 7, "FND-CFI": 72},
    "G-ROTH": {"FND-AIX": 7, "FND-GTF": 22, "FND-HCI": 12, "FND-CET": 9, "FND-CFI": 50},
    "B-TX": {"FND-AIX": 3, "FND-GTF": 10, "FND-DIR": 4, "FND-HCI": 7, "FND-CET": 5, "FND-MUN": 40, "FND-CFI": 31},
    "B-IRA": {"FND-AIX": 3, "FND-GTF": 10, "FND-HCI": 7, "FND-CFI": 80},
    "B-ROTH": {"FND-AIX": 5, "FND-GTF": 18, "FND-HCI": 10, "FND-CET": 7, "FND-CFI": 60},
    "B-EX": {"FND-AIX": 3, "FND-GTF": 10, "FND-DIR": 4, "FND-HCI": 7, "FND-CET": 5, "FND-CFI": 71},
    "C-TX": {"FND-GTF": 6, "FND-HCI": 5, "FND-CET": 5, "FND-MUN": 50, "FND-CFI": 34},
    "C-IRA": {"FND-GTF": 6, "FND-HCI": 5, "FND-CFI": 89},
    "C-EX": {"FND-GTF": 6, "FND-HCI": 5, "FND-CET": 5, "FND-CFI": 84},
}

# Opening positions on 2024-12-31, USD thousands at that day's NAV. The 2026-09-30 snapshot is NOT typed in:
# it is produced by replaying every flow forward in shares (see _simulate) and pricing at the daily NAV.
_OPENING_K = {
    # Hartwell Family Trust - client-directed technology overweight since 2023
    "ACC-1001": {"FND-AIX": 2150, "FND-GTF": 6600, "FND-DIR": 1800, "FND-HCI": 2100, "FND-CET": 1200,
                 "FND-MUN": 9300, "FND-CFI": 6900},
    "ACC-1002": {"FND-AIX": 330, "FND-GTF": 1020, "FND-HCI": 420, "FND-CFI": 4230},
    # Okafor Family Office - technology overweight
    "ACC-1004": {"FND-AIX": 2600, "FND-GTF": 7950, "FND-DIR": 2160, "FND-HCI": 2520, "FND-CET": 1800,
                 "FND-MUN": 11150, "FND-CFI": 7850},
    # Bellamy Foundation - balanced, fossil-fuel exclusion (no Energy Infrastructure Fund)
    "ACC-1006": {"FND-AIX": 630, "FND-GTF": 2100, "FND-DIR": 840, "FND-HCI": 1470, "FND-CET": 2100, "FND-CFI": 13860},
    # Lindqvist Revocable Trust - balanced
    "ACC-1007": {"FND-AIX": 270, "FND-GTF": 900, "FND-DIR": 360, "FND-HCI": 630, "FND-CET": 450,
                 "FND-MUN": 3600, "FND-CFI": 2790},
    "ACC-1008": {"FND-AIX": 60, "FND-GTF": 200, "FND-HCI": 140, "FND-CFI": 1600},
    # Ramirez Household - balanced
    "ACC-1009": {"FND-AIX": 140, "FND-GTF": 460, "FND-DIR": 180, "FND-HCI": 320, "FND-CET": 230,
                 "FND-MUN": 1840, "FND-CFI": 1430},
    "ACC-1010": {"FND-AIX": 50, "FND-GTF": 150, "FND-HCI": 100, "FND-CFI": 1200},
    "ACC-1011": {"FND-AIX": 20, "FND-GTF": 60, "FND-HCI": 40, "FND-CFI": 480},
    # Whitman Charitable Foundation - conservative
    "ACC-1012": {"FND-GTF": 750, "FND-HCI": 630, "FND-CET": 620, "FND-CFI": 10500},
    # Delgado Family Trust - conservative
    "ACC-1015": {"FND-GTF": 380, "FND-HCI": 320, "FND-CET": 320, "FND-MUN": 3200, "FND-CFI": 2180},
    "ACC-1016": {"FND-GTF": 120, "FND-HCI": 100, "FND-CFI": 1780},
    # St. Aldric School Endowment - balanced
    "ACC-1017": {"FND-AIX": 440, "FND-GTF": 1450, "FND-DIR": 580, "FND-HCI": 1020, "FND-CET": 730, "FND-CFI": 10280},
    # Sterling-Hayes Family Office - technology overweight
    "ACC-1020": {"FND-AIX": 1800, "FND-GTF": 5500, "FND-DIR": 1500, "FND-HCI": 1750, "FND-CET": 1000,
                 "FND-MUN": 7750, "FND-CFI": 5700},
    # Volkov Household - conservative
    "ACC-1022": {"FND-GTF": 180, "FND-HCI": 150, "FND-CET": 150, "FND-MUN": 1620, "FND-CFI": 900},
    "ACC-1023": {"FND-GTF": 50, "FND-HCI": 50, "FND-CFI": 700},
}
# accounts built from a model sleeve: id -> (model key, size in USD thousands)
_MODEL_OPENING = {
    "ACC-1013": ("G-TX", 17000),                                    # Nakamura Family Partners (plus PCF II)
    "ACC-1018": ("G-TX", 7000), "ACC-1019": ("G-IRA", 2200),        # Brennan Household
    "ACC-1024": ("G-TX", 3200), "ACC-1025": ("G-IRA", 1450), "ACC-1026": ("G-ROTH", 210),
    "ACC-1027": ("B-TX", 21500), "ACC-1028": ("B-IRA", 3900),
    "ACC-1029": ("G-TX", 1850), "ACC-1030": ("G-IRA", 920), "ACC-1031": ("G-ROTH", 145),
    "ACC-1032": ("B-TX", 4600), "ACC-1033": ("B-IRA", 1750),
    "ACC-1034": ("B-EX", 8300),
    "ACC-1035": ("G-TX", 2700), "ACC-1036": ("G-IRA", 1180),
    "ACC-1037": ("B-TX", 2350), "ACC-1038": ("B-IRA", 1020),
    "ACC-1039": ("C-EX", 11800),
    "ACC-1040": ("G-TX", 1260), "ACC-1041": ("G-IRA", 640), "ACC-1042": ("G-ROTH", 118),
    "ACC-1043": ("B-TX", 5900), "ACC-1044": ("B-IRA", 2150),
    "ACC-1045": ("G-TX", 24800), "ACC-1046": ("G-IRA", 4300),
    "ACC-1047": ("B-EX", 9600),
    "ACC-1048": ("C-TX", 2050), "ACC-1049": ("C-IRA", 1380),
    "ACC-1050": ("B-TX", 6700),
    "ACC-1051": ("G-TX", 980), "ACC-1052": ("G-ROTH", 96),
    "ACC-1053": ("G-TX", 3850), "ACC-1054": ("G-IRA", 1640), "ACC-1055": ("G-ROTH", 188),
    "ACC-1056": ("B-TX", 2900), "ACC-1057": ("B-IRA", 1240),
    "ACC-1058": ("C-EX", 4700),
    "ACC-1059": ("C-TX", 3400), "ACC-1060": ("C-IRA", 2250), "ACC-1061": ("C-IRA", 890),
    "ACC-1062": ("G-TX", 19700),
    "ACC-1063": ("B-TX", 1680), "ACC-1064": ("B-IRA", 1120),
    "ACC-1065": ("G-TX", 1420), "ACC-1066": ("G-ROTH", 132),
    "ACC-1067": ("B-TX", 16400), "ACC-1068": ("B-IRA", 3050),
    "ACC-1069": ("B-TX", 1540), "ACC-1070": ("B-IRA", 760),
    "ACC-1071": ("B-EX", 13200),
    "ACC-1072": ("G-TX", 2150), "ACC-1073": ("G-IRA", 870),
    "ACC-1074": ("C-TX", 5300), "ACC-1075": ("C-IRA", 1960),
    "ACC-1076": ("B-TX", 2480), "ACC-1077": ("B-IRA", 940), "ACC-1078": ("B-ROTH", 165),
}
OPENING_DATE = PRICING_START
# cost basis / opening value, by fund (accounts opened years ago carry gains; bonds sit near par)
_GAIN_RANGES = {"FND-AIX": (1.18, 1.62), "FND-GTF": (1.35, 2.40), "FND-DIR": (0.96, 1.22), "FND-HCI": (1.08, 1.55),
                "FND-CET": (0.82, 1.15), "FND-EIF": (1.05, 1.30), "FND-CYB": (1.05, 1.40), "FND-CFI": (0.93, 1.02),
                "FND-MUN": (0.95, 1.03)}


def _opening_values() -> dict[str, dict[str, float]]:
    """Opening market values (USD, 2024-12-31): design values with a small, deterministic dispersion."""
    design: dict[str, dict[str, float]] = {aid: {f: v * 1000.0 for f, v in fs.items()} for aid, fs in _OPENING_K.items()}
    for aid, (model, size_k) in _MODEL_OPENING.items():
        design[aid] = {f: size_k * 1000.0 * pct / 100.0 for f, pct in _MODEL_WEIGHTS[model].items()}
    out = {}
    for aid, funds in design.items():
        out[aid] = {}
        for fid, value in funds.items():
            rng = random.Random(_seed("open", aid, fid))
            out[aid][fid] = value * (1.0 + rng.uniform(-0.025, 0.025))
    return out


# =============================================================================
# COMMITTEES, DECISIONS, MEETINGS
# =============================================================================
DECISIONS = [
    {"id": "IC-2025-014", "date": "2025-06-18", "title": "Initiate Energy Infrastructure Fund at 5% in Growth and Balanced models",
     "status": "Approved", "vote": "7-0", "direction": "increase",
     "summary": "Adds the Arbor Peak Energy Infrastructure Fund to Growth and Balanced models at a 5% weight, funded from fixed income.",
     "affects_funds": ["FND-EIF"], "affects_companies": [], "affects_themes": ["THM-ENERGY"]},
    {"id": "IC-2025-019", "date": "2025-11-13", "title": "Add Cybersecurity Leaders Fund at 4% in Growth models",
     "status": "Approved", "vote": "7-0", "direction": "increase",
     "summary": "Adds the Arbor Peak Cybersecurity Leaders Fund to Growth models at 4%, funded from the Global Technology Fund.",
     "affects_funds": ["FND-CYB", "FND-GTF"], "affects_companies": [], "affects_themes": ["THM-CYBER"]},
    {"id": "IC-2026-004", "date": "2026-02-12", "title": "Increase AI Infrastructure Fund allocation: Growth 5% to 8%, Balanced 3% to 5%",
     "status": "Approved", "vote": "6-1", "direction": "increase",
     "summary": "Raises the AI Infrastructure Fund model weight on sustained demand for GPU capacity through 2027. "
                "Funded from fixed income. Chief Risk Officer dissented on concentration grounds.",
     "affects_funds": ["FND-AIX"], "affects_companies": ["CMP-NVDA"], "affects_themes": ["THM-AI"]},
    {"id": "IC-2026-005", "date": "2026-03-12", "title": "Shorten Core Fixed Income duration target from 6.0 to 5.0 years",
     "status": "Approved", "vote": "7-0", "direction": "decrease",
     "summary": "Reduces duration risk in the Core Fixed Income Fund given rate-path uncertainty. No client trades required.",
     "affects_funds": ["FND-CFI"], "affects_companies": [], "affects_themes": ["THM-RATES"]},
    {"id": "IC-2026-006", "date": "2026-04-09", "title": "Approve $45M senior secured term loan to Cobalt Ridge Data Centers",
     "status": "Approved", "vote": "7-0", "direction": "increase",
     "summary": "Private Credit Fund II commits $45M to a senior secured term loan financing a GPU-dense data center campus. "
                "Funded by capital call #6.",
     "affects_funds": ["FND-PC2"], "affects_companies": ["CMP-COBALT"], "affects_themes": ["THM-CREDIT", "THM-AI"]},
    {"id": "IC-2026-008", "date": "2026-05-14", "title": "Increase Energy Infrastructure Fund allocation from 5% to 7% on data center power demand",
     "status": "Approved", "vote": "7-0", "direction": "increase",
     "summary": "Raises the Energy Infrastructure Fund weight in Growth and Balanced models; thesis is natural gas demand "
                "from new data center power generation. Clients with fossil-fuel exclusions are exempt.",
     "affects_funds": ["FND-EIF"], "affects_companies": [], "affects_themes": ["THM-ENERGY", "THM-POWER"]},
    {"id": "IC-2026-011", "date": "2026-07-16", "title": "Adopt 10% single-name cap and reduce technology overlap for clients above the 15% AI look-through guideline",
     "status": "Approved", "vote": "7-0", "direction": "decrease",
     "summary": "Caps any single company at 10% of a thematic fund (Nvidia trimmed from 12% to 10% in the AI Infrastructure "
                "Fund) and reduces Global Technology Fund holdings for clients whose look-through AI Infrastructure "
                "exposure exceeds 15%.",
     "affects_funds": ["FND-AIX", "FND-GTF"], "affects_companies": ["CMP-NVDA"], "affects_themes": ["THM-AI"]},
    {"id": "IC-2026-013", "date": "2026-09-10", "title": "Approve $20M senior secured facility to Polar Loop Cooling Systems; maintain 8% AI Infrastructure allocation",
     "status": "Approved", "vote": "7-0", "direction": "increase",
     "summary": "Private Credit Fund II commits $20M to a liquid-cooling manufacturer serving AI data centers, funded by "
                "capital call #7. AI Infrastructure model weight maintained at 8%.",
     "affects_funds": ["FND-PC2", "FND-AIX"], "affects_companies": ["CMP-POLARLOOP"], "affects_themes": ["THM-CREDIT", "THM-AI"]},
]


def decision_by_id(did: str) -> dict:
    for d in DECISIONS:
        if d["id"] == did:
            return d
    raise KeyError(did)


IC_MEMBERS = ["Douglas Whitfield", "Meredith Calloway", "Brendan Kessler", "Rebecca Thornton", "Marcus Bell",
              "Elena Vasquez", "Philip Ashworth"]

# key, date, title, meeting_type, committee_id, participants (names), client_id, decision_ids
_MEETINGS = [
    ("M00", "2025-06-18", "Investment Committee Meeting", "Investment Committee", "COM-IC", IC_MEMBERS, None, ["IC-2025-014"]),
    ("M01", "2025-11-13", "Investment Committee Meeting", "Investment Committee", "COM-IC", IC_MEMBERS + ["Daniel Cho"], None, ["IC-2025-019"]),
    ("M02", "2025-12-11", "Investment Committee Meeting", "Investment Committee", "COM-IC", IC_MEMBERS + ["Stephen Albrecht"], None, []),
    ("M03", "2026-01-15", "Investment Committee Meeting", "Investment Committee", "COM-IC", ["Douglas Whitfield", "Meredith Calloway"], None, []),
    ("M04", "2026-02-12", "Investment Committee Meeting", "Investment Committee", "COM-IC", IC_MEMBERS + ["Olivia Grant"], None, ["IC-2026-004"]),
    ("M05", "2026-03-12", "Investment Committee Meeting", "Investment Committee", "COM-IC", IC_MEMBERS + ["Stephen Albrecht"], None, ["IC-2026-005"]),
    ("M06", "2026-04-09", "Investment Committee Meeting", "Investment Committee", "COM-IC", IC_MEMBERS + ["Priya Nair"], None, ["IC-2026-006"]),
    ("M07", "2026-05-14", "Investment Committee Meeting", "Investment Committee", "COM-IC", IC_MEMBERS + ["Natalie Brooks", "Wade Pruitt"], None, ["IC-2026-008"]),
    ("M08", "2026-07-16", "Investment Committee Meeting", "Investment Committee", "COM-IC", IC_MEMBERS + ["Lucas Meyer"], None, ["IC-2026-011"]),
    ("M09", "2026-09-10", "Investment Committee Meeting", "Investment Committee", "COM-IC", IC_MEMBERS + ["Priya Nair"], None, ["IC-2026-013"]),
    ("M10", "2025-12-04", "Technology Research Team Meeting", "Research", None, ["Meredith Calloway", "Arjun Mehta", "Brendan Kessler", "Olivia Grant"], None, []),
    ("M11", "2026-01-22", "Power & Energy Research Meeting", "Research", None, ["Natalie Brooks", "Rebecca Thornton", "Wade Pruitt", "Leah Goldberg"], None, []),
    ("M12", "2026-06-18", "Look-Through Exposure Review", "Risk Review", "COM-RISK", ["Elena Vasquez", "Lucas Meyer", "Douglas Whitfield", "Philip Ashworth", "Grace Holloway"], None, []),
    ("M13", "2026-08-20", "Cybersecurity Research Meeting", "Research", None, ["Daniel Cho", "Olivia Grant"], None, []),
    ("M14", "2026-03-03", "Hartwell Family Trust Quarterly Review", "Client Review", None, ["Michael Torres", "Robert Hartwell", "Elaine Hartwell"], "C-001", []),
    ("M15", "2026-08-12", "Hartwell Family Trust Mid-Year Review", "Client Review", None, ["Michael Torres", "Robert Hartwell", "Elaine Hartwell", "Brendan Kessler"], "C-001", []),
    ("M16", "2026-02-24", "Okafor Family Office Portfolio Review", "Client Review", None, ["Jennifer Walsh", "Chinedu Okafor", "Ngozi Okafor"], "C-002", []),
    ("M17", "2026-05-20", "Bellamy Foundation Investment Review", "Client Review", None, ["Andre Washington", "Margaret Bellamy"], "C-003", []),
    ("M18", "2025-11-19", "Ramirez Household Planning Meeting", "Client Review", None, ["Victor Alvarez", "Carlos Ramirez", "Sofia Ramirez"], "C-005", []),
    ("M19", "2026-03-18", "Cobalt Ridge Data Centers Management Meeting", "Due Diligence", None, ["Marcus Bell", "Priya Nair", "Owen Fitzgerald", "Alicia Moreno"], None, []),
    ("M20", "2026-08-27", "Polar Loop Cooling Systems Management Meeting", "Due Diligence", None, ["Priya Nair", "Marcus Bell", "Henrik Larsen"], None, []),
]


def meetings() -> list[dict]:
    out = []
    for key, d, title, mtype, committee, participants, client_id, decisions in _MEETINGS:
        out.append({"key": key, "id": meeting_id(d, title), "date": d, "title": title, "meeting_type": mtype,
                    "committee_id": committee, "participants": list(participants), "client_id": client_id,
                    "decision_ids": list(decisions)})
    return out


def meeting_by_key(key: str) -> dict:
    for m in meetings():
        if m["key"] == key:
            return m
    raise KeyError(key)


# =============================================================================
# FLOWS - forward simulation in shares from the opening positions
# =============================================================================
FLAGGED_OVERLAP_CLIENTS = ["C-001", "C-002", "C-011"]          # above the AI look-through guideline in June 2026
OVERLAP_TARGET_PCT = 13.0
_OVERLAP_DATES = {"C-001": "2026-08-03", "C-002": "2026-07-29", "C-011": "2026-08-05"}
_CAPITAL_CALLS = {
    # date: (reason, fraction of commitment)
    "2026-04-20": ("PCF II capital call #6 - funds Cobalt Ridge Data Centers term loan (IC-2026-006)", 0.10),
    "2026-09-15": ("PCF II capital call #7 - funds Polar Loop Cooling Systems facility (IC-2026-013)", 0.05),
}
_PC2_DISTRIBUTION_DATES = ["2025-01-15", "2025-04-15", "2025-07-15", "2025-10-15", "2026-01-15", "2026-04-15",
                           "2026-07-15"]
# advisory fees: billed quarterly in advance on the prior quarter-end value, debited from fixed income
_FEE_DATES = {"2025-01-08": ("2024-12-31", "Q1 2025"), "2025-04-08": ("2025-03-31", "Q2 2025"),
              "2025-07-09": ("2025-06-30", "Q3 2025"), "2025-10-08": ("2025-09-30", "Q4 2025"),
              "2026-01-08": ("2025-12-31", "Q1 2026"), "2026-04-08": ("2026-03-31", "Q2 2026"),
              "2026-07-09": ("2026-06-30", "Q3 2026")}
_FEE_TIERS = [(1_000_000, 0.0100), (5_000_000, 0.0080), (10_000_000, 0.0060), (25_000_000, 0.0045),
              (float("inf"), 0.0035)]
INSTITUTIONAL_FEE = 0.0040
# income on bond funds paid to cash instead of reinvested
INCOME_TO_CASH = {"ACC-1015", "ACC-1016", "ACC-1048", "ACC-1049", "ACC-1059", "ACC-1060", "ACC-1061",
                  "ACC-1074", "ACC-1075"}
# systematic flows: account -> (USD, frequency)
_MONTHLY_WITHDRAWALS = {"ACC-1015": 9000, "ACC-1022": 3500, "ACC-1027": 25000, "ACC-1048": 6500,
                        "ACC-1059": 12500, "ACC-1074": 7500}
_QUARTERLY_CONTRIBUTIONS = {"ACC-1018": 10000, "ACC-1024": 15000, "ACC-1029": 20000, "ACC-1035": 15000,
                            "ACC-1040": 12000, "ACC-1051": 10000, "ACC-1053": 25000, "ACC-1065": 9000,
                            "ACC-1072": 18000}
# annual Roth IRA contributions: (2025 amount, 2026 amount); age 50+ includes the catch-up
_ROTH_CONTRIBUTIONS = {"ACC-1011": (7000, 7500), "ACC-1026": (8000, 8600), "ACC-1031": (7000, 7500),
                       "ACC-1042": (7000, 7500), "ACC-1052": (7000, 7500), "ACC-1055": (8000, 8600),
                       "ACC-1066": (7000, 7500), "ACC-1078": (7000, 7500)}
_ROTH_DATES = {"2025": "2025-04-11", "2026": "2026-04-10"}
# required minimum distributions (December 2025): account -> IRS Uniform Lifetime Table divisor
_RMD_DIVISORS = {"ACC-1002": 25.5, "ACC-1008": 23.7, "ACC-1016": 26.5, "ACC-1028": 21.1, "ACC-1049": 24.6,
                 "ACC-1060": 22.9, "ACC-1061": 25.5, "ACC-1075": 19.4}
RMD_DATE = "2025-12-10"
# grants, spending draws and one-off client requests (USD; None = computed from a spending rate)
_ONE_OFF_WITHDRAWALS = [
    ("2025-02-04", "ACC-1012", 575000, "Annual grant distribution"),
    ("2026-02-03", "ACC-1012", 600000, "Annual grant distribution"),
    ("2025-06-10", "ACC-1006", 410000, "Semiannual grant distribution"),
    ("2025-12-09", "ACC-1006", 410000, "Semiannual grant distribution"),
    ("2026-06-09", "ACC-1006", 430000, "Semiannual grant distribution"),
    ("2025-05-13", "ACC-1034", 190000, "Semiannual grant distribution"),
    ("2025-11-12", "ACC-1034", 190000, "Semiannual grant distribution"),
    ("2026-05-12", "ACC-1034", 205000, "Semiannual grant distribution"),
    ("2025-03-11", "ACC-1058", 150000, "Annual operating draw"),
    ("2026-03-10", "ACC-1058", 150000, "Annual operating draw"),
    ("2025-08-12", "ACC-1009", 85000, "Client withdrawal - university tuition"),
    ("2026-08-11", "ACC-1009", 88500, "Client withdrawal - university tuition"),
    ("2025-05-20", "ACC-1018", 40000, "Client withdrawal"),
    ("2026-03-24", "ACC-1013", 250000, "Client withdrawal"),
    ("2025-11-18", "ACC-1043", 60000, "Client withdrawal"),
    ("2025-04-22", "ACC-1062", 750000, "Client withdrawal - partner distribution"),
    ("2026-05-19", "ACC-1032", 45000, "Client withdrawal"),
    ("2025-09-16", "ACC-1056", 30000, "Client withdrawal"),
    ("2026-01-27", "ACC-1069", 22000, "Client withdrawal"),
]
_QUARTERLY_SPENDING = {"ACC-1017": 0.0125, "ACC-1071": 0.01125}          # endowment spending policies
_QUARTERLY_SPENDING_DATES = ["2025-01-10", "2025-04-10", "2025-07-10", "2025-10-10", "2026-01-09", "2026-04-10",
                             "2026-07-10"]
_QUARTERLY_GRANTS = {"ACC-1047": 125000}
_QUARTERLY_GRANT_DATES = ["2025-03-18", "2025-06-17", "2025-09-16", "2025-12-16", "2026-03-17", "2026-06-16",
                          "2026-09-15"]
_UNITRUST_PAYOUTS = {"ACC-1039": ("2025-12-15", 0.05)}
_ONE_OFF_CONTRIBUTIONS = [
    ("2025-03-17", "ACC-1045", 1500000, "Client contribution - proceeds from property sale"),
    ("2026-01-21", "ACC-1067", 650000, "Client contribution"),
    ("2025-10-21", "ACC-1004", 1200000, "Client contribution"),
]

_SIM_CACHE: tuple[list, dict] | None = None


def fund_theme_factor(fund_id: str, theme_id: str, as_of: str) -> float:
    """Fraction of a fund's NAV exposed to the theme (weights x exposure factors), positions held at `as_of`."""
    total = 0.0
    for cid, weight, since in FUND_HOLDINGS[fund_id]:
        if since > as_of:
            continue
        degree = COMPANY_THEMES.get(cid, {}).get(theme_id)
        if degree:
            total += fund_weight(fund_id, cid, weight, as_of) / 100.0 * EXPOSURE_FACTORS[degree]
    return total


def _account_sets() -> dict[str, set[str]]:
    sets: dict[str, set[str]] = {k: set() for k in ("GROWTH_TAXABLE", "GROWTH_IRA", "BALANCED", "BALANCED_WITH_EIF")}
    for a in accounts():
        if a["account_type"] == PRIVATE_ACCOUNT_TYPE:
            continue
        risk = client_by_id(a["client_id"])["risk_profile"]
        retirement = _is_retirement(a["account_type"])
        if risk == "Growth":
            sets["GROWTH_IRA" if retirement else "GROWTH_TAXABLE"].add(a["id"])
        elif risk == "Balanced":
            sets["BALANCED"].add(a["id"])
            if not retirement and a["client_id"] not in FOSSIL_FUEL_EXCLUSION:
                sets["BALANCED_WITH_EIF"].add(a["id"])
    return sets


def _fee_rate(client_id: str, household_value: float) -> float:
    if client_by_id(client_id)["segment"] == "Institutional":
        return INSTITUTIONAL_FEE
    fee, lower = 0.0, 0.0
    for upper, rate in _FEE_TIERS:
        if household_value > lower:
            fee += (min(household_value, upper) - lower) * rate
        lower = upper
    return fee / household_value if household_value else 0.0


def _simulate() -> tuple[list[dict], dict]:
    """Replays every scheduled flow from the opening positions.

    Returns (transaction rows, opening state). Positions are kept in shares; every trade is priced at that
    day's NAV, so dollar amounts carry cents and share quantities three decimals.
    """
    global _SIM_CACHE
    if _SIM_CACHE is not None:
        return _SIM_CACHE
    opening_values = _opening_values()
    shares: dict[str, dict[str, float]] = {}
    cost: dict[str, dict[str, float]] = {}
    for aid, funds in opening_values.items():
        shares[aid], cost[aid] = {}, {}
        for fid, value in funds.items():
            qty = round(value / nav(fid, OPENING_DATE), 3)
            shares[aid][fid] = qty
            lo, hi = _GAIN_RANGES[fid]
            gain = random.Random(_seed("basis", aid, fid)).uniform(lo, hi)
            cost[aid][fid] = round(qty * nav(fid, OPENING_DATE) / gain, 2)
    for aid, commitment in PC2_COMMITMENTS.items():
        called = commitment * PC2_CALLED_BEFORE_2025
        shares[aid] = {"FND-PC2": round(called / 10.0, 4)}
        cost[aid] = {"FND-PC2": float(called)}
    opening = {"shares": {a: dict(f) for a, f in shares.items()}, "cost": {a: dict(f) for a, f in cost.items()}}
    rows: list[dict] = []

    def held(aid: str, fid: str) -> float:
        return shares[aid].get(fid, 0.0)

    def value(aid: str, d: str, fid: str | None = None) -> float:
        funds = [fid] if fid else list(shares[aid])
        return sum(shares[aid].get(f, 0.0) * nav(f, d) for f in funds)

    def add_row(d, aid, fid, ttype, qty, price, amount, reason):
        settle = d if fid == "FND-PC2" or ttype in ("INCOME", "DISTRIBUTION") else next_business_day(d)
        rows.append({"date": d, "settle_date": settle, "account_id": aid, "fund_id": fid, "txn_type": ttype,
                     "shares": qty, "price": price, "amount_usd": round(amount, 2), "order_reason": reason})

    def buy(d, aid, fid, amount, reason, ttype="BUY"):
        amount = round(amount, 2)
        if amount <= 0:
            return
        price = nav(fid, d)
        qty = round(amount / price, 4 if fid == "FND-PC2" else 3)
        shares[aid][fid] = held(aid, fid) + qty
        cost[aid][fid] = cost[aid].get(fid, 0.0) + amount
        add_row(d, aid, fid, ttype, qty, price, amount, reason)

    def sell(d, aid, fid, amount, reason, ttype="SELL"):
        amount = round(amount, 2)
        if amount <= 0:
            return
        price = nav(fid, d)
        qty = round(amount / price, 3)
        have = held(aid, fid)
        if qty > have + 1e-6:
            raise ValueError(f"oversell {aid} {fid} {amount} on {d} (holds {have * price:,.2f})")
        if have - qty < 0.0005:
            qty = have
        cost[aid][fid] = cost[aid].get(fid, 0.0) * (1.0 - qty / have) if have else 0.0
        shares[aid][fid] = have - qty
        if shares[aid][fid] < 0.0005:
            del shares[aid][fid]
            cost[aid].pop(fid, None)
        add_row(d, aid, fid, ttype, qty, price, amount, reason)

    def fi_source(aid: str) -> str:
        if held(aid, "FND-MUN") > 0:
            return "FND-MUN"
        return "FND-CFI"

    def invest_pro_rata(d, aid, amount, reason):
        liquid = {f: value(aid, d, f) for f in shares[aid] if f != "FND-PC2"}
        total = sum(liquid.values())
        allocated, funds = 0.0, sorted(liquid)
        for i, fid in enumerate(funds):
            part = round(amount * liquid[fid] / total, 2) if i < len(funds) - 1 else round(amount - allocated, 2)
            allocated += part
            buy(d, aid, fid, part, reason)

    events: list[tuple] = []          # (date, priority, seq, fn)

    def schedule(d, prio, fn):
        events.append((d, prio, len(events), fn))

    sets = _account_sets()

    def model_trade(accts, window, pct, buy_fund, reason, funding):
        days = business_days(*window)
        for i, aid in enumerate(sorted(accts)):
            d = days[(i * 3) % len(days)]

            def fn(d=d, aid=aid):
                amount = round(value(aid, d) * pct(aid), 2)
                buy(d, aid, buy_fund, amount, reason)
                sell(d, aid, funding(aid), amount, reason)
            schedule(d, 1, fn)

    # ---- IC decisions implemented through model trades ----------------------
    gt, gi, bal, bal_eif = sets["GROWTH_TAXABLE"], sets["GROWTH_IRA"], sets["BALANCED"], sets["BALANCED_WITH_EIF"]
    model_trade(gt | bal_eif, ("2025-06-23", "2025-07-03"), lambda a: 0.05, "FND-EIF",
                "Model change per IC-2025-014 (initiate Energy Infrastructure Fund)", fi_source)
    model_trade(gt, ("2025-11-17", "2025-11-26"), lambda a: 0.04, "FND-CYB",
                "Model change per IC-2025-019 (add Cybersecurity Leaders Fund)", lambda a: "FND-GTF")
    model_trade(gt | gi | bal, ("2026-02-17", "2026-03-06"), lambda a: 0.03 if a in gt | gi else 0.02, "FND-AIX",
                "Model rebalance per IC-2026-004 (increase AI Infrastructure allocation)", fi_source)
    model_trade(gt | bal_eif, ("2026-06-01", "2026-06-12"), lambda a: 0.02, "FND-EIF",
                "Model rebalance per IC-2026-008 (increase Energy Infrastructure allocation)", fi_source)

    # ---- IC-2026-011: overlap reduction sized to bring flagged clients to the target ----------
    for cid, d in _OVERLAP_DATES.items():
        def fn(d=d, cid=cid):
            total = exposed = 0.0
            for a in accounts_for_client(cid):
                for fid in shares[a["id"]]:
                    v = value(a["id"], d, fid)
                    total += v
                    exposed += v * fund_theme_factor(fid, "THM-AI", d)
            excess = exposed - total * OVERLAP_TARGET_PCT / 100.0
            if excess <= 0:
                return
            gtf_accts = [a["id"] for a in accounts_for_client(cid) if held(a["id"], "FND-GTF") > 0]
            gtf_vals = {a: value(a, d, "FND-GTF") for a in gtf_accts}
            gtf_total = sum(gtf_vals.values())
            taxable_share = sum(v for a, v in gtf_vals.items() if a in gt) / gtf_total
            f_gtf, f_cyb = fund_theme_factor("FND-GTF", "THM-AI", d), fund_theme_factor("FND-CYB", "THM-AI", d)
            sell_total = excess / (f_gtf - 0.4 * taxable_share * f_cyb)
            reason = "Overlap reduction per IC-2026-011 (AI look-through guideline)"
            for aid in gtf_accts:
                amount = round(sell_total * gtf_vals[aid] / gtf_total, 2)
                sell(d, aid, "FND-GTF", amount, reason)
                if aid in gt:
                    cyb = round(amount * 0.4, 2)
                    buy(d, aid, "FND-CYB", cyb, reason)
                    buy(d, aid, "FND-CFI", amount - cyb, reason)
                else:
                    buy(d, aid, "FND-CFI", amount, reason)
        schedule(d, 2, fn)

    # ---- Private Credit Fund II capital calls and distributions ----------------
    for d, (reason, fraction) in _CAPITAL_CALLS.items():
        for aid, commitment in PC2_COMMITMENTS.items():
            schedule(d, 3, lambda d=d, aid=aid, c=commitment, f=fraction, r=reason:
                     buy(d, aid, "FND-PC2", c * f, r, ttype="CAPITAL_CALL"))
    for d in _PC2_DISTRIBUTION_DATES:
        for aid in sorted(PC2_COMMITMENTS):
            def fn(d=d, aid=aid):
                per_unit = round(nav("FND-PC2", d) * PC2_DISTRIBUTION_RATE, 4)
                add_row(d, aid, "FND-PC2", "DISTRIBUTION", "", per_unit, held(aid, "FND-PC2") * per_unit,
                        f"PCF II quarterly income distribution (${per_unit:.4f}/unit)")
            schedule(d, 3, fn)

    # ---- fund distributions ---------------------------------------------------
    for fid, dists in _DISTRIBUTIONS.items():
        for d, kind, inc, cg in dists:
            def fn(d=d, fid=fid, kind=kind, inc=inc, cg=cg):
                before = nav(fid, _prev_business_day(d))
                inc_ps, cg_ps = round(before * inc, 4), round(before * cg, 4)
                if kind == "Year-end":
                    parts = [f"income ${inc_ps:.4f}/sh"] if inc_ps else []
                    parts += [f"LT capital gain ${cg_ps:.4f}/sh"] if cg_ps else []
                    reason = f"Year-end distribution reinvested ({', '.join(parts)})"
                else:
                    reason = f"Quarterly income dividend reinvested (${inc_ps:.4f}/sh)"
                for aid in sorted(shares):
                    if held(aid, fid) > 0:
                        buy(d, aid, fid, held(aid, fid) * (inc_ps + cg_ps), reason)
            schedule(d, 5, fn)
    for year, month in [(y, m) for y in (2025, 2026) for m in range(1, 13)]:
        d = _last_business_day_of_month(year, month)
        if d > AS_OF_DATE.isoformat():
            continue
        for fid, rates in _MONTHLY_INCOME.items():
            def fn(d=d, fid=fid, rate=rates[str(year)]):
                for aid in sorted(shares):
                    if held(aid, fid) <= 0:
                        continue
                    amount = held(aid, fid) * rate
                    if aid in INCOME_TO_CASH:
                        add_row(d, aid, fid, "INCOME", "", rate, amount,
                                f"Monthly income dividend paid to cash (${rate:.4f}/sh)")
                    else:
                        buy(d, aid, fid, amount, f"Monthly income dividend reinvested (${rate:.4f}/sh)")
            schedule(d, 5, fn)

    # ---- advisory fees ----------------------------------------------------------
    for d, (basis_date, quarter) in _FEE_DATES.items():
        def fn(d=d, basis_date=basis_date, quarter=quarter):
            by_client: dict[str, list[str]] = {}
            for a in accounts():
                if a["account_type"] != PRIVATE_ACCOUNT_TYPE:
                    by_client.setdefault(a["client_id"], []).append(a["id"])
            for cid, aids in sorted(by_client.items()):
                household = sum(value(a, basis_date) for a in aids)
                rate = _fee_rate(cid, household)
                for aid in aids:
                    fee = value(aid, basis_date) * rate / 4.0
                    sell(d, aid, fi_source(aid), fee, f"Advisory fee {quarter} ({rate * 100:.3f}% annual)",
                         ttype="FEE")
        schedule(d, 0, fn)

    # ---- client cash flows ------------------------------------------------------
    months = [(y, m) for y in (2025, 2026) for m in range(1, 13)]
    for aid, amount in _MONTHLY_WITHDRAWALS.items():
        for y, m in months:
            d = on_or_after(f"{y}-{m:02d}-15")
            if d <= AS_OF_DATE.isoformat():
                schedule(d, 4, lambda d=d, aid=aid, amt=amount:
                         sell(d, aid, fi_source(aid), amt, "Systematic monthly withdrawal"))
    for aid, amount in _QUARTERLY_CONTRIBUTIONS.items():
        for y, m in months:
            if m in (1, 4, 7, 10):
                d = on_or_after(f"{y}-{m:02d}-20")
                if d <= AS_OF_DATE.isoformat():
                    schedule(d, 4, lambda d=d, aid=aid, amt=amount:
                             invest_pro_rata(d, aid, amt, "Quarterly client contribution"))
    for aid, (amt25, amt26) in _ROTH_CONTRIBUTIONS.items():
        for year, amt in (("2025", amt25), ("2026", amt26)):
            d = _ROTH_DATES[year]
            schedule(d, 4, lambda d=d, aid=aid, amt=amt, y=year:
                     invest_pro_rata(d, aid, amt, f"Roth IRA contribution for tax year {y}"))
    for aid, divisor in _RMD_DIVISORS.items():
        def fn(aid=aid, divisor=divisor):
            prior_year_end = _value_at_open(opening, aid)          # December 31, 2024 balance
            sell(RMD_DATE, aid, "FND-CFI", prior_year_end / divisor, "Required minimum distribution (2025)")
        schedule(RMD_DATE, 4, fn)
    for d, aid, amount, reason in _ONE_OFF_WITHDRAWALS:
        schedule(d, 4, lambda d=d, aid=aid, amt=amount, r=reason: sell(d, aid, fi_source(aid), amt, r))
    for d, aid, amount, reason in _ONE_OFF_CONTRIBUTIONS:
        schedule(d, 4, lambda d=d, aid=aid, amt=amount, r=reason: invest_pro_rata(d, aid, amt, r))
    for aid, rate in _QUARTERLY_SPENDING.items():
        for d in _QUARTERLY_SPENDING_DATES:
            schedule(d, 4, lambda d=d, aid=aid, rate=rate:
                     sell(d, aid, fi_source(aid), round(value(aid, _prev_business_day(d)) * rate, 0),
                          "Quarterly endowment spending draw"))
    for aid, amount in _QUARTERLY_GRANTS.items():
        for d in _QUARTERLY_GRANT_DATES:
            schedule(d, 4, lambda d=d, aid=aid, amt=amount: sell(d, aid, fi_source(aid), amt, "Quarterly grant draw"))
    for aid, (d, rate) in _UNITRUST_PAYOUTS.items():
        schedule(d, 4, lambda d=d, aid=aid, rate=rate:
                 sell(d, aid, fi_source(aid), round(value(aid, _prev_business_day(d)) * rate, 0),
                      "Annual unitrust payout"))

    for d, _prio, _seq, fn in sorted(events, key=lambda e: (e[0], e[1], e[2])):
        if d <= AS_OF_DATE.isoformat():
            fn()
    rows.sort(key=lambda r: (r["date"], r["account_id"], r["fund_id"], r["txn_type"]))
    for i, r in enumerate(rows, start=1):
        r["id"] = f"TXN-{i:06d}"
    _SIM_CACHE = (rows, opening)
    return _SIM_CACHE


def _prev_business_day(iso: str) -> str:
    d = date.fromisoformat(iso) - timedelta(days=1)
    while not is_business_day(d.isoformat()):
        d -= timedelta(days=1)
    return d.isoformat()


def _value_at_open(opening: dict, aid: str) -> float:
    return sum(q * nav(f, OPENING_DATE) for f, q in opening["shares"][aid].items())


def transactions() -> list[dict]:
    """All trades and cash flows (USD), deterministic."""
    return [dict(r) for r in _simulate()[0]]


_SHARE_EFFECT = {"BUY": 1, "SELL": -1, "FEE": -1, "CAPITAL_CALL": 1, "DISTRIBUTION": 0, "INCOME": 0}


def shares_at(as_of: str) -> dict[str, dict[str, float]]:
    """Shares held per account and fund at the close of `as_of`."""
    rows, opening = _simulate()
    pos = {aid: dict(funds) for aid, funds in opening["shares"].items()}
    for t in rows:
        if t["date"] <= as_of and _SHARE_EFFECT[t["txn_type"]]:
            fund = pos[t["account_id"]]
            fund[t["fund_id"]] = fund.get(t["fund_id"], 0.0) + _SHARE_EFFECT[t["txn_type"]] * t["shares"]
    return pos


def positions_at(as_of: str) -> dict[str, dict[str, float]]:
    """Account positions (USD market value) at the close of `as_of`."""
    return {aid: {fid: qty * nav(fid, as_of) for fid, qty in funds.items() if qty > 0.0005}
            for aid, funds in shares_at(as_of).items()}


def holdings() -> list[dict]:
    """Account -> fund positions as of AS_OF_DATE, with share quantity, NAV, market value and cost basis."""
    rows, opening = _simulate()
    as_of = AS_OF_DATE.isoformat()
    qty = shares_at(as_of)
    cost = {aid: dict(funds) for aid, funds in opening["cost"].items()}
    held = {aid: dict(funds) for aid, funds in opening["shares"].items()}
    for t in rows:                         # average-cost basis, replayed
        effect = _SHARE_EFFECT[t["txn_type"]]
        if not effect:
            continue
        aid, fid = t["account_id"], t["fund_id"]
        have = held[aid].get(fid, 0.0)
        if effect > 0:
            cost[aid][fid] = cost[aid].get(fid, 0.0) + t["amount_usd"]
        elif have:
            cost[aid][fid] = cost[aid].get(fid, 0.0) * max(0.0, 1.0 - t["shares"] / have)
        held[aid][fid] = have + effect * t["shares"]
    out = []
    for aid in sorted(qty):
        account_value = sum(q * nav(f, as_of) for f, q in qty[aid].items() if q > 0.0005)
        for fid in sorted(qty[aid]):
            q = qty[aid][fid]
            if q <= 0.0005:
                continue
            price = nav(fid, as_of)
            mv = round(q * price, 2)
            basis = round(cost[aid].get(fid, 0.0), 2)
            out.append({"account_id": aid, "fund_id": fid, "ticker": fund_by_id(fid)["ticker"],
                        "shares": round(q, 4 if fid == "FND-PC2" else 3), "price": price, "market_value": mv,
                        "cost_basis": basis, "unrealized_gain_loss": round(mv - basis, 2),
                        "pct_of_account": round(100.0 * mv / account_value, 2), "as_of": as_of})
    return out


def look_through_exposure(client_id: str, theme_id: str = "THM-AI", as_of: str | None = None) -> dict:
    as_of = as_of or AS_OF_DATE.isoformat()
    pos = positions_at(as_of)
    total = exposed = 0.0
    for acct in accounts_for_client(client_id):
        for fid, value in pos.get(acct["id"], {}).items():
            total += value
            exposed += value * fund_theme_factor(fid, theme_id, as_of)
    return {"client_id": client_id, "theme_id": theme_id, "as_of": as_of, "total_usd": round(total),
            "exposed_usd": round(exposed), "pct": round(100.0 * exposed / total, 1) if total else 0.0}
