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


# Registry of sources, honest about what is wired. Data only; no behaviour.
SOURCES: list[dict[str, Any]] = [
    {
        "id": "cms_partd_opioids",
        "name": "CMS Medicare Part D prescribers (by provider)",
        "reads": "every Part D prescriber's opioid / long-acting-opioid volume",
        "anomaly": "a non-pain specialty carrying a pain-clinic opioid load",
        "free": True,
        "status": "AVAILABLE",
    },
    {
        "id": "cms_partd_antipsychotics_ge65",
        "name": "CMS Medicare Part D prescribers (by provider)",
        "reads": "every Part D prescriber's antipsychotic volume to patients 65+",
        "anomaly": "a non-psychiatric specialty sedating the elderly (restraint)",
        "free": True,
        "status": "AVAILABLE",
    },
    {
        "id": "sba_ppp_small_loans",
        "name": "SBA PPP FOIA loan data (under $150k)",
        "reads": "sole-proprietor loans; amount vs jobs; address clustering",
        "anomaly": "fake one-person 'businesses' at ~$20,833 clustered at homes",
        "free": True,
        "status": "NOT_BUILT",
        "note": "ticket: stream public_up_to_150k_*.csv, filter borrower=SF SD",
    },
    {
        "id": "usaspending_absence",
        "name": "USAspending awards vs business registration",
        "reads": "federal money to an entity with no matching registration/site",
        "anomaly": "money arriving where no real operation appears to exist",
        "free": True,
        "status": "NOT_BUILT",
        "note": "ticket: absence check -- award present, SoS/web presence absent",
    },
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


# ---- orchestration ---------------------------------------------------------

CHECKS: list[Callable[[], dict[str, Any]]] = [run_cms_partd]


def scan(write: bool = True) -> dict[str, Any]:
    """Run every wired check, collect candidates, optionally write them."""
    results = [check() for check in CHECKS]
    candidates: list[dict[str, Any]] = []
    for res in results:
        candidates.extend(res.get("candidates", []))
    report = {
        "generated_at": _utcnow(),
        "city": f"{CITY}, {STATE}",
        "checks": [{k: v for k, v in r.items() if k != "candidates"}
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
                        f" {report['candidate_count']} flagged"
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
