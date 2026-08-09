"""End-to-end tests through the argparse layer, the way a user runs it."""

import io
import unittest
from contextlib import redirect_stdout

from context import TempFolderTest

import main


class CliTest(TempFolderTest):
    def run_cli(self, *argv) -> tuple[int, str]:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = main.main([str(a) for a in argv])
        return code, buffer.getvalue()

    def sample_folder(self):
        self.make("holiday.jpg", "image-bytes")
        self.make("notes.pdf", "doc")
        self.make("song.mp3", "audio")


class OrganizeFlow(CliTest):
    def test_dry_run_then_apply_then_undo(self):
        self.sample_folder()
        before = self.tree()

        code, out = self.run_cli("organize", self.root)
        self.assertEqual(code, 0)
        self.assertIn("DRY RUN", out)
        self.assertIn("Images/holiday.jpg", out)
        self.assertEqual(self.tree(), before, "dry run must not touch the disk")

        code, out = self.run_cli("organize", self.root, "--apply")
        self.assertEqual(code, 0)
        self.assertEqual(
            self.tree() - self._logs(),
            {"Images/holiday.jpg", "Documents/notes.pdf", "Audio/song.mp3"},
        )

        code, out = self.run_cli("undo", self.root, "--apply")
        self.assertEqual(code, 0)
        self.assertEqual(self.tree() - self._logs(), before)

    def test_dry_run_flag_overrides_apply(self):
        self.sample_folder()
        before = self.tree()
        code, out = self.run_cli("organize", self.root, "--apply", "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("DRY RUN", out)
        self.assertEqual(self.tree(), before)

    def test_filters_reach_the_scanner(self):
        self.sample_folder()
        _code, out = self.run_cli("organize", self.root, "--ext", "jpg")
        self.assertIn("holiday.jpg", out)
        self.assertNotIn("notes.pdf", out)

    def test_undo_list_shows_history(self):
        self.sample_folder()
        self.run_cli("organize", self.root, "--apply")
        code, out = self.run_cli("undo", self.root, "--list")
        self.assertEqual(code, 0)
        self.assertIn("organize", out)

    def test_no_log_skips_history(self):
        self.sample_folder()
        self.run_cli("organize", self.root, "--apply", "--no-log")
        code, out = self.run_cli("undo", self.root)
        self.assertIn("no FileForge history", out)

    def _logs(self):
        return {p for p in self.tree() if p.startswith(".fileforge/")}


class OtherCommands(CliTest):
    def test_rename_dry_run_and_apply(self):
        self.make("second photo.jpg", "b")
        self.make("first photo.jpg", "a")

        code, out = self.run_cli("rename", self.root, "--pattern", "{n:02d}_{name}{ext}",
                                 "--regex", r"\s+", "--replace", "-")
        self.assertEqual(code, 0)
        self.assertIn("01_first-photo.jpg", out)

        self.run_cli("rename", self.root, "--pattern", "{n:02d}{ext}", "--apply", "--no-log")
        self.assertEqual(self.tree(), {"01.jpg", "02.jpg"})

    def test_dedupe_moves_copies_to_trash(self):
        self.make("original.txt", "same content")
        self.make("z-copy.txt", "same content")

        code, out = self.run_cli("dedupe", self.root)
        self.assertEqual(code, 0)
        self.assertIn("2 copies", out)
        self.assertEqual(self.tree(), {"original.txt", "z-copy.txt"})

        self.run_cli("dedupe", self.root, "--apply", "--no-log")
        remaining = {p for p in self.tree() if not p.startswith(".fileforge/")}
        self.assertEqual(remaining, {"original.txt"})
        self.assertTrue(any(p.startswith(".fileforge/trash/") for p in self.tree()))

    def test_report_output(self):
        self.make("a.jpg", "x" * 2048)
        self.make("b.pdf", "x" * 10)
        code, out = self.run_cli("report", self.root)
        self.assertEqual(code, 0)
        self.assertIn("Images", out)
        self.assertIn("2.0 KB", out)

    def test_bad_input_exits_with_an_error(self):
        code, _out = self.run_cli("organize", self.root / "does-not-exist")
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
