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


def _nh(name, ccn, *, city="Sioux Falls", rating=5, health=5, deficiencies=0):
    return {"cms_certification_number_ccn": ccn, "provider_name": name,
            "citytown": city, "overall_rating": rating,
            "health_inspection_rating": health,
            "rating_cycle_1_total_number_of_health_deficiencies": deficiencies,
            "provider_address": "1 Care Way", "chain_name": "",
            "provider_changed_ownership_in_last_12_months": "N"}


class CareCompareOutliers(unittest.TestCase):
    def test_flags_elevated_sedation_with_a_clean_inspection(self):
        rows = [_nh("Quiet Pines", "435001", rating=5, health=5),
                _nh("Low Home", "435002", rating=5)]
        pct = {"435001": 30.0, "435002": 8.0}
        out = inv.care_compare_outliers(rows, pct)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["subject"], "Quiet Pines")
        self.assertEqual(out[0]["evidence"]["antipsychotic_long_stay_pct"], 30.0)

    def test_skips_high_pct_home_with_a_bad_inspection(self):
        # high-% AND a bad rating == regulator already on it == not cold
        rows = [_nh("Flagged Home", "435003", rating=2, health=1, deficiencies=9)]
        self.assertEqual(inv.care_compare_outliers(rows, {"435003": 35.0}), [])

    def test_skips_a_home_below_the_floor(self):
        rows = [_nh("Normal Home", "435004", rating=5)]
        self.assertEqual(inv.care_compare_outliers(rows, {"435004": 12.0}), [])

    def test_threshold_is_relative_to_the_state_peer_median(self):
        # median of peers is high, so a merely-floor-level home is NOT an outlier
        rows = [_nh("A", "1", rating=5), _nh("B", "2", rating=5),
                _nh("C", "3", rating=5)]
        pct = {"1": 40.0, "2": 40.0, "3": 16.0}  # median 40 -> threshold 52
        out = inv.care_compare_outliers(rows, pct)
        self.assertEqual(out, [])  # nothing reaches 1.3x median (52%)

    def test_skips_other_city(self):
        rows = [_nh("Faraway NH", "435005", city="Aberdeen", rating=5)]
        self.assertEqual(inv.care_compare_outliers(rows, {"435005": 40.0}), [])

    def test_sorted_by_antipsychotic_pct_descending(self):
        rows = [_nh("Lower", "1", rating=5), _nh("Higher", "2", rating=5)]
        # extra low peers keep the median low so the floor (15%) binds and both
        # flag; then the two are ordered by pct
        pct = {"1": 22.0, "2": 33.0, "x": 5.0, "y": 5.0, "z": 5.0}
        out = inv.care_compare_outliers(rows, pct)
        self.assertEqual([c["subject"] for c in out], ["Higher", "Lower"])


def _ac(r="N123AB", *, t="GLEX", flight="", ownOp="", squawk="1200",
        alt_baro="ground", lat=43.582, lon=-96.742, dbFlags=0):
    return {"r": r, "t": t, "flight": flight, "ownOp": ownOp, "squawk": squawk,
            "alt_baro": alt_baro, "lat": lat, "lon": lon, "dbFlags": dbFlags}


