"""A subsystem asks for a CLASS of reasoning, not a company.

His continuity brief (docs/CONTINUITY_BRIEF.md, Part I.1): the gateway's
policies are right (routine = local first; standard = frontier first with a
local fallback; critical = frontier required), and some systems still reached
Claude, Codex, ChatGPT or her own model directly. Each remaining direct call is
listed here WITH ITS CLASS AND WHY it does not go through
`aletheia.reasoning_gateway`, and docs/REASONING_CLASSES.md is the table a person
reads. A new direct call anywhere else fails this test until it is either routed
through the gateway or added here with a reason - classified, not blindly
replaced.

The walk is over the AST, so a call hidden as a default argument
(`think = think or reasoner.subscription_json`) counts as much as a call.
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "aletheia"
DOC = ROOT / "docs" / "REASONING_CLASSES.md"

#: The modules that ARE the reasoning layer: the gateway and the rungs it drives.
REASONING_LAYER = {"reasoning_gateway", "reasoner", "local_model_pool", "local_brain",
                   "browser_reasoner"}

#: module -> attributes that ask a specific worker to think (or launch its CLI).
WATCHED = {
    "reasoner": {"subscription_json", "_subscription_json_with_provider", "subscription_text",
                 "infer_json", "infer_text", "local_text", "codex_json", "work_json",
                 "work_json_with_provider", "_run_cli", "cli_path", "codex_path",
                 "CliReasoner", "infer_or_fallback"},
    "local_model_pool": {"run_json", "auto_json"},
    "local_brain": {"infer_json"},
    "browser_reasoner": {"infer_json"},
}

#: (module, enclosing function, attribute) -> (class, why it is direct).
ALLOWED = {
    # -- the job hunt's deliberate chain (CLAUDE.md "The job hunt has its own chain")
    ("campaign", "_job_hunt_thinker.think", "work_json"):
        ("standard", "job hunt chain Claude -> Codex -> local with 6 GB free; his 2026-09-13 ruling"),
    ("campaign", "_any_model_answers", "work_json"):
        ("standard", "job hunt chain; the validator confines every rung to the form's own options"),
    ("campaign", "_any_model_writes", "subscription_text"):
        ("standard", "essays walk every writer (his 2026-09-12 ruling); gateway has no text route"),
    ("campaign", "_any_model_writes", "codex_json"):
        ("standard", "essays: Codex rung of the same deliberate chain"),
    ("campaign", "_any_model_writes", "local_text"):
        ("standard", "essays: her own model last in the same deliberate chain"),
    ("job_fit", "judge", "work_json_with_provider"):
        ("standard", "job hunt chain with a stricter local prompt; local-only verdicts wait for his OK"),
    ("pursuit", "_gateway_think.think", "codex_json"):
        ("standard", "the pursuit is the job hunt: gateway first, then the same Codex rung while Claude rests, "
                     "then her own model only with memory for it"),
    # -- conversation discloses which mouth spoke
    ("converse", "_from_my_own_model", "local_text"):
        ("standard", "conversation's disclosed local rung: the answer says it is her own model's"),
    ("converse", "answer", "subscription_text"):
        ("standard", "conversation is prose; Claude then ChatGPT, then the disclosed local rung"),
    # -- prose writers the gateway (JSON-only) cannot express yet
    ("compose", "compose", "subscription_text"):
        ("standard", "document prose; no gateway text route and no own-model disclosure on a saved file yet"),
    ("webtask", "run", "subscription_text"):
        ("standard", "the older selector loop (superseded by browser_loop for start-page asks)"),
    # -- the script sandbox is frozen by operator rule; migrate in its own reviewed change
    ("script", "write_program", "subscription_json"):
        ("standard", "authors sandboxed programs; the script sandbox is not changed in this wave"),
    ("script", "write_program", "infer_text"):
        ("standard", "same, the text retry when a model answers with the program itself"),
    # -- frontier-required: a tool only the frontier CLIs have
    ("web_search_jobs", "_claude_search", "cli_path"):
        ("critical", "web search is a tool of the Claude CLI; her own model cannot search"),
    ("web_search_jobs", "_claude_ready", "cli_path"):
        ("critical", "same: is the searching CLI there"),
    ("web_search_jobs", "_codex_search", "codex_path"):
        ("critical", "web search through the Codex CLI"),
    ("eyes", "_ask_claude_about", "cli_path"):
        ("critical", "reads a screenshot through the Claude CLI; no gateway vision route yet"),
    # -- probes of a specific worker, not reasoning
    ("setup", "_claude_cli", "cli_path"):
        ("critical", "setup audit: is the Claude CLI itself signed in and answering"),
    ("setup", "_claude_cli", "infer_text"):
        ("critical", "setup audit: a live one-word prompt to the Claude CLI"),
    ("current_state", "thinking", "cli_path"):
        ("critical", "is the Claude CLI even installed: the brains line said 'thinking with the "
                     "big models' from the rest markers alone with no CLI on the PC"),
    ("current_state", "thinking", "codex_path"):
        ("critical", "same for Codex; a presence check, no prompt"),
    # -- adapters that already route through the gateway
    ("planner", "compile", "infer_or_fallback"):
        ("standard", "runs the gateway-backed frontier provider, deterministic brain on refusal; "
                     "the local rung is local_planner through reasoning_gateway.local_json"),
    # -- code work: owned by the local-repair wave (claude/continuity-local-repair)
    ("code_worker", "*", "subscription_json"):
        ("critical", "code proposal and review; the local-repair wave owns code_worker.py"),
    ("self_diagnosis", "*", "subscription_json"):
        ("critical", "patch proposals escalate to frontier; local-repair wave owns self_diagnosis.py"),
    ("self_diagnosis", "*", "run_json"):
        ("routine", "local investigation rung; local-repair wave owns self_diagnosis.py"),
    ("project_merge", "*", "subscription_json"):
        ("critical", "a DIFFERENT model reviews before an autonomous merge; local-repair wave"),
}

#: Files another worker owns this wave: allowed wholesale by the "*" rows above.
OWNED_ELSEWHERE = {"code_worker", "self_diagnosis", "project_merge"}


def _aliases(tree: ast.Module) -> dict[str, str]:
    """local name -> watched module, for `from aletheia import reasoner as _r`."""
    names = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "aletheia":
            for alias in node.names:
                if alias.name in WATCHED:
                    names[alias.asname or alias.name] = alias.name
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("aletheia.") and alias.name.split(".")[1] in WATCHED:
                    names[alias.asname or alias.name] = alias.name.split(".")[1]
    return names


def direct_calls() -> set[tuple[str, str, str]]:
    """Every (module, enclosing function, attribute) that reaches a worker directly."""
    found: set[tuple[str, str, str]] = set()
    for path in sorted(PKG.glob("*.py")):
        module = path.stem
        if module in REASONING_LAYER:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        aliases = _aliases(tree)

        def visit(node, scope: list[str]):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                scope = scope + [node.name]
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                target = aliases.get(node.value.id)
                if target and node.attr in WATCHED[target]:
                    found.add((module, ".".join(scope) or "<module>", node.attr))
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("aletheia."):
                target = node.module.split(".")[1]
                for alias in node.names:
                    if target in WATCHED and alias.name in WATCHED[target]:
                        found.add((module, ".".join(scope) or "<module>", alias.name))
            for child in ast.iter_child_nodes(node):
                visit(child, scope)
        visit(tree, [])
    return found


def _allowed(row: tuple[str, str, str]) -> bool:
    module, scope, attr = row
    return row in ALLOWED or (module, "*", attr) in ALLOWED or (
        module in OWNED_ELSEWHERE)


class EveryDirectCallIsClassifiedOrGone(unittest.TestCase):
    def test_no_new_direct_call_outside_the_allowlist(self):
        stray = sorted(row for row in direct_calls() if not _allowed(row))
        self.assertEqual(stray, [], "route these through reasoning_gateway (reason_json / thinker / "
                                    "frontier_json / local_json) or add them to ALLOWED with a class "
                                    "and a reason, and to docs/REASONING_CLASSES.md")

    def test_the_allowlist_has_no_stale_rows(self):
        live = direct_calls()
        stale = sorted(key for key in ALLOWED
                       if key[1] != "*" and key not in live)
        self.assertEqual(stale, [], "an allowed direct call no longer exists: remove its row")

    def test_every_class_is_a_gateway_class(self):
        from aletheia import work_states
        for key, (klass, why) in ALLOWED.items():
            with self.subTest(key=key):
                self.assertTrue(set(klass.split("/")) <= work_states.REASONING_CLASSES)
                self.assertTrue(why.strip())

    def test_the_doc_names_every_allowed_module(self):
        doc = DOC.read_text(encoding="utf-8")
        for module in {key[0] for key in ALLOWED}:
            with self.subTest(module=module):
                self.assertIn(f"`{module}", doc)

    def test_the_migrated_callers_stay_migrated(self):
        live = direct_calls()
        for module in ("agent_session", "browser_route", "browser_loop", "research"):
            with self.subTest(module=module):
                self.assertEqual(sorted(r for r in live if r[0] == module), [])


if __name__ == "__main__":
    unittest.main()
