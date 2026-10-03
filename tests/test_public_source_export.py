"""Protect the source snapshot boundary and the existing development checkout."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

spec = importlib.util.spec_from_file_location(
    "public_export", Path(__file__).resolve().parents[1] / "scripts/export-public-source.py")
exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exporter)


class PublicSourceExportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.source = self.base / "development"
        self.source.mkdir()
        subprocess.run(["git", "init", "--initial-branch=main", str(self.source)],
                       check=True, capture_output=True)
        for name, text in {
            "LICENSE": "synthetic test license", "main.py": "# synthetic source\n",
            "release.json": '{"version":"0.0.1"}',
            ".gitignore": ".env\nlocal-data/\n", ".env": "synthetic ignored value",
            "AGENTS.md": "private machine instructions",
        }.items():
            (self.source / name).write_text(text, encoding="utf-8")

    def test_snapshot_contains_current_uncommitted_source_without_history_or_private_files(self):
        target = self.base / "candidate"
        report = exporter.export(self.source, target)
        self.assertEqual((target / "main.py").read_bytes(), (self.source / "main.py").read_bytes())
        self.assertFalse((target / ".env").exists())
        self.assertFalse((target / "AGENTS.md").exists())
        self.assertEqual(report["excludedLocalFiles"], ["AGENTS.md"])
        self.assertEqual(subprocess.check_output(["git", "remote"], cwd=target), b"")
        self.assertNotEqual(subprocess.run(["git", "rev-parse", "--verify", "HEAD"],
                                          cwd=target, capture_output=True).returncode, 0)
        self.assertFalse((self.source / ".git/index").exists())

    def test_existing_destination_is_never_overwritten(self):
        target = self.base / "candidate"
        target.mkdir()
        (target / "keep.txt").write_text("keep")
        with self.assertRaises(ValueError):
            exporter.export(self.source, target)
        self.assertEqual((target / "keep.txt").read_text(), "keep")

    def test_rejects_nested_destination_before_writing(self):
        target = self.source / "candidate"
        with self.assertRaises(ValueError):
            exporter.export(self.source, target)
        self.assertFalse(target.exists())

    def test_unreviewed_file_blocks_export_before_writing(self):
        (self.source / "personal-notes.txt").write_text("synthetic private notes")
        target = self.base / "candidate"
        with self.assertRaisesRegex(ValueError, "Unreviewed"):
            exporter.export(self.source, target)
        self.assertFalse(target.exists())

    def test_allowlist_blocks_runtime_data_and_instruction_files(self):
        for path in ("web/media/test.png", "role-library/test/profile.json", "state.db",
                     "docs/AGENTS.md", "tools/unknown.png", "main.py.bak", "../main.py"):
            with self.subTest(path=path):
                self.assertFalse(exporter.allowed(path))
        self.assertTrue(exporter.allowed("tests/test_api.py"))
        self.assertTrue(exporter.allowed("packaging/updater/回滚数恋到上一版本.bat"))
