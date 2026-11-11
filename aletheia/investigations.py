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
import math
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

# ---- CMS Care Compare nursing-home facility lens --------------------------
# CMS Care Compare publishes, per nursing home: a long-stay antipsychotic % (the
# share of long-stay residents on an antipsychotic, AFTER CMS excludes residents
# with schizophrenia / Tourette's / Huntington's -- so a high % is off-label
# "chemical restraint", sedation for staff convenience), alongside the home's
# star ratings and health-inspection deficiency counts.
#
# The Westen refinement (a logged rejection: "nursing-home neglect, regulator
# already on it"): a home that is BOTH high-antipsychotic AND has a bad
# inspection is already caught -- the regulator is on it, nothing cold to be
# first on. The COLD, concealed signal is the INVERSE: a home sedating an
# elevated share of its elderly yet rated clean by inspectors (4-5 stars, few
# deficiencies). The harm is present in the records and no inspector has flagged
# it. So this lens flags high-% AND clean, and drops high-% AND deficient.
CARE_COMPARE_ANTIPSYCH_FLOOR = 15.0   # % long-stay on antipsychotics; national
                                      # avg ~14%, below this nothing is notable
CARE_COMPARE_PEER_MULT = 1.3          # ... and >= 1.3x the state peer median
CARE_COMPARE_CLEAN_RATING = 4         # overall star rating >= this == "clean"
CARE_COMPARE_ANTIPSYCH_MEASURE = "481"  # MDS QM: long-stay antipsychotic %
# DKAN datastore query root (data.cms.gov/provider-data). The WAF-403 seen
# 2026-11-05 was intermittent; a plain Accept: application/json gets JSON.
CMS_DKAN_QUERY = "https://data.cms.gov/provider-data/api/1/datastore/query"
CMS_NH_PROVIDER_INFO = "4pq5-n9py"    # facility list + ratings + deficiencies
CMS_NH_MDS_QM = "djen-97ju"           # Minimum Data Set quality measures


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
     "name": "CMS Care Compare nursing homes (provider info + MDS measures)",
     "host": "data.cms.gov/provider-data",
     "reads": "each facility's antipsychotic % of long-stay residents + ratings + deficiencies",
     "signal": "a home sedating an elevated share of its elderly yet rated clean by inspectors (the cold concealed case)",
     "free": True, "status": "AVAILABLE", "caller": "run_care_compare"},
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
    # --- public health / food safety --------------------------------------
    {"id": "sf_food_safety", "category": "safety",
     "name": "Sioux Falls food inspection violations (city ArcGIS)",
     "host": "gis.siouxfalls.gov",
     "reads": "critical food-inspection line-items per establishment",
     "signal": "an establishment cited for the SAME critical hazard repeatedly, still open -- a persistent, uncorrected foodborne-illness risk nobody has assembled",
     "free": True, "status": "AVAILABLE", "caller": "run_sf_food_safety"},
    # --- housing / predatory landlord -------------------------------------
    {"id": "sf_code_enforcement", "category": "housing",
     "name": "Sioux Falls code enforcement / rental violations",
     "host": "gis.siouxfalls.gov ArcGIS",
     "reads": "repeat housing-code violations per owner/parcel",
     "signal": "a landlord concealing systemic habitability failures across many units",
     "free": True, "status": "QUEUED", "note": "ticket: the city ArcGIS (Data/Safety, Data/Community) is reachable from the cloud where the Socrata portal 502s; Environmental Enforcement Cases (Community/9) is currently empty, so find the live code-enforcement/nuisance layer"},
    {"id": "sf_parcels_landlord", "category": "housing",
     "name": "Sioux Falls parcels / ownership (ArcGIS)",
     "host": "gis.siouxfalls.gov",
     "reads": "owner name, unit counts, square footage by parcel",
     "signal": "one owner behind many units via shells (enrichment for a landlord vein)",
     "free": True, "status": "QUEUED", "note": "ticket: ArcGIS reachable; wire owner-cluster enrichment"},
    {"id": "sf_mobile_home_parks", "category": "housing",
     "name": "Sioux Falls manufactured-housing parks (ArcGIS)",
     "host": "gis.siouxfalls.gov",
     "reads": "park name, owner (PARKOWNER), manager, space count per park (Community/17)",
     "signal": "one owner concentrating many parks, joined to a harm signal (the Havenpark/Country View shape) -- concentration alone is legal, so it needs the harm join",
     "free": True, "status": "QUEUED", "note": "ticket: 25 parks reachable with owners; wire owner-concentration x harm (water/complaints/violations) join"},
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
     "free": True, "status": "AVAILABLE", "caller": "run_sky_watch"},
]


