"""The registries are read out loud and shown on his screen, so their text must be text.

config/capabilities.json carried "â€”" in eleven places - an em dash saved as UTF-8,
read back as Windows-1252 and saved again - and "what can you do" printed it beside
the Core and the browser. Nothing complained, because it is still valid JSON.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
#: A UTF-8 lead byte read as Windows-1252 (Â, Ã, â) followed by a continuation byte read
#: the same way. Ordinary prose never puts these side by side.
DOUBLE_ENCODED = re.compile("[ÂÃâ][\u0080-¿ŒœŠšŸŽ"
                            "žƒˆ˜–—‘-„†-•…‰"
                            "‹›€™]")


class TheTextIsText(unittest.TestCase):
    def test_no_registry_page_or_module_carries_double_encoded_text(self):
        found = []
        for pattern in ("config/*.json", "plans/*.json", "interface/*", "aletheia/*.py", "README.md", "docs/*.md"):
            for path in sorted(ROOT.glob(pattern)):
                if not path.is_file():
                    continue
                try:
                    text = path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    continue
                for n, line in enumerate(text.splitlines(), 1):
                    if DOUBLE_ENCODED.search(line):
                        found.append(f"{path.relative_to(ROOT)}:{n}")
        self.assertEqual(found, [], "double-encoded text (fix with s.encode('cp1252').decode('utf-8'))")

    def test_the_pattern_catches_the_real_case_and_spares_real_words(self):
        self.assertTrue(DOUBLE_ENCODED.search("the Core â€” the API"))
        self.assertTrue(DOUBLE_ENCODED.search("playbook Â§104"))
        for fine in ("café", "naïve résumé", "Señor — §104", "â la carte"):
            self.assertIsNone(DOUBLE_ENCODED.search(fine), fine)


if __name__ == "__main__":
    unittest.main()
