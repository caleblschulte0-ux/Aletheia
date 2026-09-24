"""A scheduling link in an employer's email is booked in his window, on his word.

His words, 2026-09-24: "If someone sends us a Calendly link, she can put 1
to 2.30 p.m. Central on there. And as long as she puts it on the calendar,
the Open Range Interactive Calendar, I'm fine with that. She shouldn't send
anything to outside correspondence yet."

The page here is a fixture in the shape Calendly renders: day buttons that
say "Times available", time buttons carrying data-start-time, a Next
button, a name-and-email form, a Schedule button, a confirmation. The walk
is deterministic; the one outward press waits for the grant.
"""
from __future__ import annotations

import datetime as dt
import http.server
import threading
import unittest
from unittest import mock
from zoneinfo import ZoneInfo

from aletheia import calendly, interviews

CENTRAL = ZoneInfo("America/Chicago")
WINDOW = {"start": "13:00", "end": "14:30", "timezone": "America/Chicago"}


def _next_weekdays(n: int, *, start: dt.date) -> list[dt.date]:
    out, day = [], start
    while len(out) < n:
        day += dt.timedelta(days=1)
        if day.weekday() < 5:
            out.append(day)
    return out


def _stamp(day: dt.date, hour: int, minute: int) -> str:
    return dt.datetime(day.year, day.month, day.day, hour, minute, tzinfo=CENTRAL).isoformat()


def fixture_page(days: list[dt.date], times: list[tuple[int, int]]) -> str:
    """A booking page: pick a day, pick a time, Next, name + email, Schedule."""
    day_buttons = "".join(
        f'<button aria-label="{d.strftime("%A, %B %d")} - Times available" data-day="{d.isoformat()}" '
        f'onclick="showTimes(\'{d.isoformat()}\')">{d.day}</button>' for d in days)
    slots = {d.isoformat(): [_stamp(d, h, m) for h, m in times] for d in days}
    import json
    return f"""<!doctype html><html><body>
<h1>Acme Interview - 30 min</h1>
<div role="grid" id="days">{day_buttons}</div>
<div id="times"></div>
<div id="next" style="display:none"><button aria-label="Next" onclick="showForm()">Next</button></div>
<form id="form" style="display:none" onsubmit="return schedule(event)">
  <label>Name <input name="full_name"></label>
  <label>Email <input name="email" type="email"></label>
  <button type="submit">Schedule Event</button>
</form>
<div id="done" style="display:none"></div>
<script>
const SLOTS = {json.dumps(slots)};
let picked = "";
function showTimes(day) {{
  const box = document.getElementById("times"); box.innerHTML = "";
  for (const s of SLOTS[day]) {{
    const b = document.createElement("button"); b.setAttribute("data-start-time", s);
    b.textContent = s.slice(11, 16); b.onclick = () => {{ picked = s; document.getElementById("next").style.display = ""; }};
    box.appendChild(b);
  }}
}}
function showForm() {{ document.getElementById("form").style.display = ""; }}
function schedule(e) {{
  e.preventDefault();
  const name = document.querySelector('input[name="full_name"]').value;
  const email = document.querySelector('input[name="email"]').value;
  document.getElementById("form").style.display = "none";
  document.getElementById("done").style.display = "";
  document.getElementById("done").textContent = name && email && picked
    ? "You are scheduled with Acme. " + picked + " - a calendar invitation has been sent to " + email
    : "Something went wrong. Name is required.";
  return false;
}}
</script></body></html>"""


def _serve(html: str):
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _browser():
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return None
    return sync_playwright


class TheLinkIsFoundAndTheSlotIsChosen(unittest.TestCase):
    def test_scheduling_links_are_found_by_host_and_nothing_else_is(self):
        text = ("Thanks Caleb! Grab a time here: https://calendly.com/acme-hr/30min?month=2026-10. "
                "Our careers page is https://jobs.acme.example/careers and my cal is https://cal.com/pat/intro.")
        self.assertEqual(calendly.find_scheduling_links(text),
                         ["https://calendly.com/acme-hr/30min?month=2026-10", "https://cal.com/pat/intro"])
        self.assertEqual(calendly.find_scheduling_links("no links here"), [])

    def test_the_first_open_weekday_time_in_his_window_that_he_is_free_for(self):
        now = dt.datetime(2026, 9, 24, 15, 0, tzinfo=dt.timezone.utc)
        days = _next_weekdays(3, start=dt.date(2026, 9, 24))
        slots = [{"start": _stamp(d, h, m), "end": _stamp(d, h, m + 30 if m < 30 else m), "day": d.isoformat()}
                 for d in days for h, m in ((10, 0), (13, 30), (15, 0))]
        chosen = calendly.choose(slots, window=WINDOW, busy=lambda s, e: False, now=now)
        self.assertEqual(chosen["start"], _stamp(days[0], 13, 30))
        # busy at the first one: the next day's window slot, never 10:00 or 15:00
        busy = lambda s, e: s == _stamp(days[0], 13, 30)  # noqa: E731
        self.assertEqual(calendly.choose(slots, window=WINDOW, busy=busy, now=now)["start"], _stamp(days[1], 13, 30))
        # nothing in the window means nothing: she does not book outside his words
        outside = [s for s in slots if "13:30" not in s["start"]]
        self.assertIsNone(calendly.choose(outside, window=WINDOW, busy=lambda s, e: False, now=now))

    def test_a_weekend_and_a_slot_too_soon_are_not_his_window(self):
        sat = dt.date(2026, 9, 26)
        now = dt.datetime(2026, 9, 25, 18, 0, tzinfo=dt.timezone.utc)   # 13:00 Central
        self.assertFalse(calendly.fits(_stamp(sat, 13, 30), window=WINDOW, now=now))
        self.assertFalse(calendly.fits(_stamp(dt.date(2026, 9, 25), 13, 30), window=WINDOW, now=now),
                         "half an hour from now is not notice")
        self.assertTrue(calendly.fits(_stamp(dt.date(2026, 9, 28), 13, 0), window=WINDOW, now=now))


