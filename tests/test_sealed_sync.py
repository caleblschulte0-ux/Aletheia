"""Encrypted sidecars under exchange/commands/sealed ride the existing Git sync."""
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from aletheia.sync import GitSync


def run(args, cwd):
    return subprocess.run(
        args, cwd=str(cwd), check=True, capture_output=True, text=True
    )


def rmtree(path):
    def clear_readonly(func, target, _exc):
        Path(target).chmod(stat.S_IWRITE)
        func(target)
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=clear_readonly)
    else:
        shutil.rmtree(path, onerror=clear_readonly)


class SealedSyncCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.origin = root / "origin.git"
        self.pc = root / "pc"
        self.relay = root / "relay"

        run(["git", "init", "--bare", "-b", "main", str(self.origin)], root)
        run(["git", "clone", str(self.origin), str(self.pc)], root)
        for key, value in (("user.email", "t@t"), ("user.name", "t")):
            run(["git", "config", key, value], self.pc)
        seed = self.pc / "exchange" / "commands"
        seed.mkdir(parents=True)
        (seed / ".gitkeep").write_text("", encoding="utf-8")
        run(["git", "add", "."], self.pc)
        run(["git", "commit", "-m", "seed"], self.pc)
        run(["git", "push", "origin", "main"], self.pc)

    def test_nested_sealed_sidecar_is_committed_and_pushed(self):
        sealed = self.pc / "exchange" / "commands" / "sealed"
        sealed.mkdir(parents=True)
        sidecar = sealed / "obs-sync.json"
        ciphertext_marker = "ciphertext-only-marker"
        sidecar.write_text(
            '{"version":1,"ciphertext":"' + ciphertext_marker + '"}\n',
            encoding="utf-8",
        )

        syncer = GitSync(repo_root=self.pc, branch="main")
        ok, detail = syncer.commit_push(
            ["exchange/commands"], "core: encrypted observation sidecar"
        )
        self.assertTrue(ok, detail)

        run(["git", "clone", str(self.origin), str(self.relay)], self.pc.parent)
        returned = (
            self.relay / "exchange" / "commands" / "sealed" / "obs-sync.json"
        ).read_text(encoding="utf-8")
        self.assertIn(ciphertext_marker, returned)


if __name__ == "__main__":
    unittest.main()
