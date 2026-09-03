"""Ten job applications, ready to send — and she does not send them.

"Apply to 10 jobs for me" is one sentence containing about eight hours of
real work and one irreversible act at the end of it. Run through the
planner it came back honestly and uselessly: research the openings, a GAP
saying nothing here submits an application, and a MANUAL step reading
"review the openings and submit each one yourself". Correct on every
count, and it left him with ten browser tabs.

This does the eight hours. The last step stays his, on purpose: a
submitted application is a real message to a real employer under his name
and there is no undo.
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import applications, compose, intercom, journal, policy, tasks, workspace

POSTING = (
    "About the role\nWe are looking for a Senior Backend Engineer to own our "
    "media pipeline. Responsibilities include batch video workflows and the "
    "guardrails that stop bad output shipping. Requirements: strong Python, "
    "experience with ffmpeg, experience with automated quality gates. "
    "Benefits: remote. Apply through this page.\n" + "detail. " * 80)


class ApplicationCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        self.ws = d / "ws"
        self.ws.mkdir()
        (self.ws / "resume.md").write_text("- built a pipeline\n- built an OS\n")
        env = mock.patch.dict(os.environ, {"ALETHEIA_WORKSPACE": str(self.ws),
                                           "ALETHEIA_PRIVATE_STATE": str(d)})
        env.start(); self.addCleanup(env.stop)
        (d / "tasks").mkdir()
        for target, attr, value in ((journal, "JOURNAL_PATH", d / "j.jsonl"),
                                    (policy, "HALT_PATH", d / "halt.json"),
                                    (tasks, "TASKS_DIR", d / "tasks")):
            p = mock.patch.object(target, attr, value)
            p.start(); self.addCleanup(p.stop)

    def finder(self, n=3, extra=()):
        def find(query, limit=9):
            return ([{"url": f"https://jobs.example.com/{i}",
                      "title": f"Senior Backend Engineer — Foundry {i}"}
                     for i in range(n)] + list(extra))
        return find

    def reader(self, body=POSTING, failed=()):
        def read(sources):
            out = []
            for s in sources:
                text = "a short blog post" if "blog" in s["url"] else body
                out.append({"url": s["url"], "title": s["title"], "extract": text})
            return out, list(failed)
        return read

    def writer(self, text="Dear hiring manager, I built the thing."):
        return lambda system, prompt, **kw: text


class ItDoesTheEightHours(ApplicationCase):
    def test_each_posting_becomes_a_packet(self):
        out = applications.prepare("senior backend engineer", count=2,
                                   finder=self.finder(), reader=self.reader(),
                                   writer=self.writer())
        self.assertEqual(len(out["prepared"]), 2)
        for packet in out["prepared"]:
            folder = self.ws / packet["folder"]
            self.assertTrue((folder / "posting.md").is_file())
            self.assertTrue((folder / "cover-letter.md").is_file())
            self.assertTrue((folder / "checklist.md").is_file())

    def test_the_posting_is_kept_as_she_actually_read_it(self):
        out = applications.prepare("senior backend engineer", count=1,
                                   finder=self.finder(), reader=self.reader(),
                                   writer=self.writer())
        posting = (self.ws / out["prepared"][0]["folder"] / "posting.md").read_text()
        self.assertIn("guardrails that stop bad output shipping", posting)
        self.assertIn("https://jobs.example.com/0", posting)

    def test_the_letter_is_written_against_the_posting_and_the_resume(self):
        seen = {}

        def writer(system, prompt, **kw):
            seen["prompt"] = prompt
            return "a letter"
        applications.prepare("senior backend engineer", count=1,
                             finder=self.finder(), reader=self.reader(),
                             writer=writer)
        self.assertIn("built a pipeline", seen["prompt"])
        self.assertIn("media pipeline", seen["prompt"])

    def test_one_task_per_application_so_follow_up_is_answerable(self):
        applications.prepare("senior backend engineer", count=3,
                             finder=self.finder(), reader=self.reader(),
                             writer=self.writer())
        filed = [t for t in tasks.all_tasks() if t["id"].startswith("apply-")]
        self.assertEqual(len(filed), 3)
        self.assertTrue(all("https://" in t["description"] for t in filed))

    def test_two_postings_are_never_one_packet(self):
        """Found by the first end-to-end run: "Foundry 1" and "Foundry 2"
        slugged to the same folder, so the second OVERWROTE the first and
        its task creation raised into a swallow. Two applications, one
        folder, one task, no error."""
        out = applications.prepare("senior backend engineer", count=3,
                                   finder=self.finder(), reader=self.reader(),
                                   writer=self.writer())
        folders = {p["folder"] for p in out["prepared"]}
        task_ids = {p["task"] for p in out["prepared"]}
        self.assertEqual(len(folders), 3)
        self.assertEqual(len(task_ids), 3)


class ItSubmitsNothing(ApplicationCase):
    def test_the_result_says_so(self):
        out = applications.prepare("engineer", count=1, finder=self.finder(),
                                   reader=self.reader(), writer=self.writer())
        self.assertEqual(out["submitted"], 0)
        self.assertIn("Nothing was submitted", out["note"])
        self.assertIn("did not submit", applications.spoken(out))

    def test_every_checklist_ends_with_the_submit_being_his(self):
        out = applications.prepare("engineer", count=1, finder=self.finder(),
                                   reader=self.reader(), writer=self.writer())
        checklist = (self.ws / out["prepared"][0]["folder"]
                     / "checklist.md").read_text()
        self.assertIn("[ ] Submit it.", checklist)
        self.assertIn("does not submit applications", checklist)
        self.assertIn("no undo", checklist)

    def test_the_module_reaches_no_submitting_capability(self):
        """Four gates already refuse this; a fifth is that it never asks."""
        source = (Path(__file__).parent.parent / "aletheia" / "applications.py"
                  ).read_text(encoding="utf-8")
        for reach in ("errand", "interact", "computer", "browse.read_page(",
                      "email_draft", "send"):
            self.assertNotIn(reach, source.split('"""', 2)[2], reach)

    def test_the_grammar_tells_the_planner_not_to_add_a_submit_step(self):
        note = intercom.KIND_NOTES["apply_prepare"]
        self.assertIn("SUBMITS NOTHING", note)
        self.assertIn("Do not add a step that tries to submit", note)


