"""The deterministic investigations scanner flags the right anomalies and
never touches the network under test."""

import unittest
from unittest import mock

from aletheia import investigations as inv


def _row(last, first, specialty, la=0, *, tot=1000, opioid=0, npi="1", st="1 Main",
         ap=0, ap_benes=0, age=70.0):
    return {
        "Prscrbr_NPI": npi,
        "Prscrbr_Last_Org_Name": last,
        "Prscrbr_First_Name": first,
        "Prscrbr_Type": specialty,
        "Prscrbr_St1": st,
        "Prscrbr_City": "Sioux Falls",
        "Tot_Clms": tot,
        "Opioid_Tot_Clms": opioid,
        "Opioid_LA_Tot_Clms": la,
        "Antpsyct_GE65_Tot_Clms": ap,
        "Antpsyct_GE65_Tot_Benes": ap_benes,
        "Bene_Avg_Age": age,
    }


class OpioidOutliers(unittest.TestCase):
    def test_flags_non_pain_specialty_with_heavy_long_acting_load(self):
        rows = [_row("Welch", "David", "Physician Assistant", 1091,
                     tot=5223, opioid=3238)]
        out = inv.opioid_outliers(rows)
        self.assertEqual(len(out), 1)
        c = out[0]
        self.assertEqual(c["subject"], "Welch, David")
        self.assertEqual(c["kind"], "anomaly")
        self.assertEqual(c["evidence"]["long_acting_opioid_claims"], 1091)
        self.assertEqual(c["evidence"]["opioid_share_pct"], 62.0)

    def test_skips_expected_pain_specialty(self):
        rows = [_row("Cho", "Myung", "Physical Medicine and Rehabilitation", 454)]
        self.assertEqual(inv.opioid_outliers(rows), [])

    def test_skips_below_threshold(self):
        rows = [_row("Tiny", "Tom", "Family Practice", 5)]
        self.assertEqual(inv.opioid_outliers(rows), [])

    def test_sorted_by_long_acting_load_descending(self):
        rows = [
            _row("Low", "L", "Family Practice", 50),
            _row("High", "H", "Nurse Practitioner", 200),
        ]
        out = inv.opioid_outliers(rows)
        self.assertEqual([c["subject"] for c in out], ["High, H", "Low, L"])

    def test_empty_rows(self):
        self.assertEqual(inv.opioid_outliers([]), [])


def _recall(firm, cls, *, kind="food", city="Sioux Falls", reason="contamination"):
    return {"recalling_firm": firm, "classification": cls, "kind": kind,
            "city": city, "state": "SD", "reason_for_recall": reason}


class FdaRecallOutliers(unittest.TestCase):
    def test_flags_a_single_class_I(self):
        out = inv.fda_recall_outliers([_recall("Acme Foods", "Class I")])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["subject"], "Acme Foods")
        self.assertTrue(out[0]["evidence"]["class_I"])
        self.assertEqual(out[0]["kind"], "context")

    def test_flags_a_repeat_pattern_even_without_class_I(self):
        out = inv.fda_recall_outliers([_recall("Repeat LLC", "Class II"),
                                       _recall("Repeat LLC", "Class III", kind="drug")])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["evidence"]["recall_count"], 2)
        self.assertEqual(out[0]["evidence"]["kinds"], ["drug", "food"])

    def test_single_non_class_I_is_not_flagged(self):
        self.assertEqual(inv.fda_recall_outliers([_recall("Once Co", "Class II")]), [])

    def test_a_firm_in_another_city_is_skipped(self):
        self.assertEqual(
            inv.fda_recall_outliers([_recall("Faraway", "Class I", city="Rapid City")]), [])

    def test_class_I_sorts_before_mere_repeats(self):
        out = inv.fda_recall_outliers([
            _recall("Two", "Class II"), _recall("Two", "Class III"),
            _recall("One", "Class I")])
        self.assertEqual([c["subject"] for c in out], ["One", "Two"])


def _echo(name, *, city="Sioux Falls", fed="N", snc="N", formal=0,
          penalties=0.0, status="Violation Identified"):
    return {"FacName": name, "FacCity": city, "FacFederalFlg": fed,
            "FacSNCFlg": snc, "FacFormalActionCount": formal,
            "FacTotalPenalties": penalties, "FacComplianceStatus": status,
            "FacStreet": "1 Industrial Rd", "RegistryID": "110"}


class EpaEchoViolators(unittest.TestCase):
    def test_flags_a_private_significant_noncomplier(self):
        out = inv.epa_echo_violators([_echo("Acme Plating Inc", snc="Y")])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["subject"], "Acme Plating Inc")
        self.assertTrue(out[0]["evidence"]["significant_noncomplier"])

    def test_flags_a_formal_action_or_penalty(self):
        self.assertEqual(len(inv.epa_echo_violators([_echo("B Co", formal=2)])), 1)
        self.assertEqual(len(inv.epa_echo_violators([_echo("C Co", penalties=5000.0)])), 1)

    def test_skips_a_clean_facility(self):
        self.assertEqual(inv.epa_echo_violators([_echo("Clean LLC", status="No Violation")]), [])

    def test_skips_federal_and_municipal(self):
        self.assertEqual(inv.epa_echo_violators([_echo("Ellsworth AFB", fed="Y", snc="Y")]), [])
        self.assertEqual(
            inv.epa_echo_violators([_echo("City of Sioux Falls WWTP", snc="Y")]), [])

    def test_skips_other_city(self):
        self.assertEqual(
            inv.epa_echo_violators([_echo("Faraway Mfg", snc="Y", city="Aberdeen")]), [])

    def test_snc_sorts_before_lesser_violations(self):
        out = inv.epa_echo_violators([_echo("Minor", penalties=100.0),
                                      _echo("Serious", snc="Y")])
        self.assertEqual([c["subject"] for c in out], ["Serious", "Minor"])


