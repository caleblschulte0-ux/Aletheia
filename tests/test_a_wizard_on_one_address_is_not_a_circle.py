"""A whole application on ONE address is a different page at every step.

Live 2026-10-07: eight applications she had filled stopped as "going in
circles" on the form they were moving through - Greenhouse, Lever, Ashby and
every script-drawn wizard keep one address from the first question to the
last, and each step was counted as another visit to the same page. The same
address asking the same questions again is still a circle.
"""
from __future__ import annotations

import http.server
import threading
import unittest

from aletheia import browser_loop, browser_mission as bm, job_skill
from tests.test_browser_loop_torture import LoopCase, needs_browser

#: Five steps drawn by script on one address, each with its own questions and
#: the SAME Next button (one element, so one selector, at every step).
WIZARD = """<html><head><title>Apply - Systems Engineer</title></head><body>
<h1>Apply for Systems Engineer</h1>
<form id="f" onsubmit="return false">
<div id="steps"></div>
<button type="button" id="next">Next</button>
</form>
<script>
const steps = [
  [["first_name", "First name *"], ["last_name", "Last name *"]],
  [["email", "Email *"]],
  [["phone", "Phone *"]],
  [["city", "City *"]],
  [["why", "Why do you want to work here? *"]],
];
let at = 0;
function draw() {
  const box = document.getElementById('steps');
  box.innerHTML = '';
  for (const [name, label] of steps[at]) {
    const id = 'q_' + name;
    box.insertAdjacentHTML('beforeend',
      '<p><label for="' + id + '">' + label + '</label><input id="' + id + '" name="' + name + '" required></p>');
  }
  const next = document.getElementById('next');
  if (at === steps.length - 1) { next.textContent = 'Submit application'; next.type = 'submit'; }
}
document.getElementById('next').addEventListener('click', () => {
  for (const el of document.querySelectorAll('#steps input')) if (!el.value) return;
  if (at < steps.length - 1) { at += 1; draw(); }
  else { document.body.innerHTML = '<h1>Thank you for applying</h1>'; }
});
draw();
</script></body></html>"""


class _Wizard(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        raw = WIZARD.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class TheShapeOfAPage(unittest.TestCase):
    def obs(self, *labels, url="https://jobs.example/apply/1"):
        return {"url": url, "targets": [{"role": "textbox", "label": label} for label in labels]
                + [{"role": "button", "label": "Next"}]}

    def test_the_same_questions_are_the_same_page_and_new_ones_are_not(self):
        one = browser_loop.page_shape(self.obs("First name *", "Last name *"))
        self.assertEqual(one, browser_loop.page_shape(self.obs("Last name *", "first  NAME *")),
                         "order, spacing and case are not a different page")
        self.assertNotEqual(one, browser_loop.page_shape(self.obs("Email *")))

    def test_a_page_asking_nothing_has_no_shape(self):
        self.assertEqual(browser_loop.page_shape({"url": "x", "targets": [{"role": "link", "label": "Apply"}]}), "")


@needs_browser
class AWizardOnOneAddressIsNotACircle(LoopCase):
    def setUp(self):
        super().setUp()
        self.wizard = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Wizard)
        self.wizard.daemon_threads = True
        threading.Thread(target=self.wizard.serve_forever, daemon=True).start()
        self.addCleanup(self.wizard.server_close)
        self.addCleanup(self.wizard.shutdown)
        self.start = f"http://127.0.0.1:{self.wizard.server_address[1]}/apply/1"

    def test_five_steps_on_one_address_reach_the_final_button(self):
        record = browser_loop.pursue(
            "apply for the systems engineer job", self.start,
            inputs={"why do you want to work here": "I build unattended systems with quality gates.",
                    "city": "Austin"},
            skill=job_skill.SKILL)
        self.assertBoundary(record, bm.AWAITING_APPROVAL, "SUBMIT_APPROVAL")
        self.assertEqual(record["gate"]["button"], "Submit application")


if __name__ == "__main__":
    unittest.main()
