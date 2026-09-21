"""The QR code on his PC has to actually scan, and looking at one tells you
nothing.

`interface/qr.js` exists so that getting Thea onto a phone is a camera
pointed at a screen rather than a tailnet hostname and a forty-character
token typed on glass. A picture that is nearly a QR code looks exactly like
a QR code and decodes to nothing — which would be the worst kind of failure
here, because it fails at the one moment he is trusting it.

So it is checked module by module against a real, independent encoder
(`segno`), for every version it can produce and every mask, run in the
browser that will actually run it. Both dependencies are optional; their
absence skips, it never fails the suite.

One known divergence, and it is segno's: `write_padding_bits` adds a whole
zero byte when the bit stream already ends on a codeword boundary (it writes
`8 - length % 8` without the outer modulo), which in byte mode is always. A
decoder stops at the terminator so both symbols read the same, but the
matrices differ, so the test corrects segno's padding to the spec's before
comparing. Mask CHOICE is not compared: segno scores the symbol before the
format bits are written and this scores it after, both legal, and every mask
is compared explicitly anyway.
"""
import unittest
from pathlib import Path

QR = Path(__file__).resolve().parent.parent / "interface" / "qr.js"

#: The exact byte-mode capacity of each version at error correction M — the
#: inputs where nothing is padded, so every block, every alignment pattern
#: and (from version 7) the version information is exercised.
CAPACITY = {1: 14, 2: 26, 3: 42, 4: 62, 5: 84, 6: 106, 7: 122, 8: 152,
            9: 180, 10: 213, 11: 251, 12: 287, 13: 331, 14: 362, 15: 412}

REAL = [
    "https://laptop-i09f9sc8.tail094da3.ts.net/interface/thea.html",
    "https://laptop-i09f9sc8.tail094da3.ts.net/interface/thea.html?token=tok-79bca43462",
    "https://laptop-i09f9sc8.tail094da3.ts.net/interface/thea.html?token=" + "k" * 64,
]


def chromium():
    for path in Path("/opt/pw-browsers").glob("chromium-*/chrome-linux/chrome"):
        return str(path)
    return None


class TheQRCodeScansCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import segno  # noqa: F401
            from playwright.sync_api import sync_playwright  # noqa: F401
        except ImportError as exc:
            raise unittest.SkipTest(f"optional dependency missing: {exc.name}")
        cls.cases = [("A" * n, mask) for n in CAPACITY.values() for mask in range(8)]
        cls.cases += [(text, mask) for text in REAL for mask in range(8)]
        cls.mine = cls._in_a_browser(cls.cases)

    @classmethod
    def _in_a_browser(cls, cases):
        """What the page will really produce, produced by a real browser."""
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            kwargs = {"args": ["--no-sandbox"]}
            exe = chromium()
            if exe:
                kwargs["executable_path"] = exe
            try:
                browser = pw.chromium.launch(**kwargs)
            except Exception as exc:
                raise unittest.SkipTest(f"no chromium: {type(exc).__name__}")
            page = browser.new_page()
            page.goto("about:blank")
            page.add_script_tag(content=QR.read_text(encoding="utf-8"))
            out = page.evaluate(
                "(cases) => cases.map(([t, m]) => "
                "window.TheaQR.matrix(t, m).map(r => r.join('')))",
                [[t, m] for t, m in cases])
            browser.close()
        return out

    @staticmethod
    def _reference(text, mask):
        import segno
        from segno import encoder
        spec_padding = (lambda buff, version, length:
                        buff.extend([0] * ((8 - (length % 8)) % 8)))
        was = encoder.write_padding_bits
        encoder.write_padding_bits = spec_padding
        try:
            code = segno.make(text, error="m", mode="byte", mask=mask,
                              boost_error=False, micro=False)
        finally:
            encoder.write_padding_bits = was
        return ["".join("1" if v else "0" for v in row) for row in code.matrix]

    def test_every_module_matches_a_real_encoder(self):
        wrong = []
        for (text, mask), mine in zip(self.cases, self.mine):
            if self._reference(text, mask) != mine:
                wrong.append((len(text), mask))
        self.assertEqual(wrong, [],
                         f"{len(wrong)} of {len(self.cases)} symbols differ: {wrong[:6]}")

    def test_the_link_he_will_actually_scan_is_one_of_them(self):
        self.assertIn((REAL[1], 0), self.cases)

    def test_it_chooses_a_mask_on_its_own_and_that_symbol_is_valid_too(self):
        """The page calls `matrix(text)` with no mask. Whatever its penalty
        scoring picks must be one of the eight symbols already proved
        module-for-module above."""
        free = self._in_a_browser([(REAL[1], None)])[0]
        allowed = [self._reference(REAL[1], mask) for mask in range(8)]
        self.assertIn(free, allowed)

    def test_it_refuses_rather_than_drawing_something_unreadable(self):
        """Past version 15 it has no tables, and a symbol drawn from tables
        it does not have would look fine and scan as nothing."""
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            kwargs = {"args": ["--no-sandbox"]}
            exe = chromium()
            if exe:
                kwargs["executable_path"] = exe
            browser = pw.chromium.launch(**kwargs)
            page = browser.new_page()
            page.goto("about:blank")
            page.add_script_tag(content=QR.read_text(encoding="utf-8"))
            threw = page.evaluate(
                "() => { try { window.TheaQR.matrix('x'.repeat(600)); return ''; }"
                " catch (e) { return e.message; } }")
            browser.close()
        self.assertIn("too long", threw)


if __name__ == "__main__":
    unittest.main()
