"""The deterministic investigations scanner flags the right anomalies and
never touches the network under test."""

import unittest
from unittest import mock

from aletheia import investigations as inv


def _row(last, first, specialty, la, *, tot=1000, opioid=0, npi="1", st="1 Main"):
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


class RunCheck(unittest.TestCase):
    def test_injected_fetch_is_used_no_network(self):
        rows = [_row("Welch", "David", "Physician Assistant", 1091)]
        res = inv.run_cms_opioids(fetch=lambda: ("2023", rows))
        self.assertTrue(res["ok"])
        self.assertEqual(res["data_year"], "2023")
        self.assertEqual(res["rows_scanned"], 1)
        self.assertEqual(res["candidates"][0]["data_year"], "2023")

    def test_fetch_failure_is_captured_not_raised(self):
        def boom():
            raise RuntimeError("CMS unreachable")
        res = inv.run_cms_opioids(fetch=boom)
        self.assertFalse(res["ok"])
        self.assertIn("unreachable", res["error"])
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