def _get_json(url: str, timeout: float = 60.0) -> Any:
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


CMS_DKAN_PAGE = 1000   # the datastore caps a page at 1000 rows (2000 -> HTTP 400)


def _dkan_query(dataset_id: str, conditions: list[tuple[str, str, str]],
                *, max_rows: int = 10000) -> list[dict[str, Any]]:
    """Network. A CMS DKAN datastore query, paged by offset. `conditions` is a
    list of (property, value, operator). The datastore caps a page at 1000, so
    larger sets (e.g. a state's MDS measure rows) come back over several pages;
    max_rows is a safety cap, not an expected limit.
    """
    base: dict[str, str] = {}
    for i, (prop, val, op) in enumerate(conditions):
        base[f"conditions[{i}][property]"] = prop
        base[f"conditions[{i}][value]"] = val
        base[f"conditions[{i}][operator]"] = op
    rows: list[dict[str, Any]] = []
    offset = 0
    while offset < max_rows:
        params = {**base, "limit": str(CMS_DKAN_PAGE), "offset": str(offset)}
        url = f"{CMS_DKAN_QUERY}/{dataset_id}/0?" + urllib.parse.urlencode(params)
        page = _get_json(url).get("results") or []
        rows.extend(page)
        if len(page) < CMS_DKAN_PAGE:
            break
        offset += CMS_DKAN_PAGE
    return rows


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


# ---- CMS Care Compare nursing-home facility lens --------------------------

def _median(values: list[float]) -> float:
    s = sorted(values)
    n = len(s)
    if n == 0:
        return 0.0
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2.0


def care_compare_outliers(provider_rows: list[dict[str, Any]],
                          antipsych_pct_by_ccn: dict[str, float],
                          *, city: str = CITY) -> list[dict[str, Any]]:
    """Pure analysis. Flag a nursing home in the target city that sedates an
    ELEVATED share of its long-stay elderly (antipsychotic % >= the greater of
    an absolute floor and 1.3x the state peer median) yet is rated CLEAN by
    inspectors (overall star rating >= 4). That combination -- real sedation,
    no inspection flag -- is the cold concealed-harm signal; a high-% home that
    ALSO has a bad inspection is already caught by the regulator and is dropped.
    The peer median is computed from the facilities passed in. No model.
    """
    pcts = [p for p in antipsych_pct_by_ccn.values() if p > 0]
    peer_median = _median(pcts)
    threshold = max(CARE_COMPARE_ANTIPSYCH_FLOOR,
                    peer_median * CARE_COMPARE_PEER_MULT)
    out: list[dict[str, Any]] = []
    for r in provider_rows:
        if city.upper() not in (r.get("citytown") or "").upper():
            continue
        ccn = (r.get("cms_certification_number_ccn") or "").strip()
        pct = antipsych_pct_by_ccn.get(ccn)
        if pct is None or pct < threshold:
            continue
        rating = _num(r.get("overall_rating"))
        if rating < CARE_COMPARE_CLEAN_RATING:
            continue  # high-% AND a bad inspection == regulator already on it
        name = (r.get("provider_name") or "").strip()
        health = _num(r.get("health_inspection_rating"))
        deficiencies = int(_num(
            r.get("rating_cycle_1_total_number_of_health_deficiencies")))
        out.append({
            "check": "cms_care_compare_nh",
            "kind": "anomaly",
            "subject": name,
            "summary": (
                f"{name}: {pct:.0f}% of long-stay residents on antipsychotics "
                f"(state median {peer_median:.0f}%) yet rated {int(rating)}/5 "
                f"overall, {int(health)}/5 on health inspection with "
                f"{deficiencies} deficiency(ies) -- elevated sedation, clean "
                "inspection record"),
            "evidence": {
                "ccn": ccn,
                "antipsychotic_long_stay_pct": pct,
                "state_peer_median_pct": round(peer_median, 1),
                "overall_rating": int(rating),
                "health_inspection_rating": int(health),
                "health_deficiencies_last_cycle": deficiencies,
                "chain_name": (r.get("chain_name") or "").strip(),
                "changed_ownership_last_12mo":
                    (r.get("provider_changed_ownership_in_last_12_months")
                     or "").strip(),
                "address": (r.get("provider_address") or "").strip(),
                "city": (r.get("citytown") or "").strip(),
            },
            "source": "CMS Care Compare (nursing-home provider + MDS measures)",
            "why_him": ("a facility's public Medicare quality record; target "
                        "the HOME/operator, records-based, never a resident"),
            "next_record": ("this home's health-deficiency narrative + any "
                            "complaint survey touching medication; cross-ref "
                            "the Part D prescribers at this address"),
        })
    out.sort(key=lambda c: -c["evidence"]["antipsychotic_long_stay_pct"])
    return out


