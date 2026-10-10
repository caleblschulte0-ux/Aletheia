import datetime as dt
import unittest

from aletheia import hunt_funnel


class SentBySystem(unittest.TestCase):
    def test_names_systems_never_employers(self):
        now = dt.datetime(2026, 10, 10, 18, tzinfo=dt.timezone.utc)
        at = "2026-10-10T15:00:00Z"
        rows = [{"state": s, "url": u, "staged_at": at, "submitted_at": at}
                for s, u in (("SUBMITTED", "https://boards.greenhouse.io/acme/jobs/1"),
                             ("SUBMITTED", "https://careers.acme.example/jobs/2"),
                             ("SUBMITTED", "https://careers.other.example/jobs/3"))]
        out = hunt_funnel.counts(rows, now=now)
        self.assertEqual(out["sent_by_system"], {"employer_site": 2, "greenhouse": 1})
        self.assertNotIn("acme", str(out["sent_by_system"]))


if __name__ == "__main__":
    unittest.main()