class AntipsychoticGE65Outliers(unittest.TestCase):
    def test_flags_non_psych_specialty_sedating_the_elderly(self):
        rows = [_row("Geis", "Tara", "Family Practice", ap=543, ap_benes=33)]
        out = inv.antipsychotic_ge65_outliers(rows)
        self.assertEqual(len(out), 1)
        c = out[0]
        self.assertEqual(c["subject"], "Geis, Tara")
        self.assertEqual(c["evidence"]["antipsychotic_ge65_claims"], 543)
        self.assertEqual(c["evidence"]["antipsychotic_ge65_patients"], 33)
        self.assertEqual(c["evidence"]["claims_per_patient"], 16.5)

    def test_skips_expected_psych_specialty(self):
        rows = [_row("Mind", "M", "Psychiatry", ap=800, ap_benes=50)]
        self.assertEqual(inv.antipsychotic_ge65_outliers(rows), [])

    def test_skips_below_threshold(self):
        rows = [_row("Few", "F", "Family Practice", ap=20, ap_benes=3)]
        self.assertEqual(inv.antipsychotic_ge65_outliers(rows), [])

    def test_suppressed_patient_count_leaves_ratio_none(self):
        rows = [_row("Hidden", "H", "Internal Medicine", ap=150, ap_benes=0)]
        out = inv.antipsychotic_ge65_outliers(rows)
        self.assertEqual(len(out), 1)
        self.assertIsNone(out[0]["evidence"]["antipsychotic_ge65_patients"])
        self.assertIsNone(out[0]["evidence"]["claims_per_patient"])

    def test_sorted_by_load_descending(self):
        rows = [_row("Low", "L", "Family Practice", ap=120),
                _row("High", "H", "Nurse Practitioner", ap=600)]
        out = inv.antipsychotic_ge65_outliers(rows)
        self.assertEqual([c["subject"] for c in out], ["High, H", "Low, L"])


class RunCheck(unittest.TestCase):
    def test_injected_fetch_is_used_no_network(self):
        rows = [_row("Welch", "David", "Physician Assistant", 1091)]
        res = inv.run_cms_partd(fetch=lambda: ("2023", rows))
        self.assertTrue(res["ok"])
        self.assertEqual(res["check"], "cms_partd")
        self.assertEqual(res["data_year"], "2023")
        self.assertEqual(res["rows_scanned"], 1)
        self.assertEqual(res["candidates"][0]["data_year"], "2023")

    def test_one_fetch_runs_every_lens(self):
        rows = [_row("Welch", "David", "Physician Assistant", 1091),
                _row("Geis", "Tara", "Family Practice", ap=543, ap_benes=33)]
        calls = []

        def fetch():
            calls.append(1)
            return ("2023", rows)

        res = inv.run_cms_partd(fetch=fetch)
        self.assertEqual(len(calls), 1)  # fetched ONCE, not once per lens
        checks = {c["check"] for c in res["candidates"]}
        self.assertEqual(checks, {"cms_partd_opioids", "cms_partd_antipsychotics_ge65"})

    def test_fetch_failure_is_captured_not_raised(self):
        def boom():
            raise RuntimeError("CMS unreachable")
        res = inv.run_cms_partd(fetch=boom)
        self.assertFalse(res["ok"])
        self.assertIn("unreachable", res["error"])
        self.assertEqual(res["candidates"], [])

    def test_fda_injected_fetch_no_network(self):
        res = inv.run_fda_recalls(fetch=lambda: [_recall("Acme", "Class I")])
        self.assertTrue(res["ok"])
        self.assertEqual(res["check"], "fda_recalls")
        self.assertEqual(res["candidates"][0]["subject"], "Acme")

    def test_fda_fetch_failure_is_captured(self):
        def boom():
            raise RuntimeError("fda down")
        res = inv.run_fda_recalls(fetch=boom)
        self.assertFalse(res["ok"])
        self.assertIn("down", res["error"])
        self.assertEqual(res["candidates"], [])

    def test_echo_injected_fetch_no_network(self):
        res = inv.run_epa_echo(fetch=lambda: [_echo("Acme Plating Inc", snc="Y")])
        self.assertTrue(res["ok"])
        self.assertEqual(res["check"], "epa_echo")
        self.assertEqual(res["candidates"][0]["subject"], "Acme Plating Inc")

    def test_echo_fetch_failure_is_captured(self):
        def boom():
            raise RuntimeError("echo down")
        res = inv.run_epa_echo(fetch=boom)
        self.assertFalse(res["ok"])
        self.assertIn("down", res["error"])
        self.assertEqual(res["candidates"], [])


class Scan(unittest.TestCase):
    def test_scan_assembles_and_does_not_write_when_told(self):
        stub = lambda: {"check": "stub", "ok": True, "rows_scanned": 2,
                        "candidates": [{"check": "stub", "subject": "X",
                                        "summary": "s", "evidence": {},
                                        "next_record": "n"}]}
        with mock.patch.object(inv, "CHECKS", [stub]):
            report = inv.scan(write=False)
        self.assertEqual(report["candidate_count"], 1)
        self.assertEqual(report["checks"][0]["check"], "stub")
        self.assertNotIn("candidates", report["checks"][0])

    def test_markdown_renders_without_candidates(self):
        report = {"city": "SIOUX FALLS, SD", "generated_at": "now",
                  "checks": [{"check": "stub", "ok": True, "rows_scanned": 0}],
                  "candidate_count": 0, "candidates": []}
        md = inv._markdown(report)
        self.assertIn("No anomalies", md)


if __name__ == "__main__":
    unittest.main()
