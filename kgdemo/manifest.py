"""Document manifest: the ~100 unstructured documents behind the demo.

Each DocSpec fixes the facts a document must carry (date, people, header fields,
which entities it must mention, and a brief of what it says). Header fields are
rendered from the spec; only the free-text body is authored. Every number quoted
in a brief is computed from `world` so documents and structured data agree.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import world as w

DOC_TYPES = ["Meeting Notes", "IC Memo", "Research Report", "Due Diligence", "Email", "CRM Note"]
SOURCE_SYSTEM = {
    "Meeting Notes": "Document Management",
    "IC Memo": "Document Management",
    "Research Report": "Research Portal",
    "Due Diligence": "Deal Management",
    "Email": "Email",
    "CRM Note": "CRM",
}
AVOID_AI = ["AI infrastructure", "AI infra", "AI build-out", "AI buildout", "artificial intelligence infrastructure"]
ADVISOR_NAMES = ["Michael Torres", "Jennifer Walsh", "Andre Washington", "Laura Chen", "Victor Alvarez", "Lauren Pacheco"]
IC_EMAIL_LIST = ["Douglas Whitfield", "Meredith Calloway", "Brendan Kessler", "Rebecca Thornton", "Elena Vasquez", "Philip Ashworth"]


@dataclass
class DocSpec:
    doc_id: str
    doc_type: str
    date: str
    title: str
    authors: list[str] = field(default_factory=list)      # research / memo / DD preparers / CRM owner
    meeting_key: str | None = None                         # meeting notes -> world meeting
    sender: str | None = None                              # email
    to: list[str] = field(default_factory=list)
    cc: list[str] = field(default_factory=list)
    client_id: str | None = None                           # CRM note subject client
    crm_type: str | None = None
    borrower: str | None = None                            # due diligence subject company
    decision_ref: str | None = None                        # IC memo proposes
    for_meeting_date: str | None = None                    # IC memo target meeting
    cites: list[str] = field(default_factory=list)         # doc ids rendered in a references section
    must_mention: list[str] = field(default_factory=list)  # entity surface forms the body must contain
    avoid_phrases: list[str] = field(default_factory=list)
    brief: str = ""
    words: tuple[int, int] = (150, 350)
    fixed_body: str | None = None                          # body supplied verbatim (no authoring)

    @property
    def source_system(self) -> str:
        return SOURCE_SYSTEM[self.doc_type]


# ---------------------------------------------------------------------------
# facts computed from the world model
# ---------------------------------------------------------------------------
def usd(x: float, decimals: int = 2) -> str:
    if x >= 1_000_000:
        return f"${x / 1_000_000:.{decimals}f} million"
    return f"${x:,.0f}"


def _trades(reason_part: str, txn_type: str | None = None, fund: str | None = None, account: str | None = None):
    out = []
    for t in w.transactions():
        if reason_part in t["order_reason"] and (txn_type is None or t["txn_type"] == txn_type) \
                and (fund is None or t["fund_id"] == fund) and (account is None or t["account_id"] == account):
            out.append(t)
    return out


def _one(reason_part, txn_type, fund, account) -> dict:
    rows = _trades(reason_part, txn_type, fund, account)
    if len(rows) != 1:
        raise ValueError(f"expected one trade for {reason_part} {txn_type} {fund} {account}, got {len(rows)}")
    return rows[0]


def _fmt_day(iso: str) -> str:
    from datetime import date
    d = date.fromisoformat(iso)
    return f"{d.strftime('%B')} {d.day}"


def facts() -> dict:
    f: dict = {}
    ic004 = _trades("IC-2026-004", "BUY", "FND-AIX")
    f["ic004_accounts"] = len(ic004)
    f["ic004_clients"] = len({w.account_by_id(t["account_id"])["client_id"] for t in ic004})
    f["ic004_total"] = usd(sum(t["amount_usd"] for t in ic004), 1)
    ic008 = _trades("IC-2026-008", "BUY", "FND-EIF")
    f["ic008_accounts"] = len(ic008)
    f["ic008_total"] = usd(sum(t["amount_usd"] for t in ic008), 1)
    ic019 = _trades("IC-2025-019", "BUY", "FND-CYB")
    f["ic019_accounts"] = len(ic019)
    # Hartwell trades
    f["hw_aix_trust"] = _one("IC-2026-004", "BUY", "FND-AIX", "ACC-1001")
    f["hw_aix_ira"] = _one("IC-2026-004", "BUY", "FND-AIX", "ACC-1002")
    f["hw_eif_2025"] = _one("IC-2025-014", "BUY", "FND-EIF", "ACC-1001")
    f["hw_gtf_sell_trust"] = _one("IC-2026-011", "SELL", "FND-GTF", "ACC-1001")
    f["hw_gtf_sell_ira"] = _one("IC-2026-011", "SELL", "FND-GTF", "ACC-1002")
    f["hw_cyb_buy"] = _one("IC-2026-011", "BUY", "FND-CYB", "ACC-1001")
    f["hw_cfi_buy_trust"] = _one("IC-2026-011", "BUY", "FND-CFI", "ACC-1001")
    f["hw_call6"] = _one("IC-2026-006", "CAPITAL_CALL", "FND-PC2", "ACC-1003")
    f["hw_call7"] = _one("IC-2026-013", "CAPITAL_CALL", "FND-PC2", "ACC-1003")
    # other clients
    f["ok_aix"] = _one("IC-2026-004", "BUY", "FND-AIX", "ACC-1004")
    f["ok_gtf_sell"] = _one("IC-2026-011", "SELL", "FND-GTF", "ACC-1004")
    f["sh_aix"] = _one("IC-2026-004", "BUY", "FND-AIX", "ACC-1020")
    f["sh_gtf_sell"] = _one("IC-2026-011", "SELL", "FND-GTF", "ACC-1020")
    f["sh_call6"] = _one("IC-2026-006", "CAPITAL_CALL", "FND-PC2", "ACC-1021")
    f["nk_call6"] = _one("IC-2026-006", "CAPITAL_CALL", "FND-PC2", "ACC-1014")
    f["nk_call7"] = _one("IC-2026-013", "CAPITAL_CALL", "FND-PC2", "ACC-1014")
    f["lq_aix_trust"] = _one("IC-2026-004", "BUY", "FND-AIX", "ACC-1007")
    f["lq_aix_ira"] = _one("IC-2026-004", "BUY", "FND-AIX", "ACC-1008")
    f["sa_aix"] = _one("IC-2026-004", "BUY", "FND-AIX", "ACC-1017")
    f["br_aix_joint"] = _one("IC-2026-004", "BUY", "FND-AIX", "ACC-1018")
    f["br_aix_ira"] = _one("IC-2026-004", "BUY", "FND-AIX", "ACC-1019")
    f["br_eif"] = _one("IC-2026-008", "BUY", "FND-EIF", "ACC-1018")
    f["rm_eif"] = _one("IC-2026-008", "BUY", "FND-EIF", "ACC-1009")
    f["dg_rmd"] = [t for t in w.transactions() if t["account_id"] == "ACC-1016"
                   and t["order_reason"].startswith("Required minimum distribution")][0]
    # look-through exposure (June 15 analysis, after trades, now)
    for key, cid in [("hw", "C-001"), ("ok", "C-002"), ("sh", "C-011"), ("nk", "C-007")]:
        f[f"{key}_jun"] = w.look_through_exposure(cid, "THM-AI", "2026-06-15")["pct"]
        f[f"{key}_aug"] = w.look_through_exposure(cid, "THM-AI", "2026-08-10")["pct"]
    return f


F = facts()
HW_SELL_TOTAL = F["hw_gtf_sell_trust"]["amount_usd"] + F["hw_gtf_sell_ira"]["amount_usd"]


# ---------------------------------------------------------------------------
# constructors
# ---------------------------------------------------------------------------
def MN(doc_id, meeting_key, must, brief, avoid=(), words=(170, 360), fixed_body=None) -> DocSpec:
    m = w.meeting_by_key(meeting_key)
    return DocSpec(doc_id, "Meeting Notes", m["date"], m["title"], meeting_key=meeting_key,
                   must_mention=list(must), avoid_phrases=list(avoid), brief=brief, words=words,
                   fixed_body=fixed_body)


def ICM(doc_id, date, title, authors, decision, meeting_date, cites, must, brief, avoid=(), words=(380, 620)):
    return DocSpec(doc_id, "IC Memo", date, title, authors=list(authors), decision_ref=decision,
                   for_meeting_date=meeting_date, cites=list(cites), must_mention=list(must),
                   avoid_phrases=list(avoid), brief=brief, words=words)


def RR(doc_id, date, title, authors, must, brief, avoid=(), words=(420, 720)):
    return DocSpec(doc_id, "Research Report", date, title, authors=list(authors), must_mention=list(must),
                   avoid_phrases=list(avoid), brief=brief, words=words)


def DD(doc_id, date, title, authors, borrower, must, brief, avoid=(), words=(420, 720)):
    return DocSpec(doc_id, "Due Diligence", date, title, authors=list(authors), borrower=borrower,
                   must_mention=list(must), avoid_phrases=list(avoid), brief=brief, words=words)


def EM(doc_id, date, sender, to, cc, subject, must, brief, avoid=(), words=(90, 240)):
    return DocSpec(doc_id, "Email", date, subject, sender=sender, to=list(to), cc=list(cc),
                   must_mention=list(must), avoid_phrases=list(avoid), brief=brief, words=words)


def CRM(doc_id, date, client_id, owner, crm_type, subject, must, brief, avoid=(), words=(50, 150)):
    return DocSpec(doc_id, "CRM Note", date, subject, authors=[owner], client_id=client_id, crm_type=crm_type,
                   must_mention=list(must), avoid_phrases=list(avoid), brief=brief, words=words)


HERO_BODY = (
    "Discussion:\n"
    "We remain bullish on Nvidia and other AI infrastructure providers.\n"
    "The technology team believes demand for GPU capacity will continue through 2027."
)


def doc_specs() -> list[DocSpec]:
    f = F
    hw_jun, ok_jun, sh_jun, nk_jun = f["hw_jun"], f["ok_jun"], f["sh_jun"], f["nk_jun"]
    specs: list[DocSpec] = [
        # =================================================================== MEETING NOTES
        MN("DOC-MN-01", "M00",
           ["Energy Infrastructure Fund", "IC-2025-014", "Williams Companies", "Kinder Morgan", "natural gas pipelines",
            "fee-based cash flows", "Bellamy Foundation"],
           "Investment Committee. Rebecca Thornton presents adding the Arbor Peak Energy Infrastructure Fund at 5% to Growth "
           "and Balanced models, funded from fixed income: midstream natural gas pipelines with fee-based cash flows and "
           "inflation-linked tariffs; top holdings Williams Companies, Kinder Morgan, Energy Transfer. Philip Ashworth notes "
           "the Bellamy Foundation's investment policy excludes fossil-fuel infrastructure, so it will not receive the "
           "allocation. Decision: IC-2025-014 approved 7-0. Action items: Trevor Iwasaki to implement trades in late June "
           "and early July 2025; advisors to explain the change to clients."),
        MN("DOC-MN-02", "M01",
           ["Cybersecurity Leaders Fund", "IC-2025-019", "CrowdStrike", "Palo Alto Networks", "platform consolidation",
            "Global Technology Fund", "GPU demand"],
           "Investment Committee. Daniel Cho presents adding the Arbor Peak Cybersecurity Leaders Fund at 4% to Growth "
           "models, funded from the Global Technology Fund (which falls from 16% to 12%). Thesis: platform consolidation "
           "and zero trust adoption; key holdings CrowdStrike, Palo Alto Networks, Zscaler. Decision: IC-2025-019 "
           "approved 7-0; trades November 17-26. Separately Meredith Calloway previews her forthcoming report on GPU demand: "
           "hyperscaler GPU demand still exceeds supply; full report later this month. No AI decision was taken."),
        MN("DOC-MN-03", "M03", [], "", fixed_body=HERO_BODY),
        MN("DOC-MN-04", "M02",
           ["Nvidia", "TSMC", "hyperscaler capex", "GPU capacity", "AI infrastructure", "rate cuts",
            "Core Fixed Income Fund", "Global Technology Fund", "AI Infrastructure Fund"],
           "Investment Committee, two agenda items. (1) Stephen Albrecht's fixed income update: rate cuts likely to come more "
           "slowly than the market expects; no change yet to the Core Fixed Income Fund duration, revisit in Q1. "
           "(2) Meredith Calloway walks through her November report 'GPU Demand Outlook 2026-2027: Capacity Remains Tight': GPU "
           "capacity remains tight, hyperscaler capex still rising, TSMC advanced packaging is the bottleneck; "
           "constructive on Nvidia. Douglas Whitfield asks to revisit at the January meeting whether the AI infrastructure "
           "allocation (AI Infrastructure Fund, 5% of Growth models) is large enough. Elena Vasquez flags that Nvidia "
           "already appears in both the AI Infrastructure Fund and the Global Technology Fund. No decision."),
        MN("DOC-MN-05", "M04",
           ["IC-2026-004", "AI Infrastructure Fund", "Nvidia", "Broadcom", "TSMC", "GPU capacity", "hyperscaler capex",
            "Elena Vasquez", "Meredith Calloway", "Brendan Kessler", "Global Technology Fund", "Vertiv"],
           "Investment Committee. Meredith Calloway and Brendan Kessler present their memo 'Proposal: Increase AI Infrastructure "
           "Allocation in Growth and Balanced Models': demand for GPU capacity expected to continue through 2027; "
           "hyperscaler capex plans raised again; supply constraints in TSMC advanced packaging; beneficiaries include "
           "Nvidia, Broadcom, TSMC and power/cooling names such as Vertiv. Olivia Grant notes overlap with the Global "
           "Technology Fund (Nvidia about 8% there). Decision: IC-2026-004 approved 6-1 - AI Infrastructure Fund model "
           "weight Growth 5% to 8%, Balanced 3% to 5%, funded from fixed income (Municipal Income Fund in taxable "
           "accounts, Core Fixed Income Fund otherwise). Elena Vasquez dissents on concentration grounds and asks for a "
           "look-through exposure review by mid-year. Action items: Philip Ashworth to send advisor talking points; Trevor "
           "Iwasaki to rebalance February 17 to March 6; risk team to build look-through exposure reporting."),
        MN("DOC-MN-06", "M05",
           ["IC-2026-005", "Core Fixed Income Fund", "duration target", "Treasury yields", "Cobalt Ridge Data Centers",
            "Private Credit Fund II", "senior secured term loan", "IC-2026-004"],
           "Investment Committee. (1) Stephen Albrecht proposes shortening the Core Fixed Income Fund duration target from 6.0 "
           "to 5.0 years given rate-path uncertainty and volatile Treasury yields; approved 7-0 as IC-2026-005, "
           "implemented inside the fund with no client trades. (2) Marcus Bell previews a potential $45 million senior "
           "secured term loan to Cobalt Ridge Data Centers for Private Credit Fund II; due diligence under way, site "
           "visit on March 18 and an independent power assessment pending; formal credit approval expected in April. "
           "(3) Philip Ashworth confirms the IC-2026-004 rebalancing finished on March 6."),
        MN("DOC-MN-07", "M06",
           ["IC-2026-006", "Cobalt Ridge Data Centers", "Private Credit Fund II", "senior secured term loan",
            "GPU clusters", "power purchase agreement", "Ostrander Power Constructors", "Priya Nair", "covenants",
            "Pemberton Grid Consulting", "Nvidia"],
           "Investment Committee. Marcus Bell and Priya Nair present the credit approval memo for Cobalt Ridge Data "
           "Centers: $45 million senior secured term loan, 5 years, SOFR + 575 bps, first lien on a 120 MW data center "
           "campus in West Texas leased to tenants deploying Nvidia-based GPU clusters; 15-year power purchase agreement; "
           "new substation being built by Ostrander Power Constructors (an existing Private Credit Fund II borrower). Risks: "
           "construction delay, interconnection timing, tenant concentration; mitigants: maintenance covenants and a "
           "debt service reserve. Pemberton Grid Consulting's independent power assessment is supportive. Decision: IC-2026-006 "
           "approved 7-0, funded by Private Credit Fund II capital call #6 on April 20. Elena Vasquez notes this adds "
           "data center exposure for clients invested in Private Credit Fund II."),
        MN("DOC-MN-08", "M07",
           ["IC-2026-008", "Energy Infrastructure Fund", "power demand", "gas-fired generation",
            "natural gas pipelines", "Williams Companies", "Kinder Morgan", "Bellamy Foundation", "Constellation Energy"],
           "Investment Committee. Rebecca Thornton, Natalie Brooks and Wade Pruitt propose raising the Energy Infrastructure "
           "Fund from 5% to 7% in Growth and Balanced models. Thesis: data center power demand is driving new gas-fired "
           "generation, which needs natural gas pipelines - Williams Companies and Kinder Morgan are positioned; power "
           "producers already in the fund (Constellation Energy, Vistra) benefit from tighter power markets. They cite the "
           "January report 'Powering AI' and the April report on the data center power trade. Decision: IC-2026-008 "
           "approved 7-0; the Bellamy Foundation is exempt because of its fossil-fuel exclusion. Rebalancing June 1-12."),
        MN("DOC-MN-09", "M08",
           ["IC-2026-011", "Nvidia", "AI Infrastructure Fund", "Global Technology Fund", "Hartwell Family Trust",
            "Okafor Family Office", "Sterling-Hayes Family Office", "Lucas Meyer", "Cybersecurity Leaders Fund"],
           f"Investment Committee. Elena Vasquez and Lucas Meyer present the risk memo on look-through AI concentration. "
           f"As of June 15, three clients exceeded the 15% look-through AI Infrastructure guideline: Hartwell Family "
           f"Trust {hw_jun}%, Okafor Family Office {ok_jun}%, Sterling-Hayes Family Office {sh_jun}%. Main driver: "
           f"client-directed overweights in the Global Technology Fund overlapping with the AI Infrastructure Fund, plus "
           f"Private Credit Fund II's data center loan. Meredith Calloway's July Nvidia position review recommends trimming Nvidia "
           f"from 12% to 10% of the AI Infrastructure Fund. Decision: IC-2026-011 approved 7-0 - (a) 10% single-name cap "
           f"in thematic funds; (b) for clients above the guideline, sell Global Technology Fund to bring look-through "
           f"exposure to about 13%, reinvesting in the Cybersecurity Leaders Fund and Core Fixed Income Fund; trades "
           f"July 27 to August 7. Philip Ashworth will notify advisors."),
        MN("DOC-MN-10", "M09",
           ["IC-2026-013", "Polar Loop Cooling Systems", "liquid cooling", "Cobalt Ridge Data Centers",
            "senior secured facility", "AI Infrastructure Fund", "GPU capacity", "rack density"],
           "Investment Committee. (1) Marcus Bell and Priya Nair present a $20 million senior secured facility to Polar "
           "Loop Cooling Systems, a direct-to-chip liquid cooling manufacturer whose customers include Cobalt Ridge Data "
           "Centers; backlog driven by rising rack density in AI data centers. (2) Meredith Calloway's quarterly review: GPU "
           "capacity still tight and demand expected to hold through 2027; the committee keeps the AI Infrastructure "
           "Fund model weight at 8%. Decision: IC-2026-013 approved 7-0 covering both items; the facility is funded by "
           "capital call #7 on September 15. Elena Vasquez confirms the flagged clients are back below the 15% "
           "guideline after the August trades and that the capital call adds roughly one percentage point for clients "
           "in Private Credit Fund II, keeping them below 15%."),
        MN("DOC-MN-11", "M10",
           ["Nvidia", "Micron", "TSMC", "Broadcom", "high-bandwidth memory", "custom silicon", "GPU supply",
            "AI Infrastructure Fund", "Global Technology Fund", "Arista Networks", "Marvell"],
           "Technology research working session. Arjun Mehta: high-bandwidth memory (HBM) supply is sold out through 2026 "
           "and Micron is gaining share; TSMC advanced packaging capacity is the binding constraint on GPU supply. Meredith "
           "Calloway: Nvidia remains the leader; Broadcom's custom silicon programs for hyperscalers are a second growth "
           "vector (topic of Arjun's December report). Brendan Kessler is considering adding to Marvell and Arista Networks in "
           "the AI Infrastructure Fund. Olivia Grant: the Global Technology Fund already holds about 8% in Nvidia - note "
           "the overlap. Action: Meredith Calloway to present the GPU outlook at the December 11 Investment Committee."),
        MN("DOC-MN-12", "M11",
           ["Leah Goldberg", "Pemberton Grid Consulting", "power demand", "interconnection queue", "gas-fired generation",
            "Constellation Energy", "Vistra", "Williams Companies", "AI data centers", "Kinder Morgan"],
           "Power and energy research meeting with an outside expert. Natalie Brooks hosts Leah Goldberg of Pemberton "
           "Advisory. Electricity demand from AI data centers is now the main source of US load growth; interconnection "
           "queues in Texas and the Mid-Atlantic stretch three to five years, so many campuses pair grid power with "
           "on-site gas-fired generation; nuclear restarts help at the margin. Implications: Constellation Energy and "
           "Vistra benefit from tighter power markets; Williams Companies and Kinder Morgan benefit from incremental gas "
           "demand. Rebecca Thornton wants this to inform a possible Energy Infrastructure Fund proposal. Action items: "
           "Natalie Brooks to extend her January 'Powering AI' estimates; Wade Pruitt to start a midstream note.",
           avoid=AVOID_AI),
        MN("DOC-MN-13", "M12",
           ["Hartwell Family Trust", "Okafor Family Office", "Sterling-Hayes Family Office", "Nakamura Family Partners",
            "Nvidia", "AI Infrastructure Fund", "Global Technology Fund", "Private Credit Fund II",
            "Cobalt Ridge Data Centers", "Michael Torres", "Jennifer Walsh"],
           f"Risk Committee review of the first look-through exposure report, requested when Elena Vasquez dissented on "
           f"IC-2026-004 in February. Method: client fund positions x fund holdings x company theme exposure (high 1.0, "
           f"medium 0.5, low 0.25). As of June 15: Hartwell Family Trust {hw_jun}%, Okafor Family Office {ok_jun}%, "
           f"Sterling-Hayes Family Office {sh_jun}% exceed the 15% guideline; next highest Nakamura Family Partners "
           f"{nk_jun}%. Drivers: client-directed technology overweights in the Global Technology Fund overlapping with the "
           f"AI Infrastructure Fund (Nvidia is the largest single-name look-through exposure) plus Private Credit Fund "
           f"II's loan to Cobalt Ridge Data Centers. Grace Holloway asks advisors to document client consent for the "
           f"overweights. Action items: Elena Vasquez and Lucas Meyer to bring a risk memo to the July 16 Investment "
           f"Committee; Philip Ashworth to brief Michael Torres and Jennifer Walsh."),
        MN("DOC-MN-14", "M13",
           ["CrowdStrike", "Zscaler", "Palo Alto Networks", "Fortinet", "zero trust", "platform consolidation",
            "Cybersecurity Leaders Fund", "IC-2026-011"],
           "Cybersecurity research meeting. Daniel Cho and Olivia Grant review the Cybersecurity Leaders Fund after "
           "inflows from the IC-2026-011 overlap reduction in early August (three family office and trust clients). "
           "Platform consolidation continues to favor CrowdStrike and Palo Alto Networks; Zscaler benefits from zero "
           "trust adoption; Fortinet firewall refresh cycle. Action: Daniel Cho to publish a mid-year cybersecurity "
           "update."),
        MN("DOC-MN-15", "M14",
           ["Hartwell Family Trust", "AI Infrastructure Fund", "IC-2026-004", "Nvidia", "Global Technology Fund",
            "Private Credit Fund II", "Robert Hartwell", "Elaine Hartwell", "Municipal Income Fund"],
           f"Client quarterly review. Michael Torres meets Robert and Elaine Hartwell. He explains the February rebalance "
           f"under IC-2026-004: about {usd(f['hw_aix_trust']['amount_usd'])} added to the AI Infrastructure Fund in the "
           f"trust's taxable account on {_fmt_day(f['hw_aix_trust']['date'])} and {usd(f['hw_aix_ira']['amount_usd'])} in "
           f"Robert's IRA on {_fmt_day(f['hw_aix_ira']['date'])}, funded from the Municipal Income Fund and Core Fixed "
           f"Income Fund. Elaine Hartwell asks how much Nvidia they own in total, since it sits in both the AI "
           f"Infrastructure Fund and the Global Technology Fund; Michael Torres commits to request a look-through "
           f"analysis from the risk team. Robert Hartwell supports the AI view. Michael mentions Private Credit Fund II "
           f"may issue a capital call in the spring. Action items."),
        MN("DOC-MN-16", "M15",
           ["Hartwell Family Trust", "IC-2026-011", "Global Technology Fund", "AI Infrastructure Fund", "Nvidia",
            "Cobalt Ridge Data Centers", "Private Credit Fund II", "Cybersecurity Leaders Fund", "Brendan Kessler",
            "power demand", "Core Fixed Income Fund"],
           f"Client mid-year review. Michael Torres and Brendan Kessler meet Robert and Elaine Hartwell. They review the "
           f"{_fmt_day(f['hw_gtf_sell_trust']['date'])} overlap reduction under IC-2026-011: sold "
           f"{usd(f['hw_gtf_sell_trust']['amount_usd'])} of the Global Technology Fund in the trust account and "
           f"{usd(f['hw_gtf_sell_ira']['amount_usd'])} in Robert's IRA; proceeds into the Cybersecurity Leaders Fund and "
           f"Core Fixed Income Fund; look-through AI exposure moved from {hw_jun}% in June to about {f['hw_aug']}%. Brendan "
           f"Kessler explains Nvidia was trimmed to 10% of the AI Infrastructure Fund under the new single-name cap and the "
           f"team is still constructive on GPU demand. Elaine Hartwell asks about Private Credit Fund II's loan to Cobalt "
           f"Ridge Data Centers and power risk; they explain the senior secured structure, the long-term power purchase "
           f"agreement and that power demand from data centers remains strong. Next review in Q4."),
        MN("DOC-MN-17", "M16",
           ["Okafor Family Office", "AI Infrastructure Fund", "IC-2026-004", "Private Credit Fund II", "Chinedu Okafor",
            "Ngozi Okafor", "hyperscaler capex"],
           f"Client portfolio review. Jennifer Walsh meets Chinedu and Ngozi Okafor. Explains IC-2026-004 and the AI "
           f"Infrastructure Fund purchase of about {usd(f['ok_aix']['amount_usd'])} scheduled for "
           f"{_fmt_day(f['ok_aix']['date'])} in the taxable account. Chinedu Okafor is enthusiastic and cites hyperscaler "
           f"capex headlines; Ngozi Okafor asks about liquidity and wants private credit commitments to Private Credit "
           f"Fund II kept steady. They discuss the family office's client-directed technology overweight (since 2023). "
           f"Action: send an updated investment policy statement acknowledging the overweight."),
        MN("DOC-MN-18", "M17",
           ["Bellamy Foundation", "Margaret Bellamy", "Energy Infrastructure Fund", "Clean Energy Transition Fund",
            "battery storage", "NextEra Energy", "First Solar", "IC-2026-008", "AI Infrastructure Fund",
            "Constellation Energy", "Quanta Services"],
           "Client investment review. Andre Washington meets Margaret Bellamy. Confirms the foundation is exempt from "
           "IC-2026-008 (Energy Infrastructure Fund increase) because its investment policy excludes fossil-fuel "
           "infrastructure; its energy allocation stays in the Clean Energy Transition Fund (NextEra Energy, First Solar, "
           "Fluence Energy; battery storage and grid modernization). Margaret Bellamy asks whether the foundation has "
           "indirect exposure to data center power demand; Andre explains the AI Infrastructure Fund holds Constellation "
           "Energy and Quanta Services, which are power and grid names rather than fossil-fuel pipelines. Action: provide "
           "a holdings look-through report."),
        MN("DOC-MN-19", "M18",
           ["Ramirez Household", "Carlos Ramirez", "Sofia Ramirez", "Municipal Income Fund", "municipal bonds",
            "rate cuts", "Healthcare Innovation Fund", "Eli Lilly", "GLP-1"],
           "Client planning meeting. Victor Alvarez meets Carlos and Sofia Ramirez: college funding for their daughter, "
           "tax-exempt income from the Municipal Income Fund, and what expected rate cuts mean for municipal bonds. Sofia "
           "asks about GLP-1 drug news; Victor explains the Healthcare Innovation Fund holds Eli Lilly and Novo Nordisk. "
           "No changes; next meeting in the spring."),
        MN("DOC-MN-20", "M19",
           ["Cobalt Ridge Data Centers", "Owen Fitzgerald", "Alicia Moreno", "GPU clusters", "rack density",
            "Polar Loop Cooling Systems", "Ostrander Power Constructors", "power purchase agreement", "interconnection queue",
            "Nvidia"],
           "Due diligence site visit and management meeting in West Texas. Owen Fitzgerald: 120 MW campus, phase 1 (60 "
           "MW) to be energized in Q3 2026; tenants are an investment-grade hyperscale tenant and a GPU cloud operator "
           "deploying Nvidia-based GPU clusters at rack densities above 100 kW, which require direct-to-chip liquid "
           "cooling supplied by Polar Loop Cooling Systems. Alicia Moreno: financing plan and the $45 million senior "
           "secured term loan request, a 15-year power purchase agreement, a substation being built by Ostrander "
           "Services, and a secured interconnection queue position. Priya Nair's follow-ups: tenant letters of intent, "
           "construction budget, PPA terms. Marcus Bell positive.",
           avoid=AVOID_AI),
        MN("DOC-MN-21", "M20",
           ["Polar Loop Cooling Systems", "Henrik Larsen", "liquid cooling", "rack density", "Cobalt Ridge Data Centers",
            "Vertiv", "senior secured facility"],
           "Due diligence management meeting. Priya Nair and Marcus Bell meet CEO Henrik Larsen. Polar Loop makes "
           "direct-to-chip liquid cooling systems; backlog grew sharply as AI data centers move to higher rack density; "
           "its largest customer is Cobalt Ridge Data Centers; it competes with Vertiv on large deployments but wins on "
           "lead times. It requests a $20 million senior secured facility to add a second manufacturing line. Risks: "
           "customer concentration, component supply. Next: credit due diligence report by end of August; Investment "
           "Committee on September 10.",
           avoid=AVOID_AI),

        # =================================================================== IC MEMOS
        ICM("DOC-ICM-01", "2025-06-11", "Proposal: Initiate Energy Infrastructure Fund in Growth and Balanced Models",
            ["Rebecca Thornton"], "IC-2025-014", "2025-06-18", [],
            ["Energy Infrastructure Fund", "Williams Companies", "Kinder Morgan", "Energy Transfer",
             "Enterprise Products Partners", "fee-based cash flows", "natural gas pipelines", "Bellamy Foundation",
             "LNG exports"],
            "Proposes adding the Arbor Peak Energy Infrastructure Fund at 5% in Growth and Balanced models, funded from "
            "fixed income. Rationale: fee-based cash flows, inflation-linked tariffs, natural gas pipeline volume growth "
            "from LNG exports and power generation; holdings include Williams Companies, Kinder Morgan, Energy Transfer, "
            "Enterprise Products Partners and Cheniere Energy. Risks: commodity sensitivity, policy, ESG exclusions - the "
            "Bellamy Foundation's investment policy excludes fossil-fuel infrastructure and will be exempt. "
            "Implementation: late June and early July 2025."),
        ICM("DOC-ICM-02", "2025-11-06", "Proposal: Add Cybersecurity Leaders Fund to Growth Models",
            ["Daniel Cho", "Olivia Grant"], "IC-2025-019", "2025-11-13", ["DOC-RR-11"],
            ["Cybersecurity Leaders Fund", "Global Technology Fund", "CrowdStrike", "Palo Alto Networks", "Zscaler",
             "Fortinet", "platform consolidation", "zero trust"],
            f"Proposes a 4% allocation to the Arbor Peak Cybersecurity Leaders Fund in Growth models, funded from the "
            f"Global Technology Fund (from 16% to 12% of the model). Rationale: platform consolidation, zero trust "
            f"adoption and resilient cloud security budgets; holdings CrowdStrike, Palo Alto Networks, Zscaler, Fortinet "
            f"and Microsoft. Risks: valuation, competition. Implementation: November 17-26 across "
            f"{f['ic019_accounts']} Growth taxable accounts."),
        ICM("DOC-ICM-03", "2026-02-05", "Proposal: Increase AI Infrastructure Allocation in Growth and Balanced Models",
            ["Meredith Calloway", "Brendan Kessler"], "IC-2026-004", "2026-02-12", ["DOC-RR-01", "DOC-RR-02", "DOC-RR-03", "DOC-RR-04"],
            ["AI Infrastructure Fund", "Nvidia", "Broadcom", "TSMC", "AMD", "Micron", "Vertiv", "GPU capacity",
             "hyperscaler capex", "AI infrastructure", "Global Technology Fund", "Municipal Income Fund",
             "Core Fixed Income Fund", "Arista Networks", "Eaton"],
            f"Recommends raising the AI Infrastructure Fund model weight from 5% to 8% (Growth) and 3% to 5% (Balanced), "
            f"funded from fixed income (Municipal Income Fund in taxable accounts, Core Fixed Income Fund otherwise). "
            f"Thesis: demand for GPU capacity will continue through 2027, as discussed at the January 15 Investment "
            f"Committee; hyperscaler capex plans rose again; bottlenecks are shifting to advanced packaging, "
            f"high-bandwidth memory (Micron) and AI networking (Broadcom, Arista Networks); power and cooling "
            f"beneficiaries include Vertiv and Eaton. Nvidia is 12% of the fund. Risks: valuation and concentration - "
            f"Nvidia is also about 8% of the Global Technology Fund, so clients holding both funds have overlapping "
            f"exposure; proposes a mid-year look-through review. Implementation: February 17 to March 6, about "
            f"{f['ic004_accounts']} accounts across {f['ic004_clients']} clients, roughly {f['ic004_total']} of purchases."),
        ICM("DOC-ICM-04", "2026-03-05", "Proposal: Shorten Core Fixed Income Duration Target",
            ["Stephen Albrecht"], "IC-2026-005", "2026-03-12", ["DOC-RR-13"],
            ["Core Fixed Income Fund", "duration target", "Treasury yields", "yield curve", "rate cuts",
             "Municipal Income Fund"],
            "Recommends reducing the Core Fixed Income Fund duration target from 6.0 to 5.0 years. Rationale: fewer rate "
            "cuts than the market priced, curve steepening risk, volatile Treasury yields. Implemented inside the fund by "
            "selling long Treasuries; no client account trades. The Municipal Income Fund is unchanged."),
        ICM("DOC-ICM-05", "2026-04-02", "Credit Approval Memo: Cobalt Ridge Data Centers Senior Secured Term Loan",
            ["Marcus Bell", "Priya Nair"], "IC-2026-006", "2026-04-09", ["DOC-DD-01", "DOC-DD-02", "DOC-DD-03"],
            ["Cobalt Ridge Data Centers", "Private Credit Fund II", "senior secured term loan", "SOFR", "covenants",
             "power purchase agreement", "GPU clusters", "Ostrander Power Constructors", "Polar Loop Cooling Systems",
             "Pemberton Grid Consulting", "Nvidia"],
            "Requests approval of a $45 million senior secured term loan (first lien, 5 years, SOFR + 575 bps, 1.5% "
            "original issue discount) to Cobalt Ridge Data Centers to fund phase 1 of a 120 MW West Texas campus. "
            "Collateral: land, buildings, power equipment and assignment of leases. Tenants: an investment-grade "
            "hyperscale tenant (60% of phase 1) and a GPU cloud operator (40%) deploying Nvidia-based GPU clusters. "
            "Power: 15-year power purchase agreement and a substation built by Ostrander Power Constructors (existing portfolio "
            "borrower); Pemberton Grid Consulting's independent power assessment supports the interconnection timeline. "
            "Cooling: direct-to-chip systems from Polar Loop Cooling Systems. Covenants: debt service coverage of at "
            "least 1.35x after stabilization, loan-to-value of at most 65%. Risks: construction delay, tenant "
            "concentration, power timing. Funding: Private Credit Fund II capital call #6 on April 20, 2026. Risk note: "
            "adds data center exposure for clients invested in Private Credit Fund II.",
            avoid=AVOID_AI),
        ICM("DOC-ICM-06", "2026-05-07", "Proposal: Increase Energy Infrastructure Allocation on Data Center Power Demand",
            ["Rebecca Thornton", "Natalie Brooks"], "IC-2026-008", "2026-05-14", ["DOC-RR-03", "DOC-RR-07"],
            ["Energy Infrastructure Fund", "power demand", "gas-fired generation", "natural gas pipelines",
             "Williams Companies", "Kinder Morgan", "Constellation Energy", "Vistra", "AI data centers",
             "Bellamy Foundation", "Energy Transfer"],
            f"Recommends raising the Energy Infrastructure Fund model weight from 5% to 7% in Growth and Balanced models, "
            f"funded from fixed income. Thesis: power demand from AI data centers is driving new gas-fired generation; "
            f"pipeline operators (Williams Companies, Kinder Morgan, Energy Transfer) see contracted volume growth on "
            f"their natural gas pipelines; power producers in the fund (Constellation Energy, Vistra) benefit from higher "
            f"capacity prices. Risks: rate sensitivity, project delays, policy. The Bellamy Foundation is exempt "
            f"(fossil-fuel exclusion). Implementation: June 1-12, about {f['ic008_accounts']} accounts and roughly "
            f"{f['ic008_total']} of purchases."),
        ICM("DOC-ICM-07", "2026-07-09", "Risk Memo: Look-Through AI Concentration and Single-Name Cap",
            ["Elena Vasquez", "Lucas Meyer"], "IC-2026-011", "2026-07-16", ["DOC-RR-09"],
            ["Hartwell Family Trust", "Okafor Family Office", "Sterling-Hayes Family Office", "Nvidia",
             "AI Infrastructure Fund", "Global Technology Fund", "Private Credit Fund II", "Cybersecurity Leaders Fund",
             "Core Fixed Income Fund", "AI infrastructure", "Nakamura Family Partners", "Cobalt Ridge Data Centers"],
            f"Presents the first look-through exposure analysis (as of June 15, 2026). Method: client fund positions x "
            f"fund holdings x company theme exposure (high 1.0, medium 0.5, low 0.25). Three clients exceed the 15% AI "
            f"infrastructure guideline: Hartwell Family Trust {hw_jun}%, Okafor Family Office {ok_jun}%, Sterling-Hayes "
            f"Family Office {sh_jun}%; every other client is below 13% (highest: Nakamura Family Partners {nk_jun}%). "
            f"Drivers: client-directed overweights in the Global Technology Fund overlapping with the AI Infrastructure "
            f"Fund; Nvidia is the largest single-name look-through exposure; Private Credit Fund II's Cobalt Ridge Data "
            f"Centers loan adds data center exposure. Recommendations: (1) a 10% single-name cap in thematic funds - trim "
            f"Nvidia from 12% to 10% of the AI Infrastructure Fund, consistent with Meredith Calloway's July 2 Nvidia position "
            f"review; (2) for clients above the guideline, sell Global Technology Fund to bring exposure to about 13%, "
            f"reinvesting 40% in the Cybersecurity Leaders Fund and 60% in the Core Fixed Income Fund. Estimated sales: "
            f"about {usd(f['ok_gtf_sell']['amount_usd'])} (Okafor), {usd(HW_SELL_TOTAL)} (Hartwell, trust and IRA) and "
            f"{usd(f['sh_gtf_sell']['amount_usd'])} (Sterling-Hayes)."),
        ICM("DOC-ICM-08", "2026-09-03", "Credit Approval Memo: Polar Loop Cooling Systems Senior Secured Facility",
            ["Marcus Bell", "Priya Nair"], "IC-2026-013", "2026-09-10", ["DOC-DD-04", "DOC-RR-08"],
            ["Polar Loop Cooling Systems", "Private Credit Fund II", "senior secured facility", "liquid cooling",
             "rack density", "Cobalt Ridge Data Centers", "Vertiv", "covenants", "Henrik Larsen"],
            "Requests approval of a $20 million senior secured facility (first lien, 4 years, SOFR + 600 bps) to Polar "
            "Loop Cooling Systems to fund a second manufacturing line. Business: direct-to-chip liquid cooling for high "
            "rack density GPU deployments in AI data centers; backlog up strongly in 2026; largest customer is Cobalt "
            "Ridge Data Centers (also a Private Credit Fund II borrower - related exposure noted); competes with Vertiv. "
            "CEO Henrik Larsen. Covenants: minimum liquidity and leverage of at most 3.5x. Risks: customer concentration, "
            "component supply. Funding: capital call #7 on September 15, 2026. Risk note: adds roughly one percentage "
            "point of look-through exposure for clients in Private Credit Fund II; previously flagged clients remain "
            "below the 15% guideline.",
            avoid=AVOID_AI),

        # =================================================================== RESEARCH REPORTS
        RR("DOC-RR-01", "2025-11-20", "GPU Demand Outlook 2026-2027: Capacity Remains Tight", ["Meredith Calloway", "Arjun Mehta"],
           ["Nvidia", "AMD", "TSMC", "Micron", "Broadcom", "GPU capacity", "hyperscaler capex", "high-bandwidth memory",
            "advanced packaging", "AI infrastructure", "inference demand"],
           "Thesis: demand for GPU capacity exceeds supply through 2027. Drivers: hyperscaler capex plans, inference "
           "demand growth, enterprise adoption. Constraints: TSMC advanced packaging (CoWoS) capacity, high-bandwidth "
           "memory supply (Micron among suppliers), and power availability at data centers. Views (the firm's own, "
           "qualitative): Nvidia remains the platform leader; AMD is gaining in inference; Broadcom's custom "
           "accelerators broaden the opportunity; Micron gains HBM share. Risks: a digestion phase, export controls, "
           "valuation. Portfolio implication: supports the AI infrastructure theme and the AI Infrastructure Fund."),
        RR("DOC-RR-02", "2025-12-15", "Custom Silicon and AI Networking: Beyond the GPU", ["Arjun Mehta"],
           ["Broadcom", "Marvell", "Arista Networks", "Nvidia", "custom silicon", "AI networking", "optical interconnects",
            "AI Infrastructure Fund"],
           "Thesis: as AI clusters scale, value shifts toward custom accelerators and networking. Broadcom and Marvell "
           "design custom silicon for hyperscalers; Arista Networks benefits from Ethernet-based AI networking in "
           "back-end clusters; demand for optical interconnects rises. Nvidia remains dominant, including its own "
           "networking. Implication: the AI Infrastructure Fund should diversify beyond GPUs."),
        RR("DOC-RR-03", "2026-01-08", "Powering AI: Data Center Electricity Demand and the Grid", ["Natalie Brooks"],
           ["power demand", "grid interconnection", "gas-fired generation", "nuclear power", "Constellation Energy",
            "Vistra", "GE Vernova", "Eaton", "Vertiv", "Quanta Services", "Williams Companies", "AI data centers",
            "power purchase agreements"],
           "Electricity demand from AI data centers is the fastest-growing source of US load growth. Grid "
           "interconnection queues are long, so developers pair grid supply with on-site gas-fired generation and "
           "long-term power purchase agreements; nuclear power (restarts and uprates) is valuable. Beneficiaries: power "
           "producers Constellation Energy and Vistra; equipment makers GE Vernova (gas turbines), Eaton and Vertiv "
           "(power distribution and cooling); grid construction (Quanta Services); gas pipelines (Williams Companies). "
           "Risks: regulation, rate cases, overbuild.",
           avoid=AVOID_AI),
        RR("DOC-RR-04", "2026-01-29", "Hyperscaler Capex Tracker: Q4 2025", ["Olivia Grant"],
           ["Microsoft", "Alphabet", "Amazon", "Meta", "Oracle", "hyperscaler capex", "AI data centers",
            "inference demand", "GPU supply", "Global Technology Fund"],
           "Quarterly tracker of hyperscaler capital spending plans. Q4 2025 commentary: Microsoft, Alphabet, Amazon, "
           "Meta and Oracle all signaled higher 2026 capex focused on AI data centers; inference demand is accelerating; "
           "GPU supply is still allocated. Describe direction and tone only - do not quote reported dollar figures; any "
           "numbers must be clearly labeled as internal estimates. Implications for the Global Technology Fund and for "
           "suppliers.",
           avoid=AVOID_AI),
        RR("DOC-RR-05", "2026-02-19", "High-Bandwidth Memory: The Next Bottleneck", ["Arjun Mehta"],
           ["Micron", "high-bandwidth memory", "advanced packaging", "TSMC", "Nvidia", "GPU supply"],
           "High-bandwidth memory (HBM) content per accelerator keeps rising and supply is tight; Micron is well "
           "positioned; HBM supply is linked to advanced packaging capacity at TSMC; implications for GPU supply in "
           "2026-2027 and for Nvidia's product cadence.",
           avoid=AVOID_AI),
        RR("DOC-RR-06", "2026-03-26", "Data Center REITs: Colocation Demand from AI Workloads", ["Olivia Grant"],
           ["Equinix", "Digital Realty", "American Tower", "colocation", "AI workloads", "power demand",
            "Digital Infrastructure Real Estate Fund", "data center REITs"],
           "AI workloads are lifting leasing for data center REITs: Equinix (interconnection-rich colocation), Digital "
           "Realty (hyperscale campuses); power availability is now the gating factor for new supply; American Tower is "
           "diversifying into data centers. Implications for the Digital Infrastructure Real Estate Fund."),
        RR("DOC-RR-07", "2026-04-23", "Natural Gas Midstream: The Data Center Power Trade", ["Wade Pruitt"],
           ["Williams Companies", "Kinder Morgan", "Energy Transfer", "Targa Resources", "Cheniere Energy",
            "natural gas pipelines", "gas-fired generation", "power demand", "AI data centers", "fee-based contracts",
            "Energy Infrastructure Fund"],
           "New gas-fired generation built for AI data centers adds natural gas demand. Pipeline expansions by Williams "
           "Companies, Kinder Morgan and Energy Transfer; Targa Resources benefits from gathering and processing "
           "volumes; Cheniere Energy LNG exports compete for supply. Fee-based contracts provide visibility. "
           "Recommendation: overweight midstream within the Energy Infrastructure Fund.",
           avoid=AVOID_AI),
        RR("DOC-RR-08", "2026-06-04", "Liquid Cooling: The Thermal Bottleneck in AI Data Centers", ["Arjun Mehta"],
           ["liquid cooling", "rack density", "Vertiv", "Nvidia", "Polar Loop Cooling Systems", "Eaton",
            "AI data centers"],
           "Next-generation GPU racks exceed the limits of air cooling, so direct-to-chip liquid cooling is becoming "
           "standard as rack density rises. Vertiv is the leading public player; private suppliers such as Polar Loop "
           "Cooling Systems win on lead times; Eaton supplies power distribution. Supply-chain risks: cold plates, pumps.",
           avoid=AVOID_AI),
        RR("DOC-RR-09", "2026-07-02", "Nvidia Position Review: Valuation, Concentration, and Supply", ["Meredith Calloway"],
           ["Nvidia", "AI Infrastructure Fund", "Global Technology Fund", "AMD", "Broadcom", "GPU capacity",
            "AI infrastructure"],
           "Nvidia is 12% of the AI Infrastructure Fund and about 8% of the Global Technology Fund. Fundamentals intact: "
           "GPU capacity is still tight and demand should hold through 2027. But concentration and valuation argue for a "
           "10% single-name cap in the AI Infrastructure Fund, redeploying into AMD, Broadcom and power and cooling "
           "names. Recommendation for the July Investment Committee."),
        RR("DOC-RR-10", "2026-08-06", "Semiconductor Supply Chain: Export Controls and Advanced Packaging", ["Arjun Mehta"],
           ["TSMC", "ASML", "Applied Materials", "Nvidia", "export controls", "advanced packaging", "lithography",
            "semiconductor supply chain", "AI Infrastructure Fund"],
           "Export controls keep evolving; TSMC is expanding capacity (including in Arizona) and advanced packaging; "
           "ASML lithography (EUV) and Applied Materials equipment demand stay strong; implications for Nvidia supply and "
           "for the AI Infrastructure Fund."),
        RR("DOC-RR-11", "2025-11-03", "Cybersecurity Platform Consolidation", ["Daniel Cho"],
           ["CrowdStrike", "Palo Alto Networks", "Zscaler", "Fortinet", "platform consolidation", "zero trust",
            "cloud security", "Cybersecurity Leaders Fund"],
           "Enterprises are consolidating security vendors onto platforms; zero trust and cloud security budgets are "
           "resilient. Views on CrowdStrike, Palo Alto Networks, Zscaler and Fortinet. Supports adding the "
           "Cybersecurity Leaders Fund to Growth models."),
        RR("DOC-RR-12", "2026-02-26", "GLP-1 Therapies: Second-Wave Opportunities", ["Hannah Schultz"],
           ["Eli Lilly", "Novo Nordisk", "GLP-1", "Healthcare Innovation Fund", "Intuitive Surgical",
            "Boston Scientific"],
           "The second wave of GLP-1 therapies: oral formulations and new indications; positioning of Eli Lilly and Novo "
           "Nordisk; second-order effects on medical devices (Intuitive Surgical, Boston Scientific). No fabricated "
           "clinical data. Implications for the Healthcare Innovation Fund."),
        RR("DOC-RR-13", "2026-03-02", "Rate Path and Duration Positioning", ["Stephen Albrecht"],
           ["rate cuts", "yield curve", "Treasury yields", "duration target", "Core Fixed Income Fund",
            "Municipal Income Fund", "municipal bonds"],
           "Fewer rate cuts than the market expects; curve steepening risk; recommend shortening the Core Fixed Income "
           "Fund duration target from 6.0 to 5.0 years; municipal bonds remain attractive for taxable accounts via the "
           "Municipal Income Fund."),
        RR("DOC-RR-14", "2026-05-28", "Grid Modernization and Storage", ["Natalie Brooks"],
           ["NextEra Energy", "First Solar", "Fluence Energy", "GE Vernova", "Quanta Services", "battery storage",
            "grid modernization", "power demand", "Clean Energy Transition Fund"],
           "Grid modernization and battery storage are needed to serve power demand from data centers and "
           "electrification; NextEra Energy, First Solar, Fluence Energy, GE Vernova and Quanta Services are positioned. "
           "Implications for the Clean Energy Transition Fund."),
        RR("DOC-RR-15", "2025-07-15", "AI Infrastructure Primer: Picks and Shovels", ["Meredith Calloway"],
           ["Nvidia", "TSMC", "Broadcom", "Vertiv", "AI infrastructure", "GPU capacity", "AI Infrastructure Fund",
            "Arista Networks"],
           "Primer on the AI infrastructure value chain: compute (Nvidia), foundry (TSMC), networking (Broadcom, Arista "
           "Networks), power and cooling (Vertiv). Why the AI Infrastructure Fund was launched in 2023. Early view that "
           "GPU capacity would stay tight."),

        # =================================================================== DUE DILIGENCE
        DD("DOC-DD-01", "2026-03-20", "Cobalt Ridge Data Centers - Credit Due Diligence Report", ["Priya Nair"],
           "Cobalt Ridge Data Centers",
           ["Cobalt Ridge Data Centers", "Owen Fitzgerald", "Alicia Moreno", "GPU clusters", "power purchase agreement",
            "Ostrander Power Constructors", "Polar Loop Cooling Systems", "senior secured term loan", "covenants", "Nvidia",
            "Marcus Bell"],
           "Credit due diligence for a $45 million senior secured term loan from Private Credit Fund II. Site visit on "
           "March 18 with CEO Owen Fitzgerald and CFO Alicia Moreno. 120 MW West Texas campus, phase 1 (60 MW) energized "
           "Q3 2026; tenants: an investment-grade hyperscale tenant and a GPU cloud operator deploying Nvidia-based GPU "
           "clusters. Power: 15-year power purchase agreement; substation by Ostrander Power Constructors. Cooling: "
           "direct-to-chip systems from Polar Loop Cooling Systems. Structure: first lien, SOFR + 575 bps, maintenance "
           "covenants. Risks and mitigants. Recommendation: proceed to Investment Committee (deal lead Marcus Bell).",
           avoid=AVOID_AI),
        DD("DOC-DD-02", "2026-03-25", "Cobalt Ridge Data Centers - Independent Power Assessment", ["Leah Goldberg"],
           "Cobalt Ridge Data Centers",
           ["Cobalt Ridge Data Centers", "interconnection queue", "power purchase agreement", "gas-fired generation",
            "power demand", "Ostrander Power Constructors", "Pemberton Grid Consulting"],
           "Independent power assessment prepared by Pemberton Grid Consulting for the lenders. Covers the interconnection "
           "queue position and timeline, substation construction by Ostrander Power Constructors, the 15-year power purchase "
           "agreement, on-site gas-fired generation as backup, and the regional power demand outlook. Conclusion: phase "
           "1 energization in Q3 2026 is achievable with moderate risk.",
           avoid=AVOID_AI),
        DD("DOC-DD-03", "2026-03-27", "Cobalt Ridge Data Centers - Legal Due Diligence Summary", ["George Abernathy"],
           "Cobalt Ridge Data Centers",
           ["Cobalt Ridge Data Centers", "Caldwell & Pierce LLP", "first lien", "covenants", "power purchase agreement"],
           "Legal due diligence summary prepared by Caldwell & Pierce LLP: title, permits, lease assignment, "
           "assignability of the power purchase agreement, the first lien collateral package, covenants package, no "
           "material litigation; open items before closing.",
           avoid=AVOID_AI),
        DD("DOC-DD-04", "2026-08-31", "Polar Loop Cooling Systems - Credit Due Diligence Report", ["Priya Nair"],
           "Polar Loop Cooling Systems",
           ["Polar Loop Cooling Systems", "Henrik Larsen", "liquid cooling", "rack density", "Cobalt Ridge Data Centers",
            "Vertiv", "senior secured facility", "covenants"],
           "Credit due diligence for a $20 million senior secured facility. Management meeting on August 27 with CEO "
           "Henrik Larsen. Direct-to-chip liquid cooling for high rack density deployments; backlog growth; customer "
           "concentration (Cobalt Ridge Data Centers is the largest customer); competition from Vertiv; second "
           "manufacturing line plan; covenants (minimum liquidity, leverage of at most 3.5x). Recommendation: proceed to "
           "the September 10 Investment Committee.",
           avoid=AVOID_AI),
        DD("DOC-DD-05", "2026-01-20", "Ostrander Power Constructors - Annual Credit Review", ["Priya Nair"],
           "Ostrander Power Constructors",
           ["Ostrander Power Constructors", "Janet Pryor", "substation capacity", "grid interconnection", "Quanta Services",
            "covenants", "Private Credit Fund II"],
           "Annual review of an existing Private Credit Fund II borrower (since June 2024). Backlog of substation "
           "capacity and grid interconnection work for data centers and utilities; CFO Janet Pryor; Quanta Services is "
           "the main public competitor; covenant compliance confirmed; internal rating upgrade recommended."),
        DD("DOC-DD-06", "2025-12-10", "Larkspur Fiber Networks - Credit Review", ["Priya Nair"],
           "Larkspur Fiber Networks",
           ["Larkspur Fiber Networks", "Sophie Laurent", "fiber networks", "covenants", "Private Credit Fund II"],
           "Credit review of an existing Private Credit Fund II borrower: regional builder of long-haul fiber networks "
           "connecting data centers; CEO Sophie Laurent; covenant compliance; stable outlook."),
        DD("DOC-DD-07", "2026-06-25", "Harborlight Health Partners - Covenant Compliance Review", ["Priya Nair"],
           "Harborlight Health Partners",
           ["Harborlight Health Partners", "Nina Castillo", "covenant compliance", "Private Credit Fund II"],
           "Covenant compliance review of a Private Credit Fund II borrower (physician practice management). CFO Nina "
           "Castillo; first-quarter leverage slightly above plan but within covenants; placed on the watch list."),
        DD("DOC-DD-08", "2026-05-05", "Mesquite Draw Midstream - Annual Credit Review", ["Wade Pruitt", "Priya Nair"],
           "Mesquite Draw Midstream",
           ["Mesquite Draw Midstream", "Ray Dawson", "gas gathering", "gas-fired generation", "Williams Companies",
            "covenants", "Private Credit Fund II", "Targa Resources"],
           "Annual review of a Private Credit Fund II borrower: gas gathering in the Permian Basin, CEO Ray Dawson; "
           "volumes rising with demand from gas-fired generation for data centers; valuation benchmarked against public "
           "midstream peers such as Williams Companies and Targa Resources (no contractual relationship implied); "
           "covenant compliance; recommend maintaining the position."),

        # =================================================================== EMAILS
        EM("DOC-EM-01", "2025-08-14", "Michael Torres", ["Robert Hartwell"], ["Elaine Hartwell"],
           "Energy Infrastructure Fund - new allocation in your trust account",
           ["Energy Infrastructure Fund", "IC-2025-014", "Williams Companies", "Kinder Morgan", "Hartwell Family Trust",
            "Municipal Income Fund"],
           f"Confirms that on {_fmt_day(f['hw_eif_2025']['date'])} the Hartwell Family Trust taxable account added about "
           f"{usd(f['hw_eif_2025']['amount_usd'])} to the Energy Infrastructure Fund under IC-2025-014, funded from the "
           f"Municipal Income Fund; explains the midstream rationale (fee-based cash flows; holdings such as Williams "
           f"Companies and Kinder Morgan). Offers a call."),
        EM("DOC-EM-02", "2025-11-14", "Daniel Cho", ADVISOR_NAMES, ["Philip Ashworth"],
           "IC-2025-019: Cybersecurity Leaders Fund added to Growth models",
           ["IC-2025-019", "Cybersecurity Leaders Fund", "Global Technology Fund", "CrowdStrike", "zero trust"],
           f"Announces approval of IC-2025-019: 4% to the Cybersecurity Leaders Fund in Growth models, funded from the "
           f"Global Technology Fund; trades November 17-26 in {f['ic019_accounts']} Growth taxable accounts; talking points "
           f"(platform consolidation, zero trust, CrowdStrike and Palo Alto Networks)."),
        EM("DOC-EM-03", "2025-12-12", "Meredith Calloway", ["Douglas Whitfield", "Brendan Kessler"], [],
           "GPU demand outlook - follow-ups from yesterday's IC",
           ["Nvidia", "TSMC", "GPU capacity", "AI Infrastructure Fund", "advanced packaging"],
           "Follow-ups to the December 11 Investment Committee: answers questions on TSMC advanced packaging and GPU "
           "capacity constraints; suggests discussing AI Infrastructure Fund sizing at the January 15 meeting; refers to "
           "her November report 'GPU Demand Outlook 2026-2027: Capacity Remains Tight'."),
        EM("DOC-EM-04", "2026-01-16", "Douglas Whitfield", ["Meredith Calloway", "Brendan Kessler"], ["Elena Vasquez"],
           "Follow-up from IC: AI infrastructure proposal",
           ["AI infrastructure", "Nvidia", "GPU capacity", "AI Infrastructure Fund", "Elena Vasquez"],
           "Following yesterday's Investment Committee meeting, where the committee agreed it remains bullish on Nvidia "
           "and other AI infrastructure providers and the technology team expects demand for GPU capacity to continue "
           "through 2027, asks Meredith Calloway and Brendan Kessler to draft a proposal to increase the AI Infrastructure Fund model "
           "weight for the February 12 meeting; asks them to address concentration (copying Elena Vasquez) and the "
           "funding source."),
        EM("DOC-EM-05", "2026-01-23", "Leah Goldberg", ["Natalie Brooks"], ["Rebecca Thornton"],
           "Pemberton follow-up: interconnection queue data",
           ["interconnection queue", "power demand", "gas-fired generation", "AI data centers", "Natalie Brooks"],
           "Thanks Natalie Brooks for yesterday's meeting; sends an interconnection queue data summary (Texas and the "
           "Mid-Atlantic); notes that AI data centers account for most new large-load requests and that on-site "
           "gas-fired generation is becoming common.",
           avoid=AVOID_AI),
        EM("DOC-EM-06", "2026-02-13", "Philip Ashworth", ADVISOR_NAMES, [],
           "IC-2026-004: AI Infrastructure allocation increase - client talking points",
           ["IC-2026-004", "AI Infrastructure Fund", "GPU capacity", "Nvidia", "Municipal Income Fund",
            "Core Fixed Income Fund", "Global Technology Fund"],
           f"Announces approval of IC-2026-004 (6-1): AI Infrastructure Fund Growth 5% to 8%, Balanced 3% to 5%; trades "
           f"February 17 to March 6 ({f['ic004_accounts']} accounts, {f['ic004_clients']} clients, about "
           f"{f['ic004_total']}); funded from the Municipal Income Fund (taxable) or Core Fixed Income Fund. Talking "
           f"points: demand for GPU capacity through 2027. On concentration questions, explain Nvidia appears in both the "
           f"AI Infrastructure Fund and the Global Technology Fund and that the risk team will report look-through "
           f"exposure by mid-year."),
        EM("DOC-EM-07", "2026-02-16", "Trevor Iwasaki", ADVISOR_NAMES, ["Philip Ashworth"],
           "Rebalance schedule for IC-2026-004",
           ["IC-2026-004", "AI Infrastructure Fund", "Municipal Income Fund", "Core Fixed Income Fund",
            "Hartwell Family Trust", "Okafor Family Office", "Sterling-Hayes Family Office"],
           f"Trading window February 17 to March 6, roughly four accounts per trading day; first trade is the Hartwell "
           f"Family Trust taxable account on {_fmt_day(f['hw_aix_trust']['date'])}; Okafor Family Office on "
           f"{_fmt_day(f['ok_aix']['date'])}; Sterling-Hayes Family Office on {_fmt_day(f['sh_aix']['date'])}. Sells come "
           f"from the Municipal Income Fund for taxable accounts and the Core Fixed Income Fund otherwise. Advisors must "
           f"flag any client restrictions by end of day."),
        EM("DOC-EM-08", "2026-02-18", "Michael Torres", ["Robert Hartwell"], ["Elaine Hartwell"],
           "Portfolio update: increasing AI infrastructure exposure",
           ["Hartwell Family Trust", "AI Infrastructure Fund", "IC-2026-004", "Nvidia", "Broadcom", "TSMC",
            "Municipal Income Fund", "AI infrastructure"],
           f"Yesterday ({_fmt_day(f['hw_aix_trust']['date'])}) the firm purchased about "
           f"{usd(f['hw_aix_trust']['amount_usd'])} of the AI Infrastructure Fund in the Hartwell Family Trust taxable "
           f"account, funded from the Municipal Income Fund; a {usd(f['hw_aix_ira']['amount_usd'])} purchase in Robert's "
           f"IRA follows on {_fmt_day(f['hw_aix_ira']['date'])} (funded from the Core Fixed Income Fund). Explains the "
           f"IC-2026-004 rationale; the fund's largest holdings are Nvidia, Broadcom and TSMC."),
        EM("DOC-EM-09", "2026-02-19", "Robert Hartwell", ["Michael Torres"], [],
           "RE: Portfolio update: increasing AI infrastructure exposure",
           ["Nvidia", "AI Infrastructure Fund", "Global Technology Fund"],
           "Short client reply to Michael: supportive of the change, but Elaine is worried about how much Nvidia the "
           "family owns across both the AI Infrastructure Fund and the Global Technology Fund - can he quantify the "
           "total? Suggests discussing at the March 3 review.",
           words=(60, 140)),
        EM("DOC-EM-10", "2026-02-20", "Jennifer Walsh", ["Chinedu Okafor"], ["Ngozi Okafor"],
           "AI Infrastructure allocation change",
           ["Okafor Family Office", "AI Infrastructure Fund", "IC-2026-004", "Private Credit Fund II"],
           f"Explains IC-2026-004 and the scheduled purchase of about {usd(f['ok_aix']['amount_usd'])} of the AI "
           f"Infrastructure Fund on {_fmt_day(f['ok_aix']['date'])}; confirms the February 24 meeting; private credit "
           f"commitments to Private Credit Fund II are unaffected."),
        EM("DOC-EM-11", "2026-03-19", "Owen Fitzgerald", ["Marcus Bell"], ["Priya Nair"],
           "Cobalt Ridge: tenant LOIs and power timeline",
           ["Cobalt Ridge Data Centers", "GPU clusters", "power purchase agreement", "Ostrander Power Constructors",
            "Marcus Bell"],
           "Thanks Marcus Bell for the site visit; attaches tenant letters of intent, the substation energization "
           "timeline from Ostrander Power Constructors and the power purchase agreement term sheet; GPU clusters deliveries "
           "planned for Q3.",
           avoid=AVOID_AI),
        EM("DOC-EM-12", "2026-04-10", "Marcus Bell", IC_EMAIL_LIST, ["Priya Nair"],
           "Cobalt Ridge facility approved (IC-2026-006) - closing timeline",
           ["IC-2026-006", "Cobalt Ridge Data Centers", "Private Credit Fund II", "senior secured term loan",
            "Caldwell & Pierce LLP"],
           "Thanks the committee; closing targeted for April 22; capital call #6 notices go out April 14 with funding on "
           "April 20; loan documentation by Caldwell & Pierce LLP."),
        EM("DOC-EM-13", "2026-04-14", "Courtney Bianchi", ["Robert Hartwell"], ["Michael Torres"],
           "Private Credit Fund II - Capital Call Notice #6",
           ["Private Credit Fund II", "Hartwell Family Trust", "Cobalt Ridge Data Centers"],
           f"Capital call #6: {usd(f['hw_call6']['amount_usd'])} due {_fmt_day(f['hw_call6']['date'])}, 2026 from the "
           f"Hartwell Family Trust private investments account; proceeds fund Private Credit Fund II's new senior secured "
           f"term loan to Cobalt Ridge Data Centers; wiring instructions on file; questions to Michael Torres."),
        EM("DOC-EM-14", "2026-05-15", "Rebecca Thornton", ADVISOR_NAMES, ["Philip Ashworth"],
           "IC-2026-008 talking points: Energy Infrastructure and data center power demand",
           ["IC-2026-008", "Energy Infrastructure Fund", "power demand", "AI data centers", "Williams Companies",
            "Kinder Morgan", "Bellamy Foundation"],
           f"IC-2026-008 approved 7-0: Energy Infrastructure Fund 5% to 7%; trades June 1-12 (about "
           f"{f['ic008_accounts']} accounts, {f['ic008_total']}); thesis: power demand from AI data centers drives "
           f"gas-fired generation and pipeline volumes (Williams Companies, Kinder Morgan); the Bellamy Foundation is "
           f"exempt under its investment policy."),
        EM("DOC-EM-15", "2026-05-21", "Andre Washington", ["Margaret Bellamy"], [],
           "Follow-up: energy transition allocation",
           ["Bellamy Foundation", "Clean Energy Transition Fund", "battery storage", "Energy Infrastructure Fund",
            "NextEra Energy"],
           "Recap of the May 20 meeting; confirms the Bellamy Foundation is exempt from the Energy Infrastructure Fund "
           "increase; the Clean Energy Transition Fund (NextEra Energy, First Solar, battery storage) remains its energy "
           "allocation; the look-through report will follow."),
        EM("DOC-EM-16", "2026-06-19", "Lucas Meyer", ["Elena Vasquez"], ["Douglas Whitfield"],
           "Look-through exposure results",
           ["Hartwell Family Trust", "Okafor Family Office", "Sterling-Hayes Family Office", "Nakamura Family Partners",
            "Nvidia", "AI Infrastructure Fund", "Global Technology Fund"],
           f"Summary after yesterday's Risk Committee: as of June 15 the look-through AI exposure is Hartwell Family "
           f"Trust {hw_jun}%, Okafor Family Office {ok_jun}%, Sterling-Hayes Family Office {sh_jun}% (all above 15%); "
           f"next highest Nakamura Family Partners {nk_jun}%. Nvidia is the largest single-name exposure, driven by "
           f"overlap between the AI Infrastructure Fund and the Global Technology Fund. Drafting the memo for the July "
           f"16 Investment Committee."),
        EM("DOC-EM-17", "2026-07-17", "Philip Ashworth", ADVISOR_NAMES, [],
           "IC-2026-011: single-name cap and overlap reduction - affected clients",
           ["IC-2026-011", "Hartwell Family Trust", "Okafor Family Office", "Sterling-Hayes Family Office",
            "Global Technology Fund", "Cybersecurity Leaders Fund", "Core Fixed Income Fund", "Nvidia",
            "AI Infrastructure Fund"],
           f"IC-2026-011 approved 7-0. Affected clients and trade dates: Okafor Family Office "
           f"{_fmt_day(f['ok_gtf_sell']['date'])}, Hartwell Family Trust {_fmt_day(f['hw_gtf_sell_trust']['date'])}, "
           f"Sterling-Hayes Family Office {_fmt_day(f['sh_gtf_sell']['date'])} - selling Global Technology Fund and buying "
           f"Cybersecurity Leaders Fund and Core Fixed Income Fund. Nvidia is trimmed to 10% within the AI Infrastructure "
           f"Fund. Advisors should call the affected clients this week."),
        EM("DOC-EM-18", "2026-07-20", "Michael Torres", ["Robert Hartwell", "Elaine Hartwell"], [],
           "Reducing overlap between Global Technology Fund and AI Infrastructure Fund",
           ["Global Technology Fund", "AI Infrastructure Fund", "IC-2026-011", "Nvidia", "Cybersecurity Leaders Fund",
            "Core Fixed Income Fund", "Hartwell Family Trust"],
           f"Answers Elaine's question from March: as of June 15 the Hartwell Family Trust's look-through AI exposure was "
           f"{hw_jun}%, above the firm's 15% guideline. Plan for {_fmt_day(f['hw_gtf_sell_trust']['date'])}: sell about "
           f"{usd(f['hw_gtf_sell_trust']['amount_usd'])} of the Global Technology Fund in the trust account and "
           f"{usd(f['hw_gtf_sell_ira']['amount_usd'])} in Robert's IRA; reinvest in the Cybersecurity Leaders Fund and "
           f"the Core Fixed Income Fund; expected exposure about 13%. Nvidia is also being trimmed to 10% inside the AI "
           f"Infrastructure Fund under IC-2026-011."),
        EM("DOC-EM-19", "2026-07-21", "Elaine Hartwell", ["Michael Torres"], [],
           "RE: Reducing overlap between Global Technology Fund and AI Infrastructure Fund",
           ["Cobalt Ridge Data Centers", "Private Credit Fund II"],
           "Short client reply: thanks Michael, this addresses their concern. New question: what happens to "
           "Private Credit Fund II's loan to Cobalt Ridge Data Centers if its power hookup is delayed? Suggests "
           "discussing it at the August review.",
           words=(50, 120)),
        EM("DOC-EM-20", "2026-08-28", "Henrik Larsen", ["Priya Nair"], ["Marcus Bell"],
           "Polar Loop: customer pipeline and backlog",
           ["Polar Loop Cooling Systems", "liquid cooling", "rack density", "Cobalt Ridge Data Centers", "Priya Nair"],
           "Follow-up to the August 27 meeting: backlog summary, customer pipeline led by Cobalt Ridge Data Centers, "
           "timing of the second manufacturing line; liquid cooling demand rising with rack density.",
           avoid=AVOID_AI),
        EM("DOC-EM-21", "2026-09-11", "Meredith Calloway", ["Douglas Whitfield"], ["Brendan Kessler"],
           "AI infrastructure Q3 review: demand holding through 2027",
           ["AI infrastructure", "GPU capacity", "Nvidia", "hyperscaler capex", "AI Infrastructure Fund",
            "IC-2026-013"],
           "Summary of the Q3 review presented yesterday: GPU capacity still tight, hyperscaler capex intact, demand "
           "through 2027 holds; the committee kept the AI Infrastructure Fund at 8% (recorded in IC-2026-013); Nvidia "
           "sits at the 10% cap."),
        EM("DOC-EM-22", "2026-03-13", "Stephen Albrecht", ADVISOR_NAMES, [],
           "IC-2026-005: Core Fixed Income duration change",
           ["IC-2026-005", "Core Fixed Income Fund", "duration target", "Treasury yields"],
           "IC-2026-005 approved: Core Fixed Income Fund duration target 6.0 to 5.0 years, implemented inside the fund; "
           "no client trades; client talking points on Treasury yields and rate uncertainty."),

        # =================================================================== CRM NOTES
        CRM("DOC-CRM-01", "2025-11-21", "C-001", "Michael Torres", "Call", "Robert asked about AI stocks after earnings",
            ["Robert Hartwell", "Nvidia", "AI Infrastructure Fund", "GPU demand", "Global Technology Fund"],
            "Robert Hartwell called after earnings headlines and asked whether to buy more Nvidia directly. Explained the "
            "trust already owns it through the AI Infrastructure Fund and the Global Technology Fund. Mentioned the "
            "research team just published a report on GPU demand. No action.",
            avoid=AVOID_AI),
        CRM("DOC-CRM-02", "2026-01-28", "C-001", "Michael Torres", "Call", "Elaine concerned about technology concentration",
            ["Elaine Hartwell", "Global Technology Fund", "AI Infrastructure Fund", "Nvidia"],
            "Elaine Hartwell called; worried technology is too large a share of the trust and that Nvidia appears in "
            "several funds. Mentioned the Investment Committee may revisit the AI allocation in February (nothing "
            "decided yet). Will review at the Q1 meeting."),
        CRM("DOC-CRM-03", "2026-03-03", "C-001", "Michael Torres", "Meeting",
            "Quarterly review - AI allocation and look-through request",
            ["Hartwell Family Trust", "IC-2026-004", "AI Infrastructure Fund", "Nvidia", "Private Credit Fund II"],
            f"Quarterly review with Robert and Elaine Hartwell. Reviewed IC-2026-004 purchases "
            f"({usd(f['hw_aix_trust']['amount_usd'])} trust, {usd(f['hw_aix_ira']['amount_usd'])} IRA). Elaine asked for "
            f"total Nvidia exposure across funds; request sent to the risk team. Told them Private Credit Fund II may "
            f"call capital in the spring."),
        CRM("DOC-CRM-04", "2026-04-16", "C-001", "Michael Torres", "Call", "Capital call questions - Private Credit Fund II",
            ["Robert Hartwell", "Private Credit Fund II", "Cobalt Ridge Data Centers", "senior secured term loan"],
            f"Robert Hartwell asked about capital call #6 ({usd(f['hw_call6']['amount_usd'])} due "
            f"{_fmt_day(f['hw_call6']['date'])}). Explained it funds a senior secured term loan to Cobalt Ridge Data "
            f"Centers, a data center developer; first lien. Robert comfortable."),
        CRM("DOC-CRM-05", "2026-07-22", "C-001", "Michael Torres", "Call", "Elaine comfortable with overlap reduction",
            ["Elaine Hartwell", "IC-2026-011", "Global Technology Fund", "Cobalt Ridge Data Centers"],
            f"Elaine Hartwell approved the {_fmt_day(f['hw_gtf_sell_trust']['date'])} overlap trades under IC-2026-011 "
            f"(Global Technology Fund sales). Asked about power risk at Cobalt Ridge Data Centers; agreed to cover it at "
            f"the August 12 mid-year review with Brendan Kessler."),
        CRM("DOC-CRM-06", "2026-09-18", "C-001", "Michael Torres", "Call", "Robert asked about Nvidia volatility",
            ["Robert Hartwell", "Nvidia", "GPU capacity", "Meredith Calloway", "AI Infrastructure Fund",
             "Polar Loop Cooling Systems", "Private Credit Fund II"],
            f"Robert Hartwell asked about recent Nvidia volatility. Shared Meredith Calloway's Q3 view that demand for GPU "
            f"capacity holds through 2027 and that the AI Infrastructure Fund keeps Nvidia at the 10% cap. Also confirmed "
            f"capital call #7 ({usd(f['hw_call7']['amount_usd'])}, {_fmt_day(f['hw_call7']['date'])}) funded a Private "
            f"Credit Fund II facility to Polar Loop Cooling Systems."),
        CRM("DOC-CRM-07", "2025-12-03", "C-002", "Jennifer Walsh", "Call", "Private credit interest",
            ["Chinedu Okafor", "Private Credit Fund II", "direct lending"],
            "Chinedu Okafor asked about adding to private credit. Explained Private Credit Fund II commitments are set; "
            "discussed direct lending yields and floating-rate income."),
        CRM("DOC-CRM-08", "2026-02-24", "C-002", "Jennifer Walsh", "Meeting", "Portfolio review - AI allocation",
            ["Okafor Family Office", "AI Infrastructure Fund", "IC-2026-004", "Ngozi Okafor"],
            f"Review meeting with Chinedu and Ngozi Okafor. AI Infrastructure Fund purchase of about "
            f"{usd(f['ok_aix']['amount_usd'])} scheduled for {_fmt_day(f['ok_aix']['date'])} under IC-2026-004. Ngozi "
            f"asked about liquidity. IPS acknowledgment of the technology overweight to be sent."),
        CRM("DOC-CRM-09", "2026-07-24", "C-002", "Jennifer Walsh", "Call", "Overlap reduction",
            ["Chinedu Okafor", "IC-2026-011", "Global Technology Fund", "Cybersecurity Leaders Fund"],
            f"Discussed the IC-2026-011 trades on {_fmt_day(f['ok_gtf_sell']['date'])}: sell about "
            f"{usd(f['ok_gtf_sell']['amount_usd'])} of the Global Technology Fund and reinvest in the Cybersecurity "
            f"Leaders Fund and Core Fixed Income Fund. Chinedu Okafor reluctant but agreed."),
        CRM("DOC-CRM-10", "2026-01-12", "C-003", "Andre Washington", "Call", "IPS fossil-fuel exclusion reminder",
            ["Margaret Bellamy", "Energy Infrastructure Fund", "Clean Energy Transition Fund"],
            "Margaret Bellamy reminded us the investment policy excludes fossil-fuel infrastructure. Confirmed the "
            "foundation holds no Energy Infrastructure Fund; its energy allocation is the Clean Energy Transition Fund."),
        CRM("DOC-CRM-11", "2026-05-20", "C-003", "Andre Washington", "Meeting", "Investment review",
            ["Bellamy Foundation", "IC-2026-008", "Clean Energy Transition Fund", "AI Infrastructure Fund",
             "Constellation Energy"],
            "Investment review with Margaret Bellamy. Foundation exempt from IC-2026-008. She asked about indirect power "
            "exposure; the AI Infrastructure Fund holds Constellation Energy and Quanta Services. Look-through report "
            "requested."),
        CRM("DOC-CRM-12", "2025-12-08", "C-004", "Laura Chen", "Call", "Tax-loss harvesting review",
            ["Erik Lindqvist", "Healthcare Innovation Fund", "Novo Nordisk"],
            "Erik Lindqvist asked about tax-loss harvesting. Healthcare Innovation Fund near cost; discussed Novo "
            "Nordisk weakness; no harvest this year."),
        CRM("DOC-CRM-13", "2026-03-10", "C-004", "Laura Chen", "Call", "Rebalance confirmation",
            ["Erik Lindqvist", "AI Infrastructure Fund", "IC-2026-004"],
            f"Confirmed Balanced-model purchases of the AI Infrastructure Fund under IC-2026-004: trust account on "
            f"{_fmt_day(f['lq_aix_trust']['date'])} ({usd(f['lq_aix_trust']['amount_usd'])}) and IRA on "
            f"{_fmt_day(f['lq_aix_ira']['date'])} ({usd(f['lq_aix_ira']['amount_usd'])}). Erik fine with it."),
        CRM("DOC-CRM-14", "2025-11-19", "C-005", "Victor Alvarez", "Meeting", "Planning meeting",
            ["Carlos Ramirez", "Sofia Ramirez", "Municipal Income Fund", "rate cuts"],
            "Planning meeting with Carlos and Sofia Ramirez: college funding, Municipal Income Fund income, outlook for "
            "rate cuts. No changes."),
        CRM("DOC-CRM-15", "2026-06-09", "C-005", "Victor Alvarez", "Call", "Energy allocation change",
            ["Carlos Ramirez", "Energy Infrastructure Fund", "IC-2026-008", "power demand"],
            f"Explained the IC-2026-008 Energy Infrastructure Fund purchase scheduled for {_fmt_day(f['rm_eif']['date'])} "
            f"in the joint account ({usd(f['rm_eif']['amount_usd'])}); data center power demand thesis. Carlos Ramirez "
            f"fine with it."),
        CRM("DOC-CRM-16", "2026-02-02", "C-006", "Andre Washington", "Call", "Annual grant distribution",
            ["Diane Whitman", "Core Fixed Income Fund"],
            "Diane Whitman confirmed the $600,000 annual grant distribution; it will be raised from the Core Fixed Income "
            "Fund on February 3."),
        CRM("DOC-CRM-17", "2026-08-05", "C-006", "Andre Washington", "Email", "Duration question",
            ["Diane Whitman", "Core Fixed Income Fund", "IC-2026-005", "duration target"],
            "Diane Whitman asked why the bond allocation has been steadier this year. Explained the IC-2026-005 change to "
            "the Core Fixed Income Fund duration target in March."),
        CRM("DOC-CRM-18", "2026-04-21", "C-007", "Laura Chen", "Call", "Capital call - Private Credit Fund II",
            ["Kenji Nakamura", "Private Credit Fund II", "Cobalt Ridge Data Centers"],
            f"Kenji Nakamura confirmed capital call #6 ({usd(f['nk_call6']['amount_usd'])}) funded on "
            f"{_fmt_day(f['nk_call6']['date'])}; asked about the Cobalt Ridge Data Centers loan; explained the structure."),
        CRM("DOC-CRM-19", "2026-09-16", "C-007", "Laura Chen", "Call", "Polar Loop facility",
            ["Kenji Nakamura", "Polar Loop Cooling Systems", "Private Credit Fund II", "liquid cooling"],
            f"Capital call #7 ({usd(f['nk_call7']['amount_usd'])}) funded on {_fmt_day(f['nk_call7']['date'])} for the "
            f"Private Credit Fund II facility to Polar Loop Cooling Systems. Kenji Nakamura asked about liquid cooling "
            f"demand; shared the firm's view.",
            avoid=AVOID_AI),
        CRM("DOC-CRM-20", "2025-12-15", "C-008", "Victor Alvarez", "Call", "RMD and income needs",
            ["Maria Delgado", "Municipal Income Fund"],
            f"Required minimum distribution of {usd(f['dg_rmd']['amount_usd'])} taken from Maria Delgado's IRA on "
            f"{_fmt_day(f['dg_rmd']['date'])}. Income from the Municipal Income Fund in the trust is adequate."),
        CRM("DOC-CRM-21", "2026-04-28", "C-008", "Victor Alvarez", "Call", "Rate cuts question",
            ["Maria Delgado", "Core Fixed Income Fund", "rate cuts"],
            "Maria Delgado asked how rate cuts would affect her income. Explained the Core Fixed Income Fund positioning "
            "and the shorter duration target."),
        CRM("DOC-CRM-22", "2026-03-30", "C-009", "Jennifer Walsh", "Meeting", "Endowment spending policy review",
            ["Helen Marsh", "St. Aldric School Endowment", "AI Infrastructure Fund", "IC-2026-004"],
            f"Reviewed the 5% spending policy with Helen Marsh. Confirmed the Balanced-model purchase of the AI "
            f"Infrastructure Fund ({usd(f['sa_aix']['amount_usd'])} on {_fmt_day(f['sa_aix']['date'])}) under IC-2026-004."),
        CRM("DOC-CRM-23", "2026-02-27", "C-010", "Michael Torres", "Call", "AI rebalance confirmation",
            ["Patrick Brennan", "AI Infrastructure Fund", "IC-2026-004"],
            f"Confirmed IC-2026-004 purchases with Patrick Brennan: joint account {usd(f['br_aix_joint']['amount_usd'])} "
            f"on {_fmt_day(f['br_aix_joint']['date'])} and IRA {usd(f['br_aix_ira']['amount_usd'])} on "
            f"{_fmt_day(f['br_aix_ira']['date'])}."),
        CRM("DOC-CRM-24", "2026-06-15", "C-010", "Michael Torres", "Call", "Energy infrastructure question",
            ["Patrick Brennan", "Energy Infrastructure Fund", "power demand", "IC-2026-008"],
            f"Patrick Brennan asked about the Energy Infrastructure Fund purchase on {_fmt_day(f['br_eif']['date'])} "
            f"({usd(f['br_eif']['amount_usd'])}). Explained IC-2026-008 and the data center power demand thesis."),
        CRM("DOC-CRM-25", "2026-07-23", "C-011", "Michael Torres", "Call", "Overlap reduction",
            ["Caroline Sterling-Hayes", "IC-2026-011", "Nvidia", "Global Technology Fund"],
            f"Discussed the {_fmt_day(f['sh_gtf_sell']['date'])} trades under IC-2026-011: selling about "
            f"{usd(f['sh_gtf_sell']['amount_usd'])} of the Global Technology Fund. June look-through AI exposure was "
            f"{sh_jun}%, driven largely by Nvidia overlap. Caroline Sterling-Hayes agreed."),
        CRM("DOC-CRM-26", "2026-04-22", "C-011", "Michael Torres", "Call", "Capital call confirmation",
            ["Caroline Sterling-Hayes", "Private Credit Fund II", "Cobalt Ridge Data Centers"],
            f"Confirmed capital call #6 ({usd(f['sh_call6']['amount_usd'])}) funded on {_fmt_day(f['sh_call6']['date'])}; "
            f"explained the Cobalt Ridge Data Centers loan."),
        CRM("DOC-CRM-27", "2026-01-07", "C-012", "Lauren Pacheco", "Call", "Conservative income review",
            ["Irina Volkov", "Municipal Income Fund", "Treasury yields"],
            "Income review with Irina Volkov: Municipal Income Fund distributions and Treasury yields; no changes."),
    ]
    return specs


def spec_by_id(doc_id: str) -> DocSpec:
    for s in doc_specs():
        if s.doc_id == doc_id:
            return s
    raise KeyError(doc_id)
