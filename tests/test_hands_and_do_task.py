"""Hands on the desktop, a program for the request with no verb — and the
first day this code ran on the operator's PC (2026-09-02).

Everything in here was found by running it for real rather than by reading
it: the intercom's new kinds crashed on a name that did not exist, the
agenda marked every honest answer "failed", the workspace was the
repository itself, the script brief contradicted its own caller, one search
engine served a captcha and another served results for a different
question. The tests below hold the fixes, and the two new capabilities the
operator authorized in his own words:

  (a) computer.act — open, focus, type, press; committing controls refused
      back to the hash-bound approval, never skipped;
  (b) do_task — an unmatched ask becomes a sandboxed program.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import (agenda, computer, intercom, journal, mission,
                      notifications, planner, policy, reasoner, research,
                      script, workspace)
from aletheia.fleet import REPO_ROOT

FLEET = {"repos": {}}


class Isolated(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        self.d = d
        env = mock.patch.dict(os.environ, {
            "ALETHEIA_PRIVATE_STATE": str(d / "private"),
            "ALETHEIA_MACHINE_KEY": str(d / "machine.key"),
            "ALETHEIA_WORKSPACE": str(d / "workspace")})
        env.start(); self.addCleanup(env.stop)
        for target, attr, value in (
                (journal, "JOURNAL_PATH", d / "journal.jsonl"),
                (policy, "APPROVALS_DIR", d / "approvals"),
                (policy, "HALT_PATH", d / "halt.json"),
                (mission, "MISSION_PATH", d / "mission.json"),
                (notifications, "NOTICES_DIR", d / "notices")):
            p = mock.patch.object(target, attr, value)
            p.start(); self.addCleanup(p.stop)


class FakeDesktop:
    """A desktop that records what was asked and answers with labels."""

    def __init__(self, live_names=None, on_perform=None):
        self.performed = []
        self.live_names = live_names or {}
        self.on_perform = on_perform

    def describe_control(self, step):
        key = json.dumps(step["control"], sort_keys=True)
        return {"name": self.live_names.get(key, step["control"].get("title", ""))}

    def perform(self, step):
        self.performed.append(step["action"])
        if self.on_perform:
            self.on_perform(step)
        return {"action": step["action"], "verified": True}


WIN = {"title_re": ".*Notepad.*"}


def plan(*steps):
    return list(steps)


class HandsRefuseWhatCommits(Isolated):
    """The line the operator drew: Send, Delete, Pay, Purchase, Confirm,
    Submit, Format, Uninstall, Empty Trash bounce to the approval."""

    def test_every_word_on_his_list_is_a_committing_label(self):
        for word in ("Send", "Delete", "Pay", "Purchase", "Confirm", "Submit",
                     "Format", "Uninstall", "Empty Trash", "Empty the Recycle Bin",
                     "Place order", "Check out", "Buy now", "Sign in"):
            with self.subTest(word=word):
                self.assertTrue(computer.committing_label(word), word)
        for word in ("Save", "Open", "Bold", "Cancel", "Find", "Zoom in"):
            with self.subTest(word=word):
                self.assertIsNone(computer.committing_label(word), word)

    def test_a_send_in_the_selector_refuses_the_plan_before_anything_runs(self):
        desk = FakeDesktop()
        steps = plan({"action": "focus_window", "window": WIN},
                     {"action": "invoke", "window": WIN, "control": {"title": "Send"}})
        with self.assertRaises(computer.CommittingControl) as caught:
            computer.act(steps, backend=desk)
        self.assertEqual(desk.performed, [], "refused before the first step")
        self.assertIn("python -m aletheia.computer request", str(caught.exception),
                      "the refusal names the approval path")

    def test_refused_never_means_skipped(self):
        """A plan that ran with the Send removed would report success for a
        thing not done. Nothing before the forbidden step runs either."""
        desk = FakeDesktop()
        steps = plan({"action": "set_text", "window": WIN,
                      "control": {"control_type": "Edit"}, "text": "hello"},
                     {"action": "invoke", "window": WIN, "control": {"best_match": "Delete"}},
                     {"action": "focus_window", "window": WIN})
        with self.assertRaises(computer.CommittingControl):
            computer.act(steps, backend=desk)
        self.assertEqual(desk.performed, [])

    def test_the_live_label_is_read_before_the_click(self):
        """The selector says OK; the button on screen says Send."""
        key = json.dumps({"title": "OK"}, sort_keys=True)
        desk = FakeDesktop(live_names={key: "Send"})
        steps = plan({"action": "focus_window", "window": WIN},
                     {"action": "invoke", "window": WIN, "control": {"title": "OK"}})
        with self.assertRaises(computer.CommittingControl) as caught:
            computer.act(steps, backend=desk)
        self.assertEqual(desk.performed, ["focus_window"],
                         "stopped at the click, after the honest step")
        self.assertIn("nothing was pressed", str(caught.exception))

    def test_a_control_with_no_readable_label_is_refused(self):
        desk = FakeDesktop()
        steps = plan({"action": "invoke", "window": WIN, "control": {"class_name": "Button"}})
        with self.assertRaises(computer.CommittingControl):
            computer.act(steps, backend=desk)
        self.assertEqual(desk.performed, [])

    def test_a_regex_label_is_read_as_words(self):
        self.assertTrue(computer.committing_label(
            computer._control_label({"title_re": ".*Submit.*"})))

    def test_closing_windows_and_screenshots_keep_the_approval(self):
        for step in ({"action": "close_window", "window": WIN},
                     {"action": "screenshot_window", "window": WIN, "filename": "x.png"}):
            with self.subTest(action=step["action"]):
                with self.assertRaises(computer.ApprovalRequired):
                    computer.act([step], backend=FakeDesktop())
        self.assertNotIn("close_window", computer.ACT_ACTIONS)
        self.assertNotIn("screenshot_window", computer.ACT_ACTIONS)

    SHELLS = ("cmd.exe", "powershell", r"C:\Windows\System32\cmd.exe",
              "python.exe", "regedit", "format.com")

    def test_a_shell_is_never_opened(self):
        for app in self.SHELLS:
            with self.subTest(app=app):
                with self.assertRaises(ValueError):
                    computer.act([{"action": "open_app", "app": app}], backend=FakeDesktop())

    def test_no_approval_can_authorize_a_shell_either(self):
        """Until 2026-09-03 the guard lived only in act(); execute() — the
        hash-bound approval path — happily started PowerShell, which made the
        script sandbox decoration. Launching an interpreter is code
        execution, a capability nobody has built or granted."""
        for app in self.SHELLS:
            with self.subTest(app=app):
                steps = [{"action": "open_app", "app": app}]
                self.assertTrue(any("separate capability" in p
                                    for p in computer.validate_steps(steps)))
                with self.assertRaises(ValueError):
                    computer.execute(steps, "any-approval", backend=FakeDesktop())


class HandsThatWork(Isolated):
    def test_an_honest_plan_runs_and_is_journaled(self):
        desk = FakeDesktop()
        steps = plan({"action": "open_app", "app": "notepad.exe", "arguments": ["a.txt"]},
                     {"action": "wait_window", "window": WIN},
                     {"action": "set_text", "window": WIN,
                      "control": {"control_type": "Document"}, "text": "hi"},
                     {"action": "invoke", "window": WIN, "control": {"title": "Save"}})
        result = computer.act(steps, backend=desk, requested_by="test")
        self.assertEqual(result["steps_done"], 4)
        self.assertEqual(desk.performed, ["open_app", "wait_window", "set_text", "invoke"])
        subjects = [e["subject"] for e in journal.entries()]
        self.assertIn("computer:act", subjects)
        self.assertIn("computer:invoke", subjects)
        texts = " ".join(e["text"] for e in journal.entries())
        self.assertNotIn('"hi"', texts, "typed text is never journaled")

    def test_halt_is_re_read_between_steps(self):
        def halt_after_first(step):
            policy.halt("stop", via="test")
        desk = FakeDesktop(on_perform=halt_after_first)
        steps = plan({"action": "focus_window", "window": WIN},
                     {"action": "set_text", "window": WIN,
                      "control": {"control_type": "Edit"}, "text": "x"})
        with self.assertRaises(policy.Halted):
            computer.act(steps, backend=desk)
        self.assertEqual(desk.performed, ["focus_window"])

    def test_halted_before_start_does_nothing(self):
        policy.halt("stop", via="test")
        desk = FakeDesktop()
        with self.assertRaises(policy.Halted):
            computer.act([{"action": "focus_window", "window": WIN}], backend=desk)
        self.assertEqual(desk.performed, [])


class TheIntercomKnowsBothKinds(Isolated):
    def test_both_kinds_exist_and_run_on_the_pc(self):
        for kind in ("computer_do", "do_task"):
            self.assertIn(kind, intercom.KIND_ARGS)
            self.assertIn(kind, intercom.LOCAL_KINDS)
            self.assertNotIn(kind, agenda.FORBIDDEN_KINDS, "reachable from an agenda")
            # fail closed: neither is read-only and neither rides a routine grant
            self.assertEqual(intercom.tier(kind), intercom.TIER_WORLD)

    def test_a_committing_plan_is_refused_at_the_grammar_gate(self):
        steps = [{"action": "invoke", "window": WIN, "control": {"title": "Pay"}}]
        problems = intercom.validate_kind_args(
            {"kind": "computer_do", "steps": steps}, FLEET)
        self.assertTrue(problems)
        self.assertIn("Pay", problems[0])
        # and as JSON text, the way a relayed command carries it
        problems = intercom.validate_kind_args(
            {"kind": "computer_do", "steps": json.dumps(steps)}, FLEET)
        self.assertTrue(problems)

    def test_an_honest_plan_passes_the_grammar_gate(self):
        steps = [{"action": "open_app", "app": "notepad.exe"}]
        self.assertEqual(intercom.validate_kind_args(
            {"kind": "computer_do", "steps": steps}, FLEET), [])

    def test_do_task_needs_words(self):
        self.assertTrue(intercom.validate_kind_args({"kind": "do_task", "request": " "}, FLEET))
        self.assertEqual(intercom.validate_kind_args(
            {"kind": "do_task", "request": "count the files"}, FLEET), [])

    def test_the_planner_learns_the_step_shape_from_the_intercom(self):
        brief = planner.grammar_brief()
        self.assertIn("computer_do(steps, [why])", brief)
        self.assertIn("open_app", brief)
        self.assertIn("do_task(request, [label])", brief)

    def test_every_kind_answers_with_a_line_not_an_object(self):
        """The first live agenda failed every step because these kinds
        answered with dicts and referenced a name that did not exist."""
        (self.d / "workspace").mkdir()
        (self.d / "workspace" / "a.md").write_text("x", encoding="utf-8")
        answer = intercom.execute_command({"kind": "file_list"}, FLEET)
        self.assertIsInstance(answer, str)
        self.assertIn("a.md", answer)
        answer = intercom.execute_command(
            {"kind": "file_write", "path": "b.md", "text": "hello"}, FLEET)
        self.assertIsInstance(answer, str)
        self.assertIn("wrote", answer)

    def test_a_missing_tool_is_unavailable_not_an_error(self):
        from aletheia import media
        with mock.patch.object(media, "available", return_value=(False, "no ffmpeg here")):
            with self.assertRaises(intercom.Unavailable):
                intercom.execute_command({"kind": "media_probe", "source": "x.mp4"}, FLEET)

    def test_computer_do_is_routed_to_act_not_execute(self):
        with mock.patch.object(computer, "available", return_value=(True, "ok")), \
             mock.patch.object(computer, "act", return_value={"steps_done": 1, "run_id": "hands-1"}) as act, \
             mock.patch.object(computer, "execute") as execute:
            answer = intercom.execute_command(
                {"kind": "computer_do", "steps": [{"action": "open_app", "app": "notepad.exe"}]},
                FLEET, quote="open notepad")
        self.assertIsInstance(answer, str)
        act.assert_called_once()
        execute.assert_not_called()


class TheAgendaReadsEveryReceipt(Isolated):
    def setUp(self):
        super().setUp()
        mission.start("anything", hours=1, actions=5)

    def go(self, plan_, executor):
        with mock.patch.object(planner, "compile", return_value=plan_), \
             mock.patch.object(agenda, "load_fleet", return_value={}):
            return agenda.run("do it", executor=executor)

    def test_a_string_answer_is_done_not_failed(self):
        plan_ = planner.Plan(request="r", summary="s", intent="plan", steps=[
            planner.PlannedStep(1, planner.EXECUTABLE, "ok",
                                command={"kind": "note", "text": "x"})])
        record = self.go(plan_, lambda c, f: "journaled")
        self.assertEqual(record["ran"][0]["outcome"], "done")
        self.assertEqual(record["ran"][0]["detail"], "journaled")
        self.assertEqual(record["succeeded"], 1)

    def test_an_unavailable_tool_is_said_as_such(self):
        plan_ = planner.Plan(request="r", summary="s", intent="plan", steps=[
            planner.PlannedStep(1, planner.EXECUTABLE, "ok",
                                command={"kind": "media_probe", "source": "x.mp4"})])

        def no_tool(c, f):
            raise intercom.Unavailable("no ffmpeg")
        record = self.go(plan_, no_tool)
        self.assertEqual(record["ran"][0]["outcome"], "unavailable")
        self.assertEqual(record["succeeded"], 0)

    def test_money_is_still_the_line_for_both_new_kinds(self):
        """Neither new kind widens the money rule: the source of agenda.py
        carries no override, and the refusal fires before either runs."""
        source = (Path(__file__).parent.parent / "aletheia" / "agenda.py").read_text(encoding="utf-8")
        for escape in ("allow_money", "force=", "override", "skip_money"):
            self.assertNotIn(escape, source)
        plan_ = planner.Plan(request="r", summary="s", intent="plan",
                             required_capabilities=["purchase.execute"], steps=[
            planner.PlannedStep(1, planner.EXECUTABLE, "ok",
                                command={"kind": "do_task", "request": "buy it"})])
        ran = []
        with self.assertRaises(agenda.AgendaRefused):
            self.go(plan_, lambda c, f: ran.append(c))
        self.assertEqual(ran, [])


REGISTRY_WITH_SCRIPT = {
    "providers": {"aletheia.local": {}},
    "capabilities": [
        {"id": "task.persist", "status": "AVAILABLE", "provider": "aletheia.local"},
        {"id": "task.script", "status": "AVAILABLE", "provider": "aletheia.local",
         "approval_policy": "none", "risk_class": "medium"},
        {"id": "purchase.execute", "status": "EXPERIMENTAL", "provider": "aletheia.local",
         "approval_policy": "operator_always", "risk_class": "high"},
        {"id": "calendar.read", "status": "NEEDS_CONFIGURATION", "provider": "aletheia.local",
         "approval_policy": "none", "risk_class": "read"},
        {"id": "file.rename", "status": "NOT_BUILT", "provider": "aletheia.local",
         "approval_policy": "none", "risk_class": "low"},
    ],
}
REGISTRY_WITHOUT_SCRIPT = {
    "providers": {"aletheia.local": {}},
    "capabilities": [c for c in REGISTRY_WITH_SCRIPT["capabilities"] if c["id"] != "task.script"],
}


def stub(output):
    from aletheia import brain
    return brain.Provider("stub", lambda text, ctx: output)


class UnmatchedAsksBecomeAProgram(Isolated):
    def compile(self, output, registry=REGISTRY_WITH_SCRIPT):
        return planner.compile("rename these files by date", fleet=FLEET,
                               provider=stub(output), registry=registry)

    def test_an_invented_kind_becomes_a_do_task_step(self):
        plan_ = self.compile({"intent": "plan", "summary": "s", "steps": [
            {"kind": "rename_files", "pattern": "date"}]})
        self.assertEqual([s.status for s in plan_.steps],
                         [planner.REFUSED, planner.EXECUTABLE])
        self.assertEqual(plan_.executable[0].command,
                         {"kind": "do_task", "request": "rename these files by date"})
        self.assertIn("sandboxed", plan_.executable[0].detail)

    def test_a_gap_on_a_computation_becomes_a_do_task_step_and_the_gap_stays(self):
        plan_ = self.compile({"intent": "plan", "summary": "s", "steps": [
            {"gap": "file.rename", "why": "nothing renames files"}]})
        self.assertEqual([s.status for s in plan_.steps],
                         [planner.GAP, planner.EXECUTABLE])
        self.assertEqual(plan_.steps[0].capability, "file.rename", "the ticket stays")

    def test_a_built_but_unconfigured_capability_gets_its_setup_not_a_program(self):
        # 2026-09-02: "what's on my calendar tomorrow" compiled to a sandboxed
        # program because calendar.read was NEEDS_CONFIGURATION; a sandbox
        # with no network reads no calendar. The verb exists; it needs him.
        plan_ = self.compile({"intent": "plan", "summary": "s", "steps": [
            {"gap": "calendar.read", "why": "no calendar"}]})
        self.assertEqual([s.status for s in plan_.steps], [planner.GAP])
        self.assertEqual(plan_.executable, [])

    def test_authority_shaped_gaps_are_never_turned_into_a_program(self):
        plan_ = self.compile({"intent": "plan", "summary": "s", "steps": [
            {"gap": "purchase.execute", "why": "cannot buy"}]})
        self.assertEqual(plan_.executable, [])

    def test_a_plan_that_already_does_something_is_not_padded(self):
        plan_ = self.compile({"intent": "plan", "summary": "s", "steps": [
            {"kind": "note", "text": "x"}, {"gap": "calendar.read", "why": "no"}]})
        self.assertEqual([s.command["kind"] for s in plan_.executable], ["note"])

    def test_manual_only_and_clarify_stay_his(self):
        plan_ = self.compile({"intent": "plan", "summary": "s", "steps": [
            {"manual": "sign it yourself"}]})
        self.assertEqual(plan_.executable, [])
        plan_ = self.compile({"intent": "clarify", "summary": "which files?"})
        self.assertEqual(plan_.executable, [])

    def test_only_when_the_registry_really_has_the_capability(self):
        plan_ = self.compile({"intent": "plan", "summary": "s", "steps": [
            {"kind": "rename_files", "pattern": "date"}]}, registry=REGISTRY_WITHOUT_SCRIPT)
        self.assertEqual(plan_.executable, [])

    def test_the_live_registry_names_the_script_capability(self):
        from aletheia import capabilities
        entry = capabilities.get(planner.SCRIPT_CAPABILITY)
        self.assertEqual(entry["module"], "aletheia.script")


class TheWorkspaceIsNotTheRepository(Isolated):
    def test_the_repository_is_refused_as_a_root(self):
        with mock.patch.dict(os.environ, {"ALETHEIA_WORKSPACE": str(REPO_ROOT)}):
            with self.assertRaises(workspace.WorkspaceError):
                workspace.root()

    def test_a_directory_inside_the_repository_is_refused(self):
        with mock.patch.dict(os.environ, {"ALETHEIA_WORKSPACE": str(Path(REPO_ROOT) / "cache" / "ws-probe")}):
            with self.assertRaises(workspace.WorkspaceError):
                workspace.root()
        probe = Path(REPO_ROOT) / "cache" / "ws-probe"
        if probe.is_dir():
            probe.rmdir()

    def test_any_git_checkout_is_refused(self):
        other = self.d / "someproject"
        (other / ".git").mkdir(parents=True)
        with mock.patch.dict(os.environ, {"ALETHEIA_WORKSPACE": str(other)}):
            with self.assertRaises(workspace.WorkspaceError):
                workspace.root()

    def test_the_default_is_her_own_directory_under_documents(self):
        self.assertEqual(workspace.DEFAULT_ROOT, Path.home() / "Documents" / "Aletheia")


CHALLENGE = {"url": "https://html.duckduckgo.com/html/?q=x", "title": "DuckDuckGo",
             "text": "Please complete the following challenge.",
             "links": [{"text": "DuckDuckGo", "href": "https://html.duckduckgo.com/html/"}]}
WIKI_SEARCH = {"url": "https://en.wikipedia.org/w/index.php?search=x", "title": "Search results",
               "text": "Search results " + "result text " * 60,
               "links": [{"text": "Main", "href": "https://en.wikipedia.org/wiki/Main_Page"},
                         {"text": "Help", "href": "https://en.wikipedia.org/wiki/Help:Search"},
                         {"text": "Willis Tower", "href": "https://en.wikipedia.org/wiki/Willis_Tower"},
                         {"text": "", "href": "https://en.wikipedia.org/wiki/Aon_Center_(Chicago)"},
                         {"text": "dup", "href": "https://en.wikipedia.org/wiki/Willis_Tower"},
                         {"text": "anchor", "href": "https://en.wikipedia.org/wiki/Willis_Tower#History"}]}


class ResearchSurvivesACaptcha(Isolated):
    def test_a_challenge_page_costs_the_engine_not_the_question(self):
        asked = []

        def reader(url, *a, **k):
            asked.append(url)
            if "duckduckgo" in url:
                return CHALLENGE
            if "wikipedia" in url:
                return WIKI_SEARCH
            return {"url": url, "title": "", "text": "", "links": []}
        found = research.find_sources("tallest building", reader=reader)
        self.assertEqual([s["url"] for s in found],
                         ["https://en.wikipedia.org/wiki/Willis_Tower",
                          "https://en.wikipedia.org/wiki/Aon_Center_(Chicago)"])
        self.assertTrue(all(s.get("library") for s in found))
        self.assertTrue(any("duckduckgo" in u for u in asked))
        self.assertEqual(research.SEARCH_ENGINES[0][0], "duckduckgo")

    def test_an_unrendered_results_page_yields_nothing(self):
        shell = {"url": "https://www.bing.com/search?q=x", "title": "x - Search",
                 "text": "Skip to content", "links": [
                     {"text": "", "href": "https://www.bing.com/ck/a?u=a1aHR0cHM6Ly9leGFtcGxlLm9yZy9h"}]}
        self.assertEqual(research._results("bing", shell, 5), [])

    def test_bing_redirects_are_unwrapped(self):
        wrapped = "https://www.bing.com/ck/a?!&&p=abc&u=a1aHR0cHM6Ly9leGFtcGxlLm9yZy9h&ntb=1"
        self.assertEqual(research._unwrap(wrapped), "https://example.org/a")
        self.assertEqual(research._unwrap("https://example.org/plain"), "https://example.org/plain")

    def test_search_engines_are_never_sources(self):
        for host in ("search.brave.com", "www.bing.com", "html.duckduckgo.com"):
            self.assertIn(host, research.SKIP_HOSTS)

    def test_extracts_are_cut_to_fit_the_reasoner(self):
        sources = [{"url": f"https://s{i}.test/", "title": "t", "extract": "x" * 6000}
                   for i in range(5)]
        rows = research._bounded("q", sources)
        size = len(json.dumps({"question": "q", "sources": rows}).encode("utf-8"))
        self.assertLessEqual(size, reasoner.MAX_CONTEXT_BYTES)
        self.assertEqual(len(rows), 5, "every source keeps a share")


class TheScriptBriefSaysOneThing(Isolated):
    def test_the_brief_asks_for_json_once_and_the_text_tail_for_a_program(self):
        self.assertNotIn("Return ONLY the program", script.SYSTEM)
        self.assertIn('"program"', script.SYSTEM_JSON_TAIL)
        self.assertIn("Return ONLY the program", script.SYSTEM_TEXT_TAIL)

    def test_a_fenced_program_is_accepted_as_text_when_json_fails(self):
        def refuse_json(*a, **k):
            raise ValueError("no JSON object in provider output")
        with mock.patch.object(reasoner, "subscription_json", side_effect=refuse_json), \
             mock.patch.object(reasoner, "infer_text",
                               return_value="```python\nprint('hi')\n```") as text:
            program = script.write_program("say hi")
        self.assertEqual(program, "print('hi')")
        self.assertIn("Return ONLY the program", text.call_args[0][0])

    def test_a_custom_thinker_is_not_second_guessed(self):
        def fake(*a, **k):
            raise ValueError("bad shape")
        with mock.patch.object(reasoner, "infer_text") as text:
            with self.assertRaises(ValueError):
                script.write_program("x", think=fake)
        text.assert_not_called()

    def test_the_sandbox_is_unchanged(self):
        """The operator's condition on (b): the box stays exactly as it was."""
        for name in ("socket", "urllib.request", "subprocess", "ctypes", "importlib",
                     "http.client", "requests"):
            self.assertFalse(script._module_allowed(name), name)
        with self.assertRaises(script.ScriptRefused):
            script.check("import subprocess\nsubprocess.run(['x'])")
        with self.assertRaises(script.ScriptRefused):
            script.check("import os\nos.system('x')")
        env = script._environment()
        self.assertNotIn("GITHUB_TOKEN", env)
        self.assertNotIn("ALETHEIA_PRIVATE_STATE", env)