def _fetch_care_compare(city: str = CITY, state: str = STATE
                        ) -> tuple[list[dict[str, Any]], dict[str, float]]:
    """Network. Pull the state's nursing homes (provider info) and the state's
    MDS quality-measure rows, build a CCN -> long-stay antipsychotic % map from
    the antipsychotic measure, and hand both to the pure function to filter and
    judge. Returns (provider_rows, antipsych_pct_by_ccn).
    """
    provider_rows = _dkan_query(
        CMS_NH_PROVIDER_INFO, [("state", state, "=")])
    mds_rows = _dkan_query(CMS_NH_MDS_QM, [("state", state, "=")])
    antipsych_pct_by_ccn: dict[str, float] = {}
    for r in mds_rows:
        if (r.get("measure_code") or "").strip() != CARE_COMPARE_ANTIPSYCH_MEASURE:
            continue  # filtered client-side: a datatype mismatch server-side
                      # would silently return zero rows (a false all-clear)
        ccn = (r.get("cms_certification_number_ccn") or "").strip()
        score = r.get("four_quarter_average_score")
        if ccn and score not in (None, "", "Not Available"):
            antipsych_pct_by_ccn[ccn] = _num(score)
    return provider_rows, antipsych_pct_by_ccn


def run_care_compare(
    fetch: Callable[[], tuple[list[dict[str, Any]], dict[str, float]]] | None = None
) -> dict[str, Any]:
    """One check: fetch (injectable) then analyse."""
    fetch = fetch or _fetch_care_compare
    try:
        provider_rows, antipsych_pct_by_ccn = fetch()
    except Exception as exc:  # noqa: BLE001
        return {"check": "cms_care_compare_nh", "ok": False, "error": str(exc),
                "candidates": []}
    return {"check": "cms_care_compare_nh", "ok": True,
            "rows_scanned": len(provider_rows),
            "candidates": care_compare_outliers(
                provider_rows, antipsych_pct_by_ccn)}


# ---- ADS-B / FAA sky-watch (the kinetic vein) -----------------------------
# The "blacked-out plane into Sioux Falls" vein: watch live aircraft near the
# airport (FSD) for the ones with no public reason to be there -- an opaque or
# foreign-owned business jet that lands, a military/government aircraft, an
# emergency squawk. One landing is never the story (owner-trusts and the odd
# bizjet are common and mostly legit); the story is a REPEAT, so the scanner
# keeps a small rolling log of what it has seen and elevates a tail that comes
# back. Snapshot only -- each run sees what is airborne/on-ground right then.
ADSB_SWEEP = "https://opendata.adsb.fi/api/v2/lat/{lat}/lon/{lon}/dist/{dist}"
FSD_LAT, FSD_LON = 43.582, -96.742      # Sioux Falls Regional (FSD)
SKY_SWEEP_RADIUS_NM = 80                 # the API's search radius
SKY_NEAR_NM = 15.0                       # "at/approaching FSD" vs an overflight
SKY_LOW_ALT_FT = 8000                    # below this near FSD == arriving/leaving
SKY_EMERGENCY_SQUAWKS = frozenset({"7500", "7600", "7700"})
SKY_LOG = OUT_DIR / "sky_log.json"       # rolling tail -> sightings (repeats)
SKY_LOG_MAX = 300                        # cap the log's size
# Airline / cargo / fractional-charter callsign prefixes (ICAO). An aircraft
# whose callsign starts with one of these has a public reason to be in the air;
# the vein is everything else that gets low and close to FSD.
SKY_SCHEDULED_PREFIXES = frozenset({
    "SKW", "AAL", "DAL", "UAL", "SWA", "AAY", "FFT", "NKS", "ASH", "EDV",
    "RPA", "ENY", "JIA", "QXE", "GJS", "MXY", "PDT", "AWI", "FDX", "UPS",
    "GTI", "FD"})
