"""A money-worded link on a job posting is not the way on.

Live 2026-10-07 two applications ended "refused: spends money" on posting
pages: Greenhouse and others link a "Pay Transparency Policy", and with no
final button on the page the gate read that link as the way on and refused
the whole mission. An application never charges him. On any other errand
the refusal stands, and on a job the link is still never pressed.
"""
import unittest

from aletheia import browser_loop, browser_mission as bm, job_skill, page_state as ps

GOAL = "apply for this job"
URL = "https://jobs.example.com/acme/123"


def posting(*extra):
    return {"url": URL, "state": ps.CONTENT, "title": "Billing Specialist", "text": "About the role",
            "targets": [{"id": "t1", "role": "link", "label": "Apply for this job", "href": URL + "/apply"},
                        {"id": "t2", "role": "link", "label": "Pay Transparency Policy",
                         "href": "https://acme.example.com/pay-transparency"}, *extra],
            "evidence": [], "_refs": {"t1": "#a", "t2": "#b"}}


class APayLinkIsNotTheWayOn(unittest.TestCase):
    def test_on_a_job_the_gate_lets_the_loop_go_on(self):
        record = bm.open_mission(GOAL, URL)
        self.assertIsNone(browser_loop._gate(None, None, posting(), record, GOAL, [], [],
                                             skill=job_skill.JobApplication()))
        self.assertNotEqual(bm.load(record["id"]).get("state"), bm.REFUSED)

    def test_it_is_still_never_chosen(self):
        obs = posting()
        pay = obs["targets"][1]
        self.assertEqual(browser_loop._kind(pay, obs), ps.SPEND)
        record = bm.open_mission(GOAL, URL)
        # Even a model that names it gets nothing to press.
        chosen = browser_loop._ask_model(lambda *a: {"target": "t2"}, GOAL, obs, record)
        self.assertIsNone(chosen)

    def test_any_other_errand_is_still_refused(self):
        goal = "renew the library card"
        record = bm.open_mission(goal, "https://library.example.com/")
        obs = {**posting(), "url": "https://library.example.com/"}
        stopped = browser_loop._gate(None, None, obs, record, goal, [], [], skill=browser_loop.GENERAL)
        self.assertEqual(stopped["state"], bm.REFUSED)
        self.assertEqual(stopped["boundary"]["kind"], "SPENDING")


if __name__ == "__main__":
    unittest.main()
