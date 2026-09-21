"""The semantic index: incremental, honest about which engine answered, and
never a way for a secret to reach a prompt.

A fake embedder stands in for Ollama (a bag of words hashed into a small
vector), so these tests pay for no model and hold the aggregation: what is
re-embedded when, which basis a recall carries, what never gets stored.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import semantic_index as si
from aletheia import stateio


class FakeEmbedder:
    model = "fake-embed"
    name = "fake:embed"

    def __init__(self, *, up: bool = True):
        self.calls: list[list[str]] = []
        self.up = up
        self.why = "" if up else "the fake is down"

    def available(self):
        return self.up

    def busy(self):
        return False

    def embed(self, texts, timeout_s=None):
        self.calls.append(list(texts))
        out = []
        for text in texts:
            vec = [0.0] * 32
            for word in si.tokens(text):
                vec[int(hashlib.md5(word.encode()).hexdigest(), 16) % 32] += 1.0
            out.append(vec)
        return out

    @property
    def embedded(self):
        return sum(len(c) for c in self.calls)


def table_from(docs: dict):
    """A source table over a dict {source: {ref: text}} the test can mutate."""
    def make(source):
        def gen():
            for ref, text in sorted(docs.get(source, {}).items()):
                digest = hashlib.sha256(text.encode()).hexdigest()
                yield si.Doc(source, ref, digest,
                             lambda text=text, ref=ref: [si.Chunk(ref, piece, locator=ref)
                                                         for piece in si.split_text(text)])
        return gen
    return {source: make(source) for source in ("journal", "fixes", "code")}


class IndexCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="si-test-"))
        self.db = self.tmp / "index.sqlite3"
        self.docs = {
            "journal": {"journal/2026-09-14": "alert apply: the Submit button would not take a click, "
                                              "a CAPTCHA challenge was in front of it"},
            "fixes": {"fixes/abc": "Commit abc: a torn journal line no longer blinds every reader"},
            "code": {"aletheia/x.py": "def settle_interrupted(run_id):\n    'settle a submit that died'\n"},
        }
        self.embedder = FakeEmbedder()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def build(self, **kw):
        return si.build(path=self.db, source_table=table_from(self.docs), embedder=self.embedder,
                        polite=False, **kw)


class IncrementalBuilds(IndexCase):
    def test_a_second_run_with_nothing_changed_embeds_nothing(self):
        first = self.build()
        self.assertEqual(first["chunks"], 3)
        self.assertEqual(first["embedded"], 3)
        second = self.build()
        self.assertEqual(second["embedded"], 0)
        self.assertEqual(sum(s["changed"] for s in second["sources"].values()), 0)
        self.assertEqual(self.embedder.embedded, 3)

    def test_only_the_changed_document_is_rechunked_and_reembedded(self):
        self.build()
        self.docs["code"]["aletheia/x.py"] += "\ndef another():\n    return 'a new function'\n"
        report = self.build()
        self.assertEqual(report["sources"]["code"]["changed"], 1)
        self.assertEqual(report["sources"]["journal"]["changed"], 0)
        self.assertEqual(report["embedded"], 1)

    def test_a_deleted_document_leaves_the_index_and_its_vectors_go(self):
        self.build()
        del self.docs["fixes"]["fixes/abc"]
        report = self.build()
        self.assertEqual(report["sources"]["fixes"]["removed"], 1)
        conn = sqlite3.connect(self.db)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM chunks WHERE source='fixes'").fetchone()[0], 0)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM vectors").fetchone()[0], 2)
        conn.close()

    def test_identical_text_is_embedded_once(self):
        self.docs["journal"]["journal/2026-09-15"] = self.docs["journal"]["journal/2026-09-14"]
        # same text, different ref: the title differs, so make the chunk title equal too
        table = table_from(self.docs)
        original = table["journal"]

        def same_title():
            for doc in original():
                yield si.Doc(doc.source, doc.ref, doc.digest,
                             lambda d=doc: [si.Chunk("journal", c.text) for c in d.load()])
        table["journal"] = same_title
        report = si.build(path=self.db, source_table=table, embedder=self.embedder, polite=False)
        self.assertEqual(report["chunks"], 4)
        self.assertEqual(self.embedder.embedded, 3)

    def test_the_budget_stops_embedding_and_the_next_run_carries_on(self):
        now = [0.0]
        slow = FakeEmbedder()
        real_embed = slow.embed

        def embed(texts, timeout_s=None):
            now[0] += 100.0                    # every batch costs a hundred seconds
            return real_embed(texts)
        slow.embed = embed
        self.embedder = slow
        with mock.patch.object(si, "EMBED_BATCH", 1), mock.patch.object(si.time, "monotonic", lambda: now[0]):
            partial = self.build(budget_s=150)
        self.assertEqual(partial["embedded"], 2)
        self.embedder = FakeEmbedder()
        rest = self.build()
        self.assertEqual(partial["embedded"] + rest["embedded"], 3)

    def test_an_unavailable_embedder_still_builds_the_lexical_index(self):
        self.embedder = FakeEmbedder(up=False)
        report = self.build()
        self.assertEqual(report["chunks"], 3)
        self.assertEqual(report["embedded"], 0)
        self.assertIn("fake is down", report["embed_skipped"])

    def test_a_busy_ollama_defers_embedding_when_polite(self):
        self.embedder.busy = lambda: True
        report = si.build(path=self.db, source_table=table_from(self.docs), embedder=self.embedder,
                          polite=True)
        self.assertEqual(report["embedded"], 0)
        self.assertIn("thinking", report["embed_skipped"])


class RecallSaysHowItKnows(IndexCase):
    def test_history_found_by_search_is_found_in_history(self):
        self.build()
        out = si.recall("why would the submit button not take a click", path=self.db,
                        embedder=self.embedder, probes={})
        self.assertEqual(out["basis"], si.FOUND)
        self.assertEqual(out["answered_by"], "semantic+lexical")
        self.assertEqual(out["snippets"][0]["source"], "journal")
        self.assertTrue(all(s["basis"] == si.FOUND for s in out["snippets"]))
        self.assertIn("not fact", out["note"])

    def test_a_ledger_row_is_known(self):
        self.build()
        probe = lambda words, raw: [{"store": "tasks", "id": "t1", "fact": {"description": "call the plumber"}}] \
            if "plumber" in words else []
        out = si.recall("did I ask you to call the plumber", path=self.db, embedder=self.embedder,
                        probes={"tasks": probe})
        self.assertEqual(out["basis"], si.KNOWN)
        self.assertEqual(out["facts"][0]["basis"], si.KNOWN)

    def test_nothing_anywhere_is_a_guess_and_says_so(self):
        self.build()
        out = si.recall("zebra helicopter", path=self.db, embedder=FakeEmbedder(up=False), probes={})
        self.assertEqual(out["basis"], si.GUESS)
        self.assertIn("GUESS", out["note"])

    def test_without_the_model_it_is_lexical_and_says_why(self):
        self.build()
        out = si.recall("CAPTCHA challenge", path=self.db, embedder=FakeEmbedder(up=False), probes={})
        self.assertEqual(out["answered_by"], "lexical")
        self.assertIn("fake is down", out["lexical_because"])
        self.assertEqual(out["basis"], si.FOUND)

    def test_a_never_built_index_says_so_rather_than_nothing_matched(self):
        out = si.recall("anything", path=self.tmp / "missing.sqlite3", probes={})
        self.assertIn("not built", out["index"])
        self.assertEqual(out["basis"], si.GUESS)

    def test_sources_narrow_the_search(self):
        self.build()
        out = si.recall("journal reader torn line CAPTCHA", sources=["fixes"], path=self.db,
                        embedder=self.embedder, probes={})
        self.assertTrue(out["snippets"])
        self.assertEqual({s["source"] for s in out["snippets"]}, {"fixes"})

    def test_the_pure_python_bm25_answers_when_fts5_is_missing(self):
        self.build()
        with mock.patch.object(si, "has_fts", lambda conn: False):
            out = si.recall("CAPTCHA challenge", path=self.db, embedder=FakeEmbedder(up=False), probes={})
        self.assertEqual(out["snippets"][0]["source"], "journal")

    def test_a_probe_that_breaks_is_named_not_silent(self):
        def broken(words, raw):
            raise OSError("disk")
        facts, unreadable = si.ledger("anything at all", probes={"tasks": broken})
        self.assertEqual((facts, unreadable), ([], ["tasks"]))


class SecretsNeverReachTheIndex(IndexCase):
    def test_secret_shaped_text_is_scrubbed_before_it_is_stored(self):
        self.docs["journal"]["journal/2026-09-16"] = ("note: log into the bank, password: hunter2xyz "
                                                     "and card 4111 1111 1111 1111")
        self.build()
        conn = sqlite3.connect(self.db)
        stored = " ".join(r[0] for r in conn.execute("SELECT text FROM chunks"))
        fts = " ".join(r[0] for r in conn.execute("SELECT text FROM chunks_fts"))
        conn.close()
        for blob in (stored, fts):
            self.assertNotIn("hunter2xyz", blob)
            self.assertNotIn("4111 1111", blob)

    def test_the_secret_store_is_off_the_allowlist_and_refused_outright(self):
        self.assertFalse({"secrets", "access", "authority", "profile", "training"} & set(si.SOURCES))
        with self.assertRaises(PermissionError):
            si._refuse_private(stateio.private_dir("secrets"))
        with self.assertRaises(PermissionError):
            list(si._json_dir_docs("x", stateio.private_dir("secrets"), lambda r: None))

    def test_a_mission_never_carries_its_inputs_or_its_codes(self):
        from aletheia import browser_mission
        record = browser_mission.open_mission("make a library account", "https://lib.example/signup",
                                              inputs={"password": "Sup3rSecretPw!", "card": "LIB-99887766"})
        browser_mission.post_event(record["id"], "verification_code", "918273")
        browser_mission.stop_at(browser_mission.load(record["id"]), browser_mission.NEEDS_YOU,
                                {"kind": "EMAIL_VERIFICATION", "say": "a code went to his email"})
        docs = [d for d in si.mission_docs() if d.ref.endswith(record["id"])]
        text = " ".join(c.text for c in docs[0].load())
        self.assertIn("EMAIL_VERIFICATION", text)
        for secret in ("Sup3rSecretPw", "LIB-99887766", "918273"):
            self.assertNotIn(secret, text)

    def test_an_application_travels_without_the_answers_he_gave(self):
        from aletheia import apply_run
        folder = apply_run.staged_dir()
        folder.mkdir(parents=True, exist_ok=True)
        stateio.write_json_atomic(folder / "apply-secret01.json", {
            "id": "apply-secret01", "state": "FAILED", "company": "Acme", "job_title": "Analyst",
            "failure": "the Submit button would not take a click",
            "filled": [{"label": "Salary expectation", "value": "UNIQUEANSWER-123"}],
            "answers_given": {"q": "ANOTHERANSWER-456"}})
        docs = [d for d in si.application_docs() if d.ref.endswith("apply-secret01")]
        text = " ".join(c.text for c in docs[0].load())
        self.assertIn("would not take a click", text)
        self.assertNotIn("UNIQUEANSWER", text)
        self.assertNotIn("ANOTHERANSWER", text)


class Chunking(unittest.TestCase):
    def test_python_chunks_name_their_file_and_first_line(self):
        source = "'''doc'''\nimport os\n\n\ndef first():\n    return 1\n\n\nclass Second:\n    x = 1\n"
        chunks = si.chunk_python("aletheia/m.py", source)
        where = {c.title: c.locator for c in chunks}
        self.assertEqual(where["aletheia/m.py def first"], "aletheia/m.py:5")
        self.assertEqual(where["aletheia/m.py class Second"], "aletheia/m.py:9")

    def test_long_text_splits_and_nothing_is_lost(self):
        text = "\n\n".join(f"paragraph {n} " + "word " * 60 for n in range(30))
        pieces = si.split_text(text)
        self.assertGreater(len(pieces), 1)
        self.assertTrue(all(len(p) <= si.CHUNK_CHARS + si.MIN_CHUNK_CHARS for p in pieces))
        self.assertEqual(sum(p.count("paragraph") for p in pieces), 30)

    def test_significant_words_drop_filler(self):
        self.assertEqual(si.significant("why can't you handle the Palantir application?"),
                         ["palantir", "application"])


class TheBackgroundKickIsPolite(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="si-kick-")
        self.env = mock.patch.dict(os.environ, {"ALETHEIA_SEMANTIC_INDEX": self.tmp}, clear=False)
        self.env.start()
        os.environ.pop("ALETHEIA_REHEARSAL", None)
        os.environ.pop("ALETHEIA_SEMANTIC_INDEX_OFF", None)

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_due_starts_one_build_and_records_it(self):
        started = []
        out = si.kick_if_due(spawner=lambda budget: started.append(budget) or 4242, now=10_000.0)
        self.assertTrue(out["started"])
        self.assertEqual(started, [si.DEFAULT_BUDGET_S])
        self.assertEqual(si.read_stamp()["pid"], 4242)

    def test_a_running_build_is_not_started_twice(self):
        si._write_stamp({"pid": 4242, "started_epoch": 10_000.0})
        with mock.patch("aletheia.proc.pid_alive", lambda pid, needle="": True):
            out = si.kick_if_due(spawner=lambda b: self.fail("spawned twice"), now=10_100.0)
        self.assertEqual(out["why"], "a build is already running")

    def test_not_due_until_the_interval_passes(self):
        si._write_stamp({"pid": 1, "started_epoch": 9_000.0, "finished_epoch": 9_500.0})
        out = si.kick_if_due(spawner=lambda b: self.fail("not due"), now=9_600.0, interval_s=900)
        self.assertEqual(out["why"], "not due")

    def test_a_rehearsal_never_starts_one(self):
        with mock.patch.dict(os.environ, {"ALETHEIA_REHEARSAL": "1"}):
            out = si.kick_if_due(spawner=lambda b: self.fail("rehearsal"), now=10_000.0)
        self.assertFalse(out["started"])

    def test_the_spawned_build_is_windowless_and_below_normal(self):
        seen = {}

        class FakePopen:
            pid = 99

            def __init__(self, args, **kwargs):
                seen.update(kwargs, args=args)
        with mock.patch.object(si.subprocess, "Popen", FakePopen), mock.patch.object(si, "IS_WINDOWS", True):
            self.assertEqual(si._spawn_build(60), 99)
        self.assertIn("aletheia.semantic_index", seen["args"])
        self.assertTrue(seen["creationflags"] & si.BELOW_NORMAL_PRIORITY_CLASS)


if __name__ == "__main__":
    unittest.main()