# Owner/operator substrings with an obvious public reason to be low at FSD: the
# airlines and cargo (often broadcasting no callsign on the ground), and local
# air-ambulance/hospital flights. Matched on ownOp so a FedEx 757 sitting on the
# ramp or an Avera medevac PC-12 is not mistaken for an unexplained visitor.
SKY_KNOWN_OPERATOR_MARKERS = (
    "AIRLINES", "AIR LINES", "FEDERAL EXPRESS", "FEDEX", "UPS ", "UNITED PARCEL",
    "SKYWEST", "ENVOY", "REPUBLIC", "MESA", "ENDEAVOR", "ALLEGIANT", "FRONTIER",
    "AVERA", "SANFORD", "LIFE FLIGHT", "LIFEFLIGHT", "AIR MED", "AIRMED",
    "MEDICAL", "MERCY", "HOSPITAL", "AMBULANCE", "CARE FLIGHT", "MEDEVAC",
    "STATE OF SOUTH DAKOTA", "CITY OF SIOUX FALLS", "SOUTH DAKOTA STATE")
# Fractional / charter operators broadcast a known callsign prefix (and register
# signature tail suffixes) even when the ADS-B feed carries no ownOp. A fractional
# jet is a shared-ownership pool rental: the passenger is unknowable from ADS-B, so
# the tail tells us nothing about a specific opaque owner -- it is bizjet noise, not
# a hidden-beneficiary story. (The Westen vein is a TRUST-held tail, e.g. Bank of
# Utah / Wilmington, that lands repeatedly -- never a NetJets pool jet.) Emergency
# and military flags are checked first and are NOT suppressed by this.
SKY_FRACTIONAL_PREFIXES = frozenset({
    "EJA", "NJE", "EJM",   # NetJets / NetJets Europe / Executive Jet Management
    "LXJ",                 # Flexjet
    "XOJ",                 # XO / XOJet
    "JTL",                 # Jet Linx
    "VJT", "VJA",          # VistaJet
    "OPT"})                # Flight Options
SKY_FRACTIONAL_TAIL_SUFFIXES = ("QS", "FX")  # N###QS NetJets, N###FX Flexjet


def _known_operator(owner: str) -> bool:
    up = (owner or "").upper()
    return any(m in up for m in SKY_KNOWN_OPERATOR_MARKERS)


def _is_fractional(callsign: str, tail: str) -> bool:
    """A fractional/charter pool jet, by callsign prefix or signature tail suffix.
    Shared-ownership means the ADS-B tail cannot be tied to one beneficiary, so it
    is noise for the opaque-owner vein."""
    cs = (callsign or "").strip().upper()
    tl = (tail or "").strip().upper()
    if any(cs.startswith(p) for p in SKY_FRACTIONAL_PREFIXES):
        return True
    return bool(tl) and tl.startswith("N") and tl.endswith(SKY_FRACTIONAL_TAIL_SUFFIXES)


