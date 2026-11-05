"""Cold-lead investigations scanner: deterministic, model-free, cheap.

The investigations engine (a frontier session) should spend its tokens on
JUDGMENT, not on grinding raw public records. This module does the grinding:
it pulls free public datasets and flags ANOMALIES deterministically -- no
model, so it can run on the free CI runner on a schedule, even with the
operator's PC off, and it never costs a conversation token.

The output is a short list of candidate anomalies with their evidence,
written to ``state/investigations/candidates.json`` (machine) and
``candidates.md`` (human). The engine reads that short list and applies the
Westen test (concealed wrongdoing where the pieces do not add up) to the few
flagged, instead of re-mining the raw data every run.

Design rules (match the repo's honesty contract):
- The ANALYSIS is a pure function over rows; the FETCH is injected, so the
  test stubs the network and keeps the aggregation under test. A scanner
  that hits the network in the suite becomes a live-network test that
  answers differently on a train.
- Every check names what it reads and why the pattern is suspicious. A
  flagged candidate is a QUESTION for the engine, never a conclusion.
- Sources not yet wired are listed as NOT_BUILT with a note, never faked.

Entry point: ``python -m aletheia.investigations`` (or ``.scan()``).
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

from aletheia.fleet import REPO_ROOT

OUT_DIR = REPO_ROOT / "state" / "investigations"
UA = "Mozilla/5.0 (Aletheia investigations; public-records research)"

# The target city. Kept as data so the scanner is not hard-coded to one place.
CITY = "SIOUX FALLS"
STATE = "SD"

# CMS Medicare Part D "by Provider" dataset ids (data.cms.gov data-api), newest
# first. Published yearly; add the new uuid each year. Resolved dynamically is
# more honest but costs a multi-MB catalog download every run, so these are
# pinned and the scanner records which year it actually used.
CMS_PARTD_BY_PROVIDER = [
    ("2023", "42888afe-3b85-4a61-a4ee-091f00bd62bc"),
    ("2022", "adcdaca6-0c9c-485f-af21-1abc16104d6c"),
]

# Specialties for which heavy opioid / long-acting-opioid prescribing is
# EXPECTED (so they are not anomalies). Everyone else carrying a large
# long-acting-opioid load is the signal.
OPIOID_EXPECTED_SPECIALTIES = frozenset({
    "Pain Management",
    "Interventional Pain Management",
    "Anesthesiology",
    "Hematology/Oncology",
    "Medical Oncology",
    "Hematology-Oncology",
    "Physical Medicine and Rehabilitation",
    "Hospice and Palliative Care",
    "Orthopedic Surgery",
    "Neurosurgery",
    "Rheumatology",
})

# A long-acting-opioid claim count at/above this, from an UNEXPECTED specialty,
# is worth a human look. Long-acting opioids are the pill-mill marker.
LA_OPIOID_FLAG = 40

# Specialties for which prescribing antipsychotics to patients 65+ is EXPECTED
# (so not an anomaly). Everyone else carrying a heavy GE65 antipsychotic load is
# the signal: off-label antipsychotics to the elderly is the documented
# nursing-home "chemical restraint" pattern (dementia patients sedated for staff
# convenience), which CMS itself tracks and penalises.
ANTIPSYCHOTIC_GE65_EXPECTED_SPECIALTIES = frozenset({
    "Psychiatry",
    "Geriatric Psychiatry",
    "Child & Adolescent Psychiatry",
    "Neuropsychiatry",
    "Psychiatry & Neurology",
    "Neurology",
    "Geriatric Medicine",
    "Hospice and Palliative Care",
    "Addiction Medicine",
})

# A GE65 antipsychotic claim count at/above this, from an UNEXPECTED specialty,
# is worth a human look. Claims-per-patient (when not suppressed) is the
# continuous-dosing tell that separates restraint from occasional treatment.
ANTIPSYCHOTIC_GE65_FLAG = 100


# Registry of sources: a broad catalogue of what a records-based investigator
# would watch, honest about what is actually wired. Data only; no behaviour.
#
# status is one of:
#   AVAILABLE    a lens is wired and runs every scan (names its run_* caller)
#   QUEUED       the host is reachable from here; the lens is the next build
#   BLOCKED_WAF  the host WAF-403s programmatic JSON (verified); needs a static
#                file / bulk download fetch instead -- the note says which
#   NOT_BUILT    needs a fetch path worked out (portal scrape / token / bulk)
#
# Every non-AVAILABLE entry carries a NOTE that is its ticket. Nothing here is
# faked: a source is AVAILABLE only when a pure analysis + injected fetch exist
# and a test stubs the network. Adding one is a small, reviewed change.
SOURCES: list[dict[str, Any]] = [
    # --- medical harm / exploiting the vulnerable -------------------------
    {"id": "cms_partd_opioids", "category": "medical",
     "name": "CMS Medicare Part D prescribers (by provider)",
     "host": "data.cms.gov/data-api",
     "reads": "every Part D prescriber's opioid / long-acting-opioid volume",
     "signal": "a non-pain specialty carrying a pain-clinic opioid load",
     "free": True, "status": "AVAILABLE"},
    {"id": "cms_partd_antipsychotics_ge65", "category": "medical",
     "name": "CMS Medicare Part D prescribers (by provider)",
     "host": "data.cms.gov/data-api",
     "reads": "every Part D prescriber's antipsychotic volume to patients 65+",
     "signal": "a non-psychiatric specialty sedating the elderly (restraint)",
     "free": True, "status": "AVAILABLE"},
    {"id": "cms_care_compare_nh", "category": "medical",
     "name": "CMS Care Compare nursing homes (provider info)",
     "host": "data.cms.gov/provider-data",
     "reads": "each facility's antipsychotic % of long-stay residents + deficiencies",
     "signal": "a home sedating residents with a bad inspection record (judges the Rx flags)",
     "free": True, "status": "BLOCKED_WAF",
     "note": "ticket: provider-data /api/ WAF-403s; fetch the static NH_ProviderInfo CSV distribution"},
    {"id": "cms_open_payments", "category": "medical",
     "name": "CMS Open Payments (industry $ to clinicians)",
     "host": "openpaymentsdata.cms.gov",
     "reads": "pharma/device payments to SD prescribers",
     "signal": "money to the exact doctors the Rx lenses flag (corroboration)",
     "free": True, "status": "BLOCKED_WAF",
     "note": "ticket: DKAN /api/ WAF-403s; fetch the annual general-payment CSV, filter state=SD"},
    # --- food / consumer / product safety ---------------------------------
    {"id": "fda_recalls", "category": "consumer_safety",
     "name": "openFDA enforcement (food/drug/device recalls)",
     "host": "api.fda.gov",
     "reads": "every FDA recall naming an SD firm, with class and reason",
     "signal": "a local firm with a Class I or repeated recall pattern nobody has covered",
     "free": True, "status": "AVAILABLE"},
    {"id": "nhtsa_complaints", "category": "consumer_safety",
     "name": "NHTSA complaints / recalls", "host": "api.nhtsa.gov",
     "reads": "safety complaints; dealer/service patterns",
     "signal": "a local seller tied to a cluster of safety complaints",
     "free": True, "status": "QUEUED", "note": "ticket: weak local signal; wire if a vein needs it"},
    # --- workplace / labor harm -------------------------------------------
    {"id": "osha_severe_injury", "category": "workplace",
     "name": "OSHA severe injury reports (amputations/hospitalizations)",
     "host": "osha.gov / enforcedata.dol.gov",
     "reads": "every amputation/hospitalization an SF employer reported since 2015",
     "signal": "an employer maiming workers repeatedly with no public reckoning",
     "free": True, "status": "BLOCKED_WAF",
     "note": "ticket: osha.gov .json WAF-403s; fetch the DOL enforcedata severe-injury bulk file"},
    {"id": "osha_inspections", "category": "workplace",
     "name": "OSHA inspections / violations", "host": "enforcedata.dol.gov",
     "reads": "serious/willful/repeat violations at SD establishments",
     "signal": "a willful-violation pattern at one employer",
     "free": True, "status": "QUEUED", "note": "ticket: wire the enforcedata OSHA inspection bulk CSV"},
    {"id": "dol_whd_wage", "category": "workplace",
     "name": "DOL Wage & Hour enforcement", "host": "enforcedata.dol.gov",
     "reads": "back-wage findings by employer",
     "signal": "systematic wage theft at an SF employer",
     "free": True, "status": "NOT_BUILT", "note": "ticket: wire the enforcedata WHD bulk CSV, filter SD"},
    # --- environment -------------------------------------------------------
    {"id": "epa_echo", "category": "environment",
     "name": "EPA ECHO enforcement & compliance", "host": "echodata.epa.gov",
     "reads": "clean-air/water/waste violations, SNC flags and penalties by facility",
     "signal": "a private facility poisoning neighbors, under the regulator's radar",
     "free": True, "status": "AVAILABLE"},
    # --- housing / predatory landlord -------------------------------------
    {"id": "sf_code_enforcement", "category": "housing",
     "name": "Sioux Falls code enforcement / rental violations",
     "host": "siouxfalls.gov portal",
     "reads": "repeat housing-code violations per owner/parcel",
     "signal": "a landlord concealing systemic habitability failures across many units",
     "free": True, "status": "NOT_BUILT", "note": "ticket: find the city code-enforcement data endpoint"},
    {"id": "sf_parcels_landlord", "category": "housing",
     "name": "Sioux Falls parcels / ownership (ArcGIS)",
     "host": "gis.siouxfalls.gov",
     "reads": "owner name, unit counts, square footage by parcel",
     "signal": "one owner behind many units via shells (enrichment for a landlord vein)",
     "free": True, "status": "QUEUED", "note": "ticket: ArcGIS reachable; wire owner-cluster enrichment"},
    {"id": "minnehaha_deeds_liens", "category": "housing",
     "name": "Minnehaha County deeds / liens", "host": "county ROD portal",
     "reads": "transfers and liens vs claimed ownership",
     "signal": "a transfer/lien that contradicts a public claim",
     "free": True, "status": "NOT_BUILT", "note": "ticket: find the county register-of-deeds search endpoint"},
    # --- financial / shells / self-dealing --------------------------------
    {"id": "sd_sos_entities", "category": "financial",
     "name": "SD Secretary of State business entities", "host": "sosenterprise.sd.gov",
     "reads": "entities and their registered agents",
     "signal": "shared-agent shell clusters; a registration absent where money arrives",
     "free": True, "status": "NOT_BUILT", "note": "ticket: work out the SoS entity-search fetch (anchors the absence-of-record join)"},
    {"id": "usaspending_longtail", "category": "financial",
     "name": "USAspending awards (long tail)", "host": "api.usaspending.gov",
     "reads": "federal awards to SF recipients, mining the small/odd tail",
     "signal": "money to an entity with no matching registration/footprint (absence-of-record)",
     "free": True, "status": "QUEUED",
     "note": "ticket: reachable; top tail = known institutions (gov-money alone is low-priority), so the lens is the long-tail x SoS-registry join"},
    {"id": "sec_edgar_formd", "category": "financial",
     "name": "SEC EDGAR full-text / Form D", "host": "efts.sec.gov",
     "reads": "private securities offerings and promoters based in SD",
     "signal": "an offering whose story doesn't match the promoter's footprint",
     "free": True, "status": "QUEUED", "note": "ticket: reachable; wire Form D full-text pull for SD"},
    {"id": "propublica_990", "category": "financial",
     "name": "ProPublica Nonprofit Explorer (990s)", "host": "projects.propublica.org",
     "reads": "officer pay, related-party (Schedule L) self-dealing",
     "signal": "a nonprofit whose money serves insiders, not its mission",
     "free": True, "status": "QUEUED", "note": "ticket: reachable; impossible-math exhausted, wire Schedule L self-dealing"},
    # --- corruption / influence -------------------------------------------
    {"id": "sd_campaign_finance", "category": "corruption",
     "name": "SD campaign finance", "host": "sdsos campaign portal",
     "reads": "contributions vs official actions / contracts",
     "signal": "a donor who wins a contract or a vote",
     "free": True, "status": "NOT_BUILT", "note": "ticket: find the SD campaign-finance data endpoint"},
    {"id": "sf_contracts_tif", "category": "corruption",
     "name": "Sioux Falls contracts / TIF / permits", "host": "siouxfalls.gov",
     "reads": "who wins city money and who approves it",
     "signal": "an insider deal or a permit that contradicts a public claim",
     "free": True, "status": "NOT_BUILT", "note": "ticket: find the city contract/TIF data endpoint"},
    # --- courts / litigation ----------------------------------------------
    {"id": "courtlistener_dockets", "category": "courts",
     "name": "CourtListener / RECAP dockets", "host": "courtlistener.com",
     "reads": "civil suits naming an SD operator (a pattern of harm)",
     "signal": "many plaintiffs, same defendant, no press -- a quiet harm pattern",
     "free": True, "status": "NOT_BUILT", "note": "ticket: needs a free CourtListener API token"},
    # --- animal cruelty ----------------------------------------------------
    {"id": "usda_aphis_inspections", "category": "animal",
     "name": "USDA APHIS inspection reports", "host": "aphis.usda.gov",
     "reads": "animal-welfare violations at licensed SD facilities",
     "signal": "a breeder/dealer with a cruelty record nobody has covered",
     "free": True, "status": "NOT_BUILT", "note": "ticket: APHIS publishes inspection PDFs; work out the fetch"},
    # --- kinetic / live ----------------------------------------------------
    {"id": "sky_watch", "category": "kinetic",
     "name": "ADS-B / FAA aircraft (sky-watch)", "host": "adsb.fi / FAA registry",
     "reads": "unusual aircraft over / landing near Sioux Falls",
     "signal": "a private jet pattern that doesn't match any public reason",
     "free": True, "status": "QUEUED", "note": "ticket: reachable; wire as its own periodic kinetic check"},
]


def _get_json(url: str, timeout: float = 60.0) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


# ---- CMS Part D opioid outliers -------------------------------------------

def opioid_outliers(rows: list[dict[str, Any]],
                    *, flag_at: int = LA_OPIOID_FLAG) -> list[dict[str, Any]]:
    """Pure analysis. Given Part D by-provider rows for the city, return
    candidate anomalies: prescribers with a heavy long-acting-opioid load
    whose specialty does not explain it. Deterministic, no model.
    """
    out: list[dict[str, Any]] = []
    for r in rows:
        la = _num(r.get("Opioid_LA_Tot_Clms"))
        if la < flag_at:
            continue
        specialty = (r.get("Prscrbr_Type") or "").strip()
        if specialty in OPIOID_EXPECTED_SPECIALTIES:
            continue
        total = _num(r.get("Tot_Clms"))
        opioid = _num(r.get("Opioid_Tot_Clms"))
        name = (str(r.get("Prscrbr_Last_Org_Name") or "").strip()
                + ", " + str(r.get("Prscrbr_First_Name") or "").strip()).strip(", ")
        out.append({
            "check": "cms_partd_opioids",
            "kind": "anomaly",
            "subject": name,
            "summary": (f"{specialty} prescriber with {int(la)} long-acting-opioid "
                        f"claims -- a pain-clinic load from a non-pain specialty"),
            "evidence": {
                "npi": r.get("Prscrbr_NPI"),
                "specialty": specialty,
                "long_acting_opioid_claims": int(la),
                "opioid_claims": int(opioid),
                "total_claims": int(total),
                "opioid_share_pct": round(100 * opioid / total, 1) if total else None,
                "address": (str(r.get("Prscrbr_St1") or "").strip()),
                "city": (str(r.get("Prscrbr_City") or "").strip()),
            },
            "source": "CMS Medicare Part D prescribers (by provider)",
            "why_him": ("a licensed professional's public prescribing record; "
                        "target the CLINIC, records-based, never the person"),
            "next_record": ("who supervises/owns the clinic (SD SoS + medical "
                            "board); any overdose cluster or billing anomaly"),
        })
    out.sort(key=lambda c: -c["evidence"]["long_acting_opioid_claims"])
    return out


# ---- CMS Part D antipsychotic-to-elderly outliers -------------------------

def antipsychotic_ge65_outliers(rows: list[dict[str, Any]],
                                *, flag_at: int = ANTIPSYCHOTIC_GE65_FLAG
                                ) -> list[dict[str, Any]]:
    """Pure analysis over the SAME Part D by-provider rows. Flag prescribers
    carrying a heavy antipsychotic load to patients 65+ whose specialty does
    not explain it -- the nursing-home chemical-restraint marker. No model.
    """
    out: list[dict[str, Any]] = []
    for r in rows:
        clms = _num(r.get("Antpsyct_GE65_Tot_Clms"))
        if clms < flag_at:
            continue
        specialty = (r.get("Prscrbr_Type") or "").strip()
        if specialty in ANTIPSYCHOTIC_GE65_EXPECTED_SPECIALTIES:
            continue
        benes = _num(r.get("Antpsyct_GE65_Tot_Benes"))
        per_bene = round(clms / benes, 1) if benes else None
        name = (str(r.get("Prscrbr_Last_Org_Name") or "").strip()
                + ", " + str(r.get("Prscrbr_First_Name") or "").strip()).strip(", ")
        age = _num(r.get("Bene_Avg_Age"))
        summary = (f"{specialty} prescriber with {int(clms)} antipsychotic claims "
                   f"to patients 65+")
        if per_bene is not None:
            summary += f" across {int(benes)} patients ({per_bene} per patient)"
        summary += " -- the nursing-home chemical-restraint marker"
        out.append({
            "check": "cms_partd_antipsychotics_ge65",
            "kind": "anomaly",
            "subject": name,
            "summary": summary,
            "evidence": {
                "npi": r.get("Prscrbr_NPI"),
                "specialty": specialty,
                "antipsychotic_ge65_claims": int(clms),
                "antipsychotic_ge65_patients": int(benes) if benes else None,
                "claims_per_patient": per_bene,
                "avg_patient_age": round(age, 1) if age else None,
                "address": (str(r.get("Prscrbr_St1") or "").strip()),
                "city": (str(r.get("Prscrbr_City") or "").strip()),
            },
            "source": "CMS Medicare Part D prescribers (by provider)",
            "why_him": ("a licensed professional's public prescribing record; "
                        "target the FACILITY/clinic, records-based, never a patient"),
            "next_record": ("which nursing home(s) the prescriber serves (CMS Care "
                            "Compare); that facility's antipsychotic rate and "
                            "deficiency/complaint history"),
        })
    out.sort(key=lambda c: -c["evidence"]["antipsychotic_ge65_claims"])
    return out


def _fetch_cms_partd(city: str = CITY, state: str = STATE) -> tuple[str, list[dict]]:
    """Network. Return (year, rows) for the city from the newest CMS Part D
    by-provider dataset that answers.
    """
    last_err = "no dataset tried"
    for year, uuid in CMS_PARTD_BY_PROVIDER:
        url = (f"https://data.cms.gov/data-api/v1/dataset/{uuid}/data"
               f"?filter[Prscrbr_City]={urllib.parse.quote(city)}"
               f"&filter[Prscrbr_State_Abrvtn]={urllib.parse.quote(state)}"
               f"&size=5000")
        try:
            rows = _get_json(url)
            if isinstance(rows, list) and rows:
                return year, rows
            last_err = f"{year}: empty"
        except Exception as exc:  # noqa: BLE001 - network is best-effort
            last_err = f"{year}: {exc}"
    raise RuntimeError(f"CMS Part D unreachable ({last_err})")


# Each lens is a pure function over the same by-provider rows, so the city is
# fetched ONCE and every anomaly check runs over it -- no duplicate network pull.
CMS_ANALYSES: list[Callable[[list[dict[str, Any]]], list[dict[str, Any]]]] = [
    opioid_outliers,
    antipsychotic_ge65_outliers,
]


def run_cms_partd(fetch: Callable[[], tuple[str, list[dict]]] | None = None
                  ) -> dict[str, Any]:
    """One check, one fetch (injectable), several lenses. Returns a result
    record whose candidates are every CMS anomaly found over the city's rows.
    """
    fetch = fetch or _fetch_cms_partd
    try:
        year, rows = fetch()
    except Exception as exc:  # noqa: BLE001
        return {"check": "cms_partd", "ok": False, "error": str(exc),
                "candidates": []}
    cands: list[dict[str, Any]] = []
    for analyse in CMS_ANALYSES:
        for c in analyse(rows):
            c["data_year"] = year
            cands.append(c)
    return {"check": "cms_partd", "ok": True, "data_year": year,
            "rows_scanned": len(rows), "candidates": cands}


# ---- openFDA enforcement (food/drug/device recalls) -----------------------

# api.fda.gov is AWS-hosted and answers programmatically (unlike the DKAN
# provider-data / open-payments hosts, which WAF-403 and need static files).
FDA_ENFORCEMENT_ENDPOINTS = [
    ("food", "https://api.fda.gov/food/enforcement.json"),
    ("drug", "https://api.fda.gov/drug/enforcement.json"),
    ("device", "https://api.fda.gov/device/enforcement.json"),
]


def fda_recall_outliers(results: list[dict[str, Any]], *, city: str = CITY
                        ) -> list[dict[str, Any]]:
    """Pure analysis. Group recalls by firm (in the target city) and flag a
    firm carrying a Class I (serious-harm) recall OR a repeat pattern. A single
    recall is published, so this is a CONTEXT puzzle-piece; a CLUSTER nobody
    has covered is the lead. Deterministic, no model.
    """
    by_firm: dict[str, list[dict[str, Any]]] = {}
    for r in results:
        rc_city = (r.get("city") or "").strip()
        if city.upper() not in rc_city.upper():
            continue
        firm = (r.get("recalling_firm") or "").strip()
        if not firm:
            continue
        by_firm.setdefault(firm, []).append(r)
    out: list[dict[str, Any]] = []
    for firm, recs in by_firm.items():
        class_i = any((x.get("classification") or "").strip() == "Class I"
                      for x in recs)
        if not (class_i or len(recs) >= 2):
            continue
        classes = sorted({(x.get("classification") or "").strip()
                          for x in recs if x.get("classification")})
        kinds = sorted({str(x.get("kind")) for x in recs if x.get("kind")})
        reasons = [str(x.get("reason_for_recall") or "")[:140] for x in recs[:4]]
        summary = (f"{firm}: {len(recs)} FDA recall(s) "
                   f"[{', '.join(kinds) or 'n/a'}], classes {', '.join(classes) or 'n/a'}")
        if class_i:
            summary += " incl. Class I (serious-harm)"
        out.append({
            "check": "fda_recalls",
            "kind": "context",
            "subject": firm,
            "summary": summary,
            "evidence": {
                "recall_count": len(recs),
                "classes": classes,
                "kinds": kinds,
                "class_I": class_i,
                "reasons": reasons,
                "city": next((x.get("city") for x in recs if x.get("city")), ""),
            },
            "source": "openFDA enforcement (food/drug/device recalls)",
            "why_him": ("a firm's public recall record; target the BUSINESS, "
                        "records-based"),
            "next_record": ("is the pattern uncovered locally (news/BBB/health "
                            "dept)? repeat across years; distribution reach / who "
                            "was harmed"),
        })
    out.sort(key=lambda c: (-int(c["evidence"]["class_I"]),
                            -c["evidence"]["recall_count"]))
    return out


def _fetch_fda_recalls(state: str = STATE) -> list[dict[str, Any]]:
    """Network. Pull recent recalls naming a firm in the state across food,
    drug and device enforcement. openFDA returns 404 when a query has no
    matches, so one empty endpoint never kills the others.
    """
    out: list[dict[str, Any]] = []
    for kind, base in FDA_ENFORCEMENT_ENDPOINTS:
        url = f"{base}?search=state:{urllib.parse.quote(state)}&limit=100"
        try:
            data = _get_json(url)
        except Exception:  # noqa: BLE001 - per-endpoint best-effort (404 = none)
            continue
        for r in (data.get("results", []) if isinstance(data, dict) else []):
            r["kind"] = kind
            out.append(r)
    return out


def run_fda_recalls(fetch: Callable[[], list[dict[str, Any]]] | None = None
                    ) -> dict[str, Any]:
    """One check: fetch (injectable) then analyse."""
    fetch = fetch or _fetch_fda_recalls
    try:
        results = fetch()
    except Exception as exc:  # noqa: BLE001
        return {"check": "fda_recalls", "ok": False, "error": str(exc),
                "candidates": []}
    return {"check": "fda_recalls", "ok": True, "rows_scanned": len(results),
            "candidates": fda_recall_outliers(results)}


# ---- EPA ECHO environmental violators -------------------------------------

ECHO_FACILITY_INFO = "https://echodata.epa.gov/echo/echo_rest_services.get_facility_info"
ECHO_QID = "https://echodata.epa.gov/echo/echo_rest_services.get_qid"

# Name markers for government / municipal operators -- the memory's warning was
# that SF environmental hits are gov lagoons (a city sewage plant is not the
# concealed-harm story). Dropped deterministically alongside the federal flag.
ECHO_GOV_NAME_MARKERS = (
    "CITY OF", "COUNTY OF", "STATE OF", "MUNICIPAL", "SANITARY DISTRICT",
    "WASTEWATER", "WATER RECLAMATION", "PUBLIC WORKS", "WWTP", "WTP",
    "WATER TREATMENT", "WATER DEPT", "SCHOOL DISTRICT", "DEPARTMENT OF",
    "USDA", "FEDERAL", "AIR FORCE", "ARMY", "DEPT OF",
    "PORT OF ENTRY", "HIGHWAY", "DOT ", "NATIONAL GUARD", "PENITENTIARY",
)


def epa_echo_violators(rows: list[dict[str, Any]], *, city: str = CITY
                       ) -> list[dict[str, Any]]:
    """Pure analysis. From ECHO facility rows, flag a PRIVATE facility in the
    target city that is a significant non-complier, or carries a formal
    enforcement action or a penalty -- a repeat environmental violator. Gov /
    municipal operators are dropped (federal flag + name markers). No model.
    """
    out: list[dict[str, Any]] = []
    for r in rows:
        if city.upper() not in (r.get("FacCity") or "").upper():
            continue
        if (r.get("FacFederalFlg") or "").strip().upper() == "Y":
            continue
        name = (r.get("FacName") or "").strip()
        up = name.upper()
        if any(m in up for m in ECHO_GOV_NAME_MARKERS):
            continue
        snc = (r.get("FacSNCFlg") or "").strip().upper() == "Y"
        formal = int(_num(r.get("FacFormalActionCount")))
        penalties = _num(r.get("FacTotalPenalties"))
        if not (snc or formal >= 1 or penalties > 0):
            continue
        summary = f"{name}: EPA " + ("significant non-complier" if snc else "violations")
        if formal:
            summary += f", {formal} formal action(s)"
        if penalties:
            summary += f", ${int(penalties):,} penalties"
        status = (r.get("FacComplianceStatus") or "").strip()
        if status:
            summary += f" [{status}]"
        out.append({
            "check": "epa_echo",
            "kind": "anomaly",
            "subject": name,
            "summary": summary,
            "evidence": {
                "registry_id": r.get("RegistryID"),
                "significant_noncomplier": snc,
                "formal_actions": formal,
                "total_penalties": penalties,
                "quarters_with_noncompliance": r.get("FacQtrsWithNC"),
                "compliance": {
                    "overall": status,
                    "air_caa": (r.get("CAAComplianceStatus") or "").strip(),
                    "water_cwa": (r.get("CWAComplianceStatus") or "").strip(),
                    "waste_rcra": (r.get("RCRAComplianceStatus") or "").strip(),
                    "drinking_sdwa": (r.get("SDWAComplianceStatus") or "").strip(),
                },
                "industry": (r.get("FacSICDescs") or r.get("FacNAICSDescs") or "").strip(),
                "last_inspection": r.get("FacDateLastInspection"),
                "address": (r.get("FacStreet") or "").strip(),
                "city": (r.get("FacCity") or "").strip(),
            },
            "source": "EPA ECHO (enforcement & compliance)",
            "why_him": ("a facility's public environmental-compliance record; "
                        "target the BUSINESS, records-based"),
            "next_record": ("what it emits/discharges and who lives nearby; is the "
                            "violation uncovered locally; a repeat pattern vs one-off"),
        })
    out.sort(key=lambda c: (-int(c["evidence"]["significant_noncomplier"]),
                            -c["evidence"]["formal_actions"],
                            -c["evidence"]["total_penalties"]))
    return out


def _fetch_echo_sd(state: str = STATE) -> list[dict[str, Any]]:
    """Network. ECHO ignores a city filter, so pull the state's facilities (a
    QID then paged rows) and let the pure function filter to the city. The
    query returns a QID; rows come from get_qid, 5000 per page.
    """
    q = _get_json(f"{ECHO_FACILITY_INFO}?output=JSON&p_st={urllib.parse.quote(state)}")
    qid = (q.get("Results") or {}).get("QueryID")
    if not qid:
        raise RuntimeError("ECHO: no QueryID returned")
    rows: list[dict[str, Any]] = []
    for page in range(1, 7):  # safety cap; SD is ~13k = 3 pages of 5000
        d = _get_json(f"{ECHO_QID}?output=JSON&qid={qid}&pageno={page}&responseset=5000")
        facs = (d.get("Results") or {}).get("Facilities") or []
        rows.extend(facs)
        if len(facs) < 5000:
            break
    return rows


def run_epa_echo(fetch: Callable[[], list[dict[str, Any]]] | None = None
                 ) -> dict[str, Any]:
    """One check: fetch (injectable) then analyse."""
    fetch = fetch or _fetch_echo_sd
    try:
        rows = fetch()
    except Exception as exc:  # noqa: BLE001
        return {"check": "epa_echo", "ok": False, "error": str(exc),
                "candidates": []}
    return {"check": "epa_echo", "ok": True, "rows_scanned": len(rows),
            "candidates": epa_echo_violators(rows)}


# ---- orchestration ---------------------------------------------------------

CHECKS: list[Callable[[], dict[str, Any]]] = [
    run_cms_partd, run_fda_recalls, run_epa_echo,
]


def scan(write: bool = True) -> dict[str, Any]:
    """Run every wired check, collect candidates, optionally write them."""
    results = [check() for check in CHECKS]
    candidates: list[dict[str, Any]] = []
    for res in results:
        candidates.extend(res.get("candidates", []))
    report = {
        "generated_at": _utcnow(),
        "city": f"{CITY}, {STATE}",
        "checks": [{**{k: v for k, v in r.items() if k != "candidates"},
                     "flagged": len(r.get("candidates", []))}
                    for r in results],
        "candidate_count": len(candidates),
        "candidates": candidates,
    }
    if write:
        _write(report)
    return report


def _utcnow() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write(report: dict[str, Any]) -> list[Path]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    jpath = OUT_DIR / "candidates.json"
    jpath.write_text(json.dumps(report, indent=2, sort_keys=False) + "\n",
                     encoding="utf-8")
    mpath = OUT_DIR / "candidates.md"
    mpath.write_text(_markdown(report), encoding="utf-8")
    return [jpath, mpath]


def _markdown(report: dict[str, Any]) -> str:
    lines = [f"# Investigations candidates - {report['city']}",
             "",
             f"Generated {report['generated_at']} by the deterministic scanner. "
             "Each line is a QUESTION for the engine, not a conclusion.",
             ""]
    for res in report["checks"]:
        state = "ok" if res.get("ok") else f"FAILED: {res.get('error')}"
        lines.append(f"- source `{res['check']}`: {state}"
                     + (f", scanned {res.get('rows_scanned')} rows,"
                        f" {res.get('flagged', 0)} flagged"
                        if res.get("ok") else ""))
    lines.append("")
    if not report["candidates"]:
        lines.append("No anomalies cleared the deterministic threshold this run.")
    for i, c in enumerate(report["candidates"], 1):
        lines += [f"## {i}. {c['subject']}  ({c['check']})",
                  f"- {c['summary']}",
                  f"- evidence: {json.dumps(c['evidence'])}",
                  f"- next record: {c['next_record']}",
                  ""]
    return "\n".join(lines) + "\n"


def main() -> None:
    report = scan(write=True)
    print(f"scanned {len(CHECKS)} source(s); "
          f"{report['candidate_count']} candidate(s) flagged")
    for c in report["candidates"]:
        print(f"  [{c['check']}] {c['subject']}: {c['summary']}")


if __name__ == "__main__":
    main()