if __name__ == "__main__":
    unittest.main()


class AMissionCoversOneGoal(Isolated):
    """A live mission is not a live mission for everything: fix_projects
    authorizes code.autonomous and nothing else (found 2026-09-02 — the
    agenda checked only that SOME mission was running)."""

    def test_an_agenda_refuses_to_run_under_a_fix_projects_mission(self):
        mission.start("fix_projects", hours=1, actions=3)
        plan_ = planner.Plan(request="r", summary="s", intent="plan", steps=[
            planner.PlannedStep(1, planner.EXECUTABLE, "ok",
                                command={"kind": "note", "text": "x"})])
        ran = []
        with mock.patch.object(planner, "compile", return_value=plan_), \
             mock.patch.object(agenda, "load_fleet", return_value={}):
            with self.assertRaises(agenda.AgendaError) as caught:
                agenda.run("do it", executor=lambda c, f: ran.append(c))
        self.assertEqual(ran, [])
        self.assertIn("fix_projects", str(caught.exception))

    def test_the_code_sweep_refuses_to_run_under_an_anything_mission(self):
        from aletheia import project_loop
        mission.start("anything", hours=1, actions=3)
        result = project_loop.run_mission_slice(request=lambda *a, **k: [])
        self.assertEqual(result["status"], "NO_MISSION")

    def test_covers_names_the_capability_not_the_kind(self):
        mission.start("anything", hours=1, actions=3)
        self.assertIsNotNone(mission.covers("agenda.execute"))
        self.assertIsNone(mission.covers("code.autonomous"))
        self.assertIsNone(mission.covers("purchase.execute"))