class ItNeverWritesAboutAJobItDidNotREAD(ApplicationCase):
    def test_a_page_that_is_not_a_posting_is_dropped_and_declared(self):
        out = applications.prepare(
            "senior backend engineer", count=5,
            finder=self.finder(n=1, extra=[{"url": "https://blog.example.com/x",
                                            "title": "How we hire"}]),
            reader=self.reader(), writer=self.writer())
        self.assertEqual(len(out["prepared"]), 1)
        self.assertEqual(len(out["skipped"]), 1)
        self.assertIn("blog", out["skipped"][0]["url"])

    def test_nothing_readable_writes_nothing_at_all(self):
        with self.assertRaises(applications.ApplicationError) as caught:
            applications.prepare("engineer", count=2, finder=self.finder(),
                                 reader=self.reader(body="too short"),
                                 writer=self.writer())
        self.assertIn("none of them read like an actual job posting",
                      str(caught.exception))
        self.assertFalse((self.ws / applications.FOLDER).exists())

    def test_no_search_results_is_an_honest_refusal(self):
        with self.assertRaises(applications.ApplicationError):
            applications.prepare("engineer", finder=lambda q, limit=9: [],
                                 reader=self.reader(), writer=self.writer())

    def test_no_browser_means_no_applications_rather_than_blurb_letters(self):
        from aletheia import browse
        with mock.patch.object(browse, "available",
                               return_value=(False, "playwright is not installed")):
            with self.assertRaises(applications.ApplicationError) as caught:
                applications.prepare("engineer")
        said = str(caught.exception)
        self.assertIn("playwright", said)
        self.assertIn("never opened", said)

    def test_a_letter_that_could_not_be_written_says_so_in_the_folder(self):
        def dead(*a, **k):
            raise RuntimeError("no model")
        out = applications.prepare("senior backend engineer", count=1,
                                   finder=self.finder(), reader=self.reader(),
                                   writer=dead)
        packet = out["prepared"][0]
        self.assertTrue(packet["problem"])
        checklist = (self.ws / packet["folder"] / "checklist.md").read_text()
        self.assertIn("NOT WRITTEN", checklist)
        self.assertIn("Write the cover letter yourself", checklist)

    def test_the_letter_brief_fits_what_compose_accepts(self):
        """The first run wrote NO letters at all: the brief was 500
        characters and compose's cap was 400, so every single one failed
        with a ValueError nobody would have connected to the cap."""
        self.assertLessEqual(len(applications.LETTER), compose.MAX_WHAT_CHARS)


class ItStaysInsideTheUsualBoundaries(ApplicationCase):
    def test_a_halt_stops_it_before_it_searches(self):
        policy.halt("stopped", via="test")
        touched = []
        with self.assertRaises(Exception):
            applications.prepare("engineer",
                                 finder=lambda q, limit=9: touched.append(1) or [],
                                 reader=self.reader(), writer=self.writer())
        self.assertEqual(touched, [])

    def test_it_writes_only_through_the_workspace(self):
        source = (Path(__file__).parent.parent / "aletheia" / "applications.py"
                  ).read_text(encoding="utf-8")
        body = source.split('"""', 2)[2]
        self.assertIn("workspace.write(", body)
        for raw in ("open(", "write_text("):
            self.assertNotIn(raw, body, raw)

    def test_ten_is_the_ceiling(self):
        out = applications.prepare("senior backend engineer", count=99,
                                   finder=self.finder(n=30),
                                   reader=self.reader(), writer=self.writer())
        self.assertLessEqual(len(out["prepared"]), applications.MAX_APPLICATIONS)

    def test_the_kind_is_local_and_routine_and_validates(self):
        self.assertIn("apply_prepare", intercom.LOCAL_KINDS)
        self.assertIn("apply_prepare", intercom.ROUTINE_KINDS)
        self.assertEqual(intercom.validate_kind_args(
            {"kind": "apply_prepare", "role": "engineer", "count": 3}, {}), [])


if __name__ == "__main__":
    unittest.main()