def _nm_between(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in nautical miles."""
    r_nm = 3440.065
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dlam / 2) ** 2)
    return r_nm * 2 * math.asin(min(1.0, math.sqrt(a)))


def _is_scheduled(callsign: str) -> bool:
    cs = (callsign or "").strip().upper()
    return any(cs.startswith(p) for p in SKY_SCHEDULED_PREFIXES)


def sky_outliers(aircraft: list[dict[str, Any]],
                 prior: dict[str, dict[str, Any]] | None = None,
                 *, origin_lat: float = FSD_LAT, origin_lon: float = FSD_LON,
                 today: str = "") -> list[dict[str, Any]]:
    """Pure analysis. From an ADS-B snapshot, flag aircraft with no public
    reason to be over/at Sioux Falls: an emergency squawk; a military flag; or
    a non-scheduled aircraft that is on the ground or low AND close to FSD
    (a business jet arriving, not a transcontinental overflight). `prior` is
    the rolling log (tail -> {count, first_seen}); a tail seen before is
    elevated to an anomaly, because the repeat is the story. No model.
    """
    prior = prior or {}
    out: list[dict[str, Any]] = []
    for ac in aircraft:
        tail = (ac.get("r") or "").strip()
        squawk = (ac.get("squawk") or "").strip()
        callsign = (ac.get("flight") or "").strip()
        ac_type = (ac.get("t") or "").strip()
        owner = (ac.get("ownOp") or "").strip()
        military = bool(int(ac.get("dbFlags") or 0) & 1)
        alt_raw = ac.get("alt_baro")
        on_ground = str(alt_raw).lower() == "ground"
        alt = 0.0 if on_ground else _num(alt_raw)
        lat, lon = _num(ac.get("lat")), _num(ac.get("lon"))
        dist = (_nm_between(origin_lat, origin_lon, lat, lon)
                if (lat or lon) else None)
        near_low = (dist is not None and dist <= SKY_NEAR_NM
                    and (on_ground or 0 < alt <= SKY_LOW_ALT_FT))

        emergency = squawk in SKY_EMERGENCY_SQUAWKS
        foreign = bool(tail) and not tail.upper().startswith("N")
        reason = None
        if emergency:
            reason = f"emergency squawk {squawk}"
        elif military and (dist is None or dist <= SKY_SWEEP_RADIUS_NM):
            reason = "military / government aircraft"
        elif (near_low and not _is_scheduled(callsign)
              and not _known_operator(owner)
              and not _is_fractional(callsign, tail)):
            where = "on the ground at" if on_ground else f"{alt:.0f}ft near"
            reason = (f"{'foreign-registered ' if foreign else ''}non-scheduled "
                      f"aircraft {where} FSD ({dist:.0f}nm)")
        if not reason:
            continue

        seen_before = prior.get(tail or callsign, {})
        times = int(seen_before.get("count", 0)) + 1
        first_seen = seen_before.get("first_seen") or today
        label = tail or callsign or "unknown aircraft"
        descr = f"{label}" + (f" ({ac_type})" if ac_type else "")
        if owner:
            descr += f", owner {owner}"
        summary = f"{descr}: {reason}"
        if times >= 2:
            summary += f" -- seen {times} times (repeat; first {first_seen})"
        out.append({
            "check": "sky_watch",
            "kind": "anomaly" if (times >= 2 or emergency or military)
                    else "context",
            "subject": label,
            "summary": summary,
            "evidence": {
                "tail": tail, "type": ac_type, "callsign": callsign,
                "owner_operator": owner, "squawk": squawk,
                "military": military, "foreign_registration": foreign,
                "on_ground": on_ground, "altitude_ft": None if on_ground else alt,
                "distance_from_fsd_nm": None if dist is None else round(dist, 1),
                "times_seen": times, "first_seen": first_seen,
            },
            "source": "ADS-B (adsb.fi) + FAA registry",
            "why_him": ("public flight data; target the AIRCRAFT/owner (an org "
                        "or its trust), records-based, never a person's travel"),
            "next_record": ("FAA registry owner for the tail (registry.faa.gov) "
                            "-- an owner-trust (Bank of Utah / Wilmington) hides "
                            "the beneficiary; then watch for it to come back"),
        })
    out.sort(key=lambda c: -c["evidence"]["times_seen"])
    return out


def _fetch_adsb() -> list[dict[str, Any]]:
    """Network. One ADS-B snapshot of the airspace around FSD."""
    url = ADSB_SWEEP.format(lat=FSD_LAT, lon=FSD_LON, dist=SKY_SWEEP_RADIUS_NM)
    d = _get_json(url)
    return d.get("aircraft") or d.get("ac") or []


def _read_sky_log() -> dict[str, dict[str, Any]]:
    try:
        return json.loads(SKY_LOG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_sky_log(log: dict[str, dict[str, Any]]) -> None:
    # keep the most-recently-seen tails, capped
    if len(log) > SKY_LOG_MAX:
        keep = sorted(log.items(), key=lambda kv: kv[1].get("last_seen", ""),
                      reverse=True)[:SKY_LOG_MAX]
        log = dict(keep)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    SKY_LOG.write_text(json.dumps(log, indent=2, sort_keys=True) + "\n",
                       encoding="utf-8")


def run_sky_watch(fetch: Callable[[], list[dict[str, Any]]] | None = None,
                  *, log_io: bool = True) -> dict[str, Any]:
    """One check: fetch the snapshot, read the rolling log so repeats are
    known, analyse, then record this run's flagged tails back to the log. Set
    log_io=False in tests to keep it pure (no file touched).
    """
    fetch = fetch or _fetch_adsb
    try:
        aircraft = fetch()
    except Exception as exc:  # noqa: BLE001
        return {"check": "sky_watch", "ok": False, "error": str(exc),
                "candidates": []}
    today = _utcnow()[:10]
    prior = _read_sky_log() if log_io else {}
    candidates = sky_outliers(aircraft, prior, today=today)
    if log_io:
        for c in candidates:
            key = c["evidence"]["tail"] or c["evidence"]["callsign"]
            if not key:
                continue
            row = prior.get(key, {})
            prior[key] = {
                "count": int(row.get("count", 0)) + 1,
                "first_seen": row.get("first_seen") or today,
                "last_seen": today,
                "type": c["evidence"]["type"],
                "owner_operator": c["evidence"]["owner_operator"],
            }
        _write_sky_log(prior)
    return {"check": "sky_watch", "ok": True, "rows_scanned": len(aircraft),
            "candidates": candidates}


# ---- orchestration ---------------------------------------------------------

# ---- Sioux Falls food-safety recurring-hazard clusters --------------------
# Local records the cloud is NOT walled off from: the city publishes its food
# inspection line-items as ArcGIS feature layers (the Socrata portal 502s from
# a datacenter, but ArcGIS answers -- the same host that serves parcels). A
# single critical violation is the inspector's routine work; the COLD pattern
# is an establishment cited for the SAME critical hazard again and again that
# is still open -- a persistent, uncorrected foodborne-illness risk nobody has
# assembled. This is the "violation, no formal action" cut (raw inspection
# line-items, not an enforcement record that would mean the regulator acted).

SF_GIS = "https://gis.siouxfalls.gov/arcgis/rest/services"
SF_FOOD_VIOLATION_LAYERS = (
    f"{SF_GIS}/Data/Safety/MapServer/20",   # Service Violations
    f"{SF_GIS}/Data/Safety/MapServer/19",   # Processing Violations
)
SF_FOOD_SITES_LAYER = f"{SF_GIS}/Data/Safety/MapServer/17"  # Restaurant Sites

FOOD_FLAG_CRITICAL = 5        # total critical violations in the published window
FOOD_FLAG_REPEAT = 3          # ... with the SAME critical code cited this often


def _arcgis_query(layer: str, where: str, out_fields: str,
                  *, max_rows: int = 6000) -> list[dict[str, Any]]:
    """Network. Page an ArcGIS feature layer's attributes. Deduped by OBJECTID
    and stopped when a page adds nothing new, so a layer that silently ignores
    resultOffset (not all advertise pagination) returns its first page once
    rather than looping forever.
    """
    fields = out_fields if "OBJECTID" in out_fields else out_fields + ",OBJECTID"
    rows: dict[Any, dict[str, Any]] = {}
    offset = 0
    while len(rows) < max_rows:
        params = {
            "where": where, "outFields": fields, "returnGeometry": "false",
            "resultOffset": str(offset), "resultRecordCount": "1000", "f": "json",
        }
        url = f"{layer}/query?" + urllib.parse.urlencode(params)
        page = _get_json(url).get("features") or []
        before = len(rows)
        for feat in page:
            attrs = feat.get("attributes", {})
            rows[attrs.get("OBJECTID")] = attrs
        if len(page) < 1000 or len(rows) == before:
            break
        offset += 1000
    return list(rows.values())


def _fetch_sf_food_violations() -> dict[str, Any]:
    """Network. Critical food-inspection violations + the site name map."""
    viols: list[dict[str, Any]] = []
    for layer in SF_FOOD_VIOLATION_LAYERS:
        viols.extend(_arcgis_query(
            layer, "CRITICAL='Y'",
            "SITE_NO,CONTROL,DATE,TXT_VCODE,VIOLATION,INV_TYPE"))
    site_ids = sorted({int(v["SITE_NO"]) for v in viols
                       if v.get("SITE_NO") is not None})
    sites: dict[int, dict[str, Any]] = {}
    if site_ids:
        where = "SITE_NO IN (%s)" % ",".join(str(s) for s in site_ids)
        for attrs in _arcgis_query(
                SF_FOOD_SITES_LAYER, where,
                "SITE_NO,SITE_NAME,FULL_ADDRESS,SITE_TYPE_DESC,SCORE1,SCORE2"):
            if attrs.get("SITE_NO") is not None:
                sites.setdefault(int(attrs["SITE_NO"]), attrs)
    return {"violations": viols, "sites": sites}


def food_hazard_clusters(data: dict[str, Any], *,
                         flag_critical: int = FOOD_FLAG_CRITICAL,
                         flag_repeat: int = FOOD_FLAG_REPEAT
                         ) -> list[dict[str, Any]]:
    """Pure analysis. Cluster critical violations by site; flag a site cited
    for the SAME critical code >= flag_repeat times AND >= flag_critical
    criticals overall, across >= 2 inspection dates -- a recurring, uncorrected
    hazard. Deterministic, no model. A flag is a QUESTION: at judgment the
    engine checks whether the health dept closed/placarded it (that would mean
    the regulator acted -> not cold).
    """
    from collections import Counter, defaultdict
    by_site: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for v in data.get("violations", []):
        if v.get("SITE_NO") is None:
            continue
        by_site[int(v["SITE_NO"])].append(v)
    sites = data.get("sites", {})
    out: list[dict[str, Any]] = []
    for site_no, vs in by_site.items():
        dates = {v.get("DATE") for v in vs if v.get("DATE")}
        if len(dates) < 2:
            continue
        codes = Counter((v.get("TXT_VCODE") or "").strip() for v in vs
                        if (v.get("TXT_VCODE") or "").strip())
        top_code, top_n = (codes.most_common(1) or [("", 0)])[0]
        if len(vs) < flag_critical or top_n < flag_repeat:
            continue
        site = sites.get(site_no) or sites.get(str(site_no)) or {}
        name = (site.get("SITE_NAME") or f"site #{site_no}").strip()
        addr = (site.get("FULL_ADDRESS") or "").strip()
        # what the repeated hazard IS (the violation text for the top code)
        hazard = next((((v.get("VIOLATION") or "").strip())
                       for v in vs
                       if (v.get("TXT_VCODE") or "").strip() == top_code
                       and (v.get("VIOLATION") or "").strip()), top_code)
        recurring = sorted(((c, n) for c, n in codes.items() if n >= 2),
                           key=lambda cn: (-cn[1], cn[0]))
        summary = (
            f"{name}" + (f" ({addr})" if addr else "")
            + f": {len(vs)} critical food-safety violations across "
            + f"{len(dates)} inspections, including '{hazard}' cited {top_n}x "
            + "-- a recurring, uncorrected hazard")
        out.append({
            "check": "sf_food_safety",
            "kind": "anomaly",
            "subject": name,
            "summary": summary,
            "evidence": {
                "site_no": site_no,
                "address": addr,
                "site_type": (site.get("SITE_TYPE_DESC") or "").strip(),
                "critical_violations": len(vs),
                "inspections": len(dates),
                "recent_scores": [s for s in (site.get("SCORE1"),
                                              site.get("SCORE2"))
                                  if s is not None],
                "recurring_critical_codes": [
                    {"code": c, "times": n} for c, n in recurring],
                "worst_hazard": hazard,
            },
            "source": "Sioux Falls food inspection violations (city ArcGIS)",
            "why_him": ("a licensed food establishment's public inspection "
                        "record; the business is the target, records-based, "
                        "never an individual"),
            "next_record": ("whether the health dept closed or placarded it "
                            "(if so, DISQUALIFIED -- the regulator acted); "
                            "otherwise the full inspection history and any "
                            "illness complaints tied to it"),
        })
    out.sort(key=lambda c: (-c["evidence"]["critical_violations"], c["subject"]))
    return out


def run_sf_food_safety(fetch: Callable[[], dict[str, Any]] | None = None
                       ) -> dict[str, Any]:
    """One check: fetch (injectable) then analyse."""
    fetch = fetch or _fetch_sf_food_violations
    try:
        data = fetch()
    except Exception as exc:  # noqa: BLE001
        return {"check": "sf_food_safety", "ok": False, "error": str(exc),
                "candidates": []}
    rows = len(data.get("violations", []))
    return {"check": "sf_food_safety", "ok": True, "rows_scanned": rows,
            "candidates": food_hazard_clusters(data)}


CHECKS: list[Callable[[], dict[str, Any]]] = [
    run_cms_partd, run_fda_recalls, run_epa_echo, run_care_compare,
    run_sky_watch, run_sf_food_safety,
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
