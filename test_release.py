"""Release contents and HTTP boundary checks without private fixtures."""
import unittest
from pathlib import Path
from build_release import FILES


class ReleaseTests(unittest.TestCase):
    def test_allowlist_contains_only_source_assets_and_docs(self):
        root = Path(__file__).resolve().parent
        self.assertEqual(len(FILES), len(set(FILES)))
        for name in FILES:
            self.assertTrue((root / name).is_file(), name)
            self.assertNotIn('/', name)
            self.assertNotIn('snapshot', name)
            self.assertNotIn('manifest', name)
            self.assertNotIn('native', name)
            self.assertNotIn('full', name)
        self.assertIn('atlas.py', FILES)
        self.assertIn('viewer.css', FILES)
        self.assertIn('LICENSE', FILES)

    def test_public_docs_have_no_developer_archive_paths(self):
        root = Path(__file__).resolve().parent
        for name in ('README.txt', 'BETA_NOTES.md', 'SUPPORT.md', 'FORMAT.md'):
            data = (root / name).read_text(encoding='utf-8')
            self.assertTrue(data.isascii(), name)
            for private in ('D:\\hermes', 'C:\\Users\\Ant', 'pure-full', 'staging-full', 'validation-snapshot'):
                self.assertNotIn(private, data, name)


if __name__ == '__main__':
    unittest.main()