class SkyWatch(unittest.TestCase):
    def test_flags_a_nonscheduled_jet_on_the_ground_at_fsd(self):
        out = inv.sky_outliers([_ac("N827TF", ownOp="AVANDRA LLC C/O BANK OF UTAH")])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["subject"], "N827TF")
        self.assertEqual(out[0]["kind"], "context")  # first sighting
        self.assertEqual(out[0]["evidence"]["times_seen"], 1)

    def test_a_repeat_tail_is_elevated_to_an_anomaly(self):
        prior = {"N827TF": {"count": 1, "first_seen": "2026-11-01"}}
        out = inv.sky_outliers([_ac("N827TF")], prior, today="2026-11-06")
        self.assertEqual(out[0]["kind"], "anomaly")
        self.assertEqual(out[0]["evidence"]["times_seen"], 2)
        self.assertIn("seen 2 times", out[0]["summary"])

    def test_emergency_squawk_is_flagged_anywhere(self):
        # far away and high, but squawking 7700
        out = inv.sky_outliers([_ac("N55X", squawk="7700", alt_baro=38000,
                                     lat=44.5, lon=-97.9)])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["kind"], "anomaly")

    def test_military_is_flagged(self):
        out = inv.sky_outliers([_ac("02-4561", dbFlags=1, alt_baro=12000,
                                     lat=43.7, lon=-96.9)])
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0]["evidence"]["military"])

    def test_skips_a_scheduled_airline_landing(self):
        out = inv.sky_outliers([_ac("N901SW", flight="SKW1234", alt_baro=3000)])
        self.assertEqual(out, [])

    def test_skips_known_operators_by_owner(self):
        # a FedEx jet on the ramp (no callsign) and a hospital medevac have an
        # obvious public reason -- not unexplained visitors
        fedex = _ac("N920FD", t="B752", flight="", ownOp="FEDERAL EXPRESS CORP",
                    alt_baro="ground", lat=43.582, lon=-96.742)
        medevac = _ac("N911MN", t="PC12", flight="N911MN", ownOp="AVERA MCKENNAN",
                      alt_baro=4000, lat=43.6, lon=-96.8)
        self.assertEqual(inv.sky_outliers([fedex, medevac]), [])

    def test_skips_a_fractional_charter_jet(self):
        # the live 2026-11-06 false positive: a NetJets Citation (callsign EJA###,
        # tail N###QS) on the ground at FSD with an empty ownOp. A shared-pool jet's
        # passenger is unknowable from ADS-B, so it is noise for the opaque-owner vein.
        netjets_cs = _ac("N694QS", t="C68A", flight="EJA694", ownOp="",
                         alt_baro="ground", lat=43.582, lon=-96.742)
        self.assertEqual(inv.sky_outliers([netjets_cs]), [])
        # excluded by the signature tail suffix alone, even with no callsign
        netjets_tail = _ac("N694QS", t="C68A", flight="", ownOp="",
                           alt_baro="ground", lat=43.582, lon=-96.742)
        self.assertEqual(inv.sky_outliers([netjets_tail]), [])
        # and a Flexjet N###FX
        flexjet = _ac("N612FX", t="GL7T", flight="LXJ612", ownOp="",
                      alt_baro="ground", lat=43.582, lon=-96.742)
        self.assertEqual(inv.sky_outliers([flexjet]), [])

    def test_a_fractional_jet_with_an_emergency_squawk_still_flags(self):
        # the fractional exclusion must not suppress a real emergency
        out = inv.sky_outliers([_ac("N694QS", flight="EJA694", squawk="7700",
                                     alt_baro=38000, lat=44.5, lon=-97.9)])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["kind"], "anomaly")

    def test_skips_a_high_overflight(self):
        # a bizjet transiting at altitude far from FSD is noise
        out = inv.sky_outliers([_ac("N1GL", alt_baro=41000, lat=44.3, lon=-97.6)])
        self.assertEqual(out, [])

    def test_foreign_registration_near_and_low_is_noted(self):
        out = inv.sky_outliers([_ac("M-YJET", alt_baro=4000)])
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0]["evidence"]["foreign_registration"])
        self.assertIn("foreign", out[0]["summary"])

    def test_sorted_by_times_seen_descending(self):
        prior = {"N2": {"count": 3, "first_seen": "2026-10-01"}}
        out = inv.sky_outliers([_ac("N1"), _ac("N2")], prior, today="2026-11-06")
        self.assertEqual([c["subject"] for c in out], ["N2", "N1"])


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

    def test_care_compare_injected_fetch_no_network(self):
        rows = [_nh("Quiet Pines", "435001", rating=5)]
        pct = {"435001": 30.0, "a": 5.0, "b": 5.0, "c": 5.0}  # low peers -> floor binds
        res = inv.run_care_compare(fetch=lambda: (rows, pct))
        self.assertTrue(res["ok"])
        self.assertEqual(res["check"], "cms_care_compare_nh")
        self.assertEqual(res["rows_scanned"], 1)
        self.assertEqual(res["candidates"][0]["subject"], "Quiet Pines")

    def test_care_compare_fetch_failure_is_captured(self):
        def boom():
            raise RuntimeError("care compare down")
        res = inv.run_care_compare(fetch=boom)
        self.assertFalse(res["ok"])
        self.assertIn("down", res["error"])
        self.assertEqual(res["candidates"], [])

    def test_sky_watch_injected_fetch_no_network_no_log(self):
        res = inv.run_sky_watch(fetch=lambda: [_ac("N827TF")], log_io=False)
        self.assertTrue(res["ok"])
        self.assertEqual(res["check"], "sky_watch")
        self.assertEqual(res["rows_scanned"], 1)
        self.assertEqual(res["candidates"][0]["subject"], "N827TF")

    def test_sky_watch_fetch_failure_is_captured(self):
        def boom():
            raise RuntimeError("adsb down")
        res = inv.run_sky_watch(fetch=boom, log_io=False)
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

    def test_each_source_reports_its_own_flagged_count_not_the_grand_total(self):
        def _cand(check):
            return {"check": check, "subject": "X", "summary": "s",
                    "evidence": {}, "next_record": "n"}
        one = lambda: {"check": "one", "ok": True, "rows_scanned": 5,
                       "candidates": [_cand("one")]}
        three = lambda: {"check": "three", "ok": True, "rows_scanned": 9,
                         "candidates": [_cand("three")] * 3}
        with mock.patch.object(inv, "CHECKS", [one, three]):
            report = inv.scan(write=False)
        self.assertEqual(report["candidate_count"], 4)
        self.assertEqual(report["checks"][0]["flagged"], 1)
        self.assertEqual(report["checks"][1]["flagged"], 3)
        md = inv._markdown(report)
        self.assertIn("scanned 5 rows, 1 flagged", md)
        self.assertIn("scanned 9 rows, 3 flagged", md)
        self.assertNotIn("4 flagged", md)

    def test_markdown_renders_without_candidates(self):
        report = {"city": "SIOUX FALLS, SD", "generated_at": "now",
                  "checks": [{"check": "stub", "ok": True, "rows_scanned": 0}],
                  "candidate_count": 0, "candidates": []}
        md = inv._markdown(report)
        self.assertIn("No anomalies", md)


if __name__ == "__main__":
    unittest.main()
