"""Live 2026-09-23 Taranis got three applications in one night: "Remote",
"Hybrid" and "On-site Associate Customer Success Representative" - one job,
three seats. How the seat is worked is not what the job is."""
import unittest

from aletheia import apply_run


class OneRoleThreeWays(unittest.TestCase):
    def test_the_work_mode_words_do_not_make_a_different_job(self):
        keys = {apply_run.role_key("Taranis", t) for t in (
            "Remote Associate Customer Success Representative",
            "Hybrid Associate Customer Success Representative",
            "On-site Associate Customer Success Representative - Taranis",
            "Associate Customer Success Representative (Remote)")}
        self.assertEqual(len(keys), 1, keys)

    def test_a_level_or_a_region_is_still_a_different_job(self):
        self.assertNotEqual(apply_run.role_key("Datadog", "Technical Account Manager 3 - East"),
                            apply_run.role_key("Datadog", "Technical Account Manager 2 - West"))
        self.assertNotEqual(apply_run.role_key("Databricks", "Business Development Representative"),
                            apply_run.role_key("Databricks", "Frontier AI Lab Account Executive"))


if __name__ == "__main__":
    unittest.main()
