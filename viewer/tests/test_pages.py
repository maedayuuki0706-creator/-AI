import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("pages", ROOT / "build_pages.py")
PAGES = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PAGES)


class PagesTest(unittest.TestCase):
    def test_preview_is_unindexed_and_dormant(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)
            PAGES.build(target, "https://preview.example.com", True, "NOT_PUBLIC")
            self.assertEqual((target / "robots.txt").read_text(), "User-agent: *\nDisallow: /\n")
            for file in target.rglob("*.html"):
                text = file.read_text()
                self.assertIn('content="noindex, nofollow"', text)
                self.assertNotIn("NOT_PUBLIC", text)
                self.assertIn("https://preview.example.com/", text)
            self.assertIn('"enabled": false', (target / "assets/site-config.js").read_text())

    def test_analytics_needs_id_and_production(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                PAGES.build(Path(folder), "https://preview.example.com", analytics=True)
            with self.assertRaises(ValueError):
                PAGES.build(Path(folder), "https://preview.example.com", preview=True, analytics=True, measurement_id="G-123456")

    def test_generated_pages_are_reproducible(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)
            PAGES.build(target, PAGES.PRODUCTION)
            for route in PAGES.PAGES:
                path = Path(route.strip("/")) / "index.html"
                self.assertEqual((ROOT / path).read_text(), (target / path).read_text(), str(path))


if __name__ == "__main__":
    unittest.main()