class ThePageIsWalkedAndThePressWaitsForHisWord(unittest.TestCase):
    def setUp(self):
        self.pw = _browser()
        if self.pw is None:
            raise unittest.SkipTest("playwright is not installed")
        today = dt.datetime.now(CENTRAL).date()
        self.days = _next_weekdays(3, start=today)
        self.server = _serve(fixture_page(self.days, [(10, 0), (13, 30), (15, 0)]))
        self.addCleanup(self.server.shutdown)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/acme/30min"
        self.now = dt.datetime.now(dt.timezone.utc)

    def _page(self):
        p = self.pw().start()
        self.addCleanup(p.stop)
        browser = p.chromium.launch()
        self.addCleanup(browser.close)
        return browser.new_page()

    def test_without_the_grant_she_fills_the_form_and_stops_before_the_press(self):
        page = self._page()
        out = calendly.book(self.url, name="Caleb Schulte", email="openrangeinteractive@gmail.com", window=WINDOW,
                            busy=lambda s, e: False, now=self.now, page=page, spender=lambda cap, aid: None)
        self.assertEqual(out["state"], "needs_grant", out)
        self.assertEqual(out["chosen"]["start"], _stamp(self.days[0], 13, 30))
        self.assertEqual(page.input_value('input[name="full_name"]'), "Caleb Schulte")
        self.assertNotIn("You are scheduled", page.inner_text("body"))

    def test_with_the_grant_the_slot_in_his_window_is_booked_and_confirmed(self):
        page = self._page()
        spent = []

        def spender(cap, aid):
            spent.append(cap)
            return "standing-interviews-test"
        out = calendly.book(self.url, name="Caleb Schulte", email="openrangeinteractive@gmail.com", window=WINDOW,
                            busy=lambda s, e: False, now=self.now, page=page, spender=spender)
        self.assertEqual(out["state"], "booked", out)
        self.assertEqual(spent, ["interview.book"])
        self.assertEqual(out["chosen"]["start"], _stamp(self.days[0], 13, 30))
        self.assertIn("You are scheduled", page.inner_text("body"))

    def test_when_nothing_is_in_his_window_nothing_is_pressed(self):
        server = _serve(fixture_page(self.days, [(9, 0), (16, 0)]))
        self.addCleanup(server.shutdown)
        page = self._page()
        out = calendly.book(f"http://127.0.0.1:{server.server_address[1]}/acme/30min", name="Caleb Schulte",
                            email="x@example.com", window=WINDOW, busy=lambda s, e: False, now=self.now, page=page,
                            spender=lambda cap, aid: "grant")
        self.assertEqual(out["state"], "no_slot")
        self.assertEqual(out["looked_at"], 6)


class TheInterviewPathBooksInsteadOfDrafting(unittest.TestCase):
    def setUp(self):
        import os, tempfile
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": tmp.name})
        env.start(); self.addCleanup(env.stop)
        self.notices = []
        self.marks = []

    def _consider(self, booker, calendar_writer=None):
        with mock.patch.object(interviews, "status", return_value={"on": True, "window": WINDOW, "quote": "", "command": ""}), \
                mock.patch("aletheia.mail._config", return_value={"address": "openrangeinteractive@gmail.com"}), \
                mock.patch("aletheia.calendar.create", return_value={"id": "interview-acme-2026-09-28"}):
            return interviews.consider(
                {"id": "ev-1", "attributes": {"sender": "pat@acme.example"}},
                {"id": "apply-1", "company": "Acme"}, subject="Interview - Acme",
                text="Hi Caleb, grab a time: https://calendly.com/acme/30min Thanks, Pat",
                now=dt.datetime(2026, 9, 24, 15, 0, tzinfo=dt.timezone.utc),
                busy=lambda s, e: False, known={"full_name": "Caleb Schulte"},
                marker=lambda *a, **k: self.marks.append((a, k)),
                notify=lambda title, body, **k: self.notices.append((title, body)),
                booker=booker, calendar_writer=calendar_writer or (lambda **k: {"state": "written", "say": "it is on the Open Range Interactive calendar"}))

    def test_a_booked_link_is_said_marked_and_never_drafted(self):
        chosen = {"start": "2026-09-28T13:30:00-05:00", "end": "2026-09-28T14:00:00-05:00"}
        out = self._consider(lambda url, **k: {"state": "booked", "chosen": chosen, "grant": "g"})
        self.assertEqual(out["state"], "booked")
        self.assertEqual(self.marks[0][0][:2], ("apply-1", "interview"))
        title, body = self.notices[0]
        self.assertIn("booked", body)
        self.assertIn("Open Range Interactive calendar", body)
        self.assertNotIn("draft", body.lower())

    def test_without_the_grant_the_sentence_carries_the_one_command(self):
        chosen = {"start": "2026-09-28T13:30:00-05:00", "end": "2026-09-28T14:00:00-05:00"}
        out = self._consider(lambda url, **k: {"state": "needs_grant", "chosen": chosen})
        self.assertEqual(out["state"], "needs_grant")
        self.assertIn("python -m aletheia.interviews on", self.notices[0][1])
        self.assertEqual(self.marks, [])

    def test_no_slot_in_his_window_hands_him_the_link(self):
        out = self._consider(lambda url, **k: {"state": "no_slot", "looked_at": 9})
        self.assertEqual(out["state"], "no_slot")
        self.assertIn("https://calendly.com/acme/30min", self.notices[0][1])


if __name__ == "__main__":
    unittest.main()
