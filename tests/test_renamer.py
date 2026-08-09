import os
import unittest
from datetime import datetime

from context import TempFolderTest

import renamer
from core import FileForgeError, execute, iter_files


def swap_a_and_b(match):
    """Callable replacement, used to build a genuine a <-> b rename batch."""
    return "b" if match.group(0) == "a" else "a"


class Renaming(TempFolderTest):
    def run_plan(self, **kwargs):
        plan = renamer.plan_rename(iter_files(self.root), **kwargs)
        execute(plan, root=self.root, command="rename", dry_run=False, write_log=False)
        return self.tree()

    def test_numbering_pattern(self):
        for name in ("b.txt", "a.txt", "c.txt"):
            self.make(name)
        self.assertEqual(
            self.run_plan(pattern="{n:03d}_{name}{ext}"),
            {"001_a.txt", "002_b.txt", "003_c.txt"},
        )

    def test_start_and_step(self):
        self.make("a.txt")
        self.make("b.txt")
        self.assertEqual(
            self.run_plan(pattern="{n}{ext}", start=10, step=5), {"10.txt", "15.txt"}
        )

    def test_regex_substitution(self):
        self.make("my holiday  photo.jpg")
        self.assertEqual(self.run_plan(regex=r"\s+", replace="_"), {"my_holiday_photo.jpg"})

    def test_regex_and_pattern_compose(self):
        self.make("draft report.pdf")
        self.assertEqual(
            self.run_plan(regex=r"\s+", replace="-", pattern="{n:02d}-{name}{ext}"),
            {"01-draft-report.pdf"},
        )

    def test_case_mode(self):
        self.make("SHOUTING.TXT")
        self.assertEqual(self.run_plan(case="lower"), {"shouting.TXT"})

    def test_date_placeholder(self):
        path = self.make("note.txt")
        stamp = datetime(2022, 1, 9, 8, 30).timestamp()
        os.utime(path, (stamp, stamp))
        self.assertEqual(
            self.run_plan(pattern="{date}_{name}{ext}", date_format="%Y%m%d"),
            {"20220109_note.txt"},
        )

    def test_unchanged_names_are_not_planned(self):
        self.make("a.txt")
        self.assertEqual(renamer.plan_rename(iter_files(self.root), pattern="{name}{ext}"), [])

    def test_sort_by_size_controls_numbering(self):
        self.make("big.txt", "x" * 100)
        self.make("small.txt", "x")
        self.assertEqual(
            self.run_plan(pattern="{n}-{name}{ext}", sort="size"),
            {"1-small.txt", "2-big.txt"},
        )

    def test_collision_with_an_untouched_file_gets_a_suffix(self):
        self.make("a.txt", "moved")
        self.make("taken.txt", "original")
        self.assertEqual(
            self.run_plan(regex="^a$", replace="taken"), {"taken.txt", "taken (1).txt"}
        )
        self.assertEqual((self.root / "taken.txt").read_text(encoding="utf-8"), "original")

    def test_swapping_two_names_works(self):
        self.make("a.txt", "AAA")
        self.make("b.txt", "BBB")
        plan = renamer.plan_rename(iter_files(self.root), regex="^(a|b)$", replace=swap_a_and_b)
        execute(plan, root=self.root, command="rename", dry_run=False, write_log=False)
        self.assertEqual(self.tree(), {"a.txt", "b.txt"})
        self.assertEqual((self.root / "a.txt").read_text(encoding="utf-8"), "BBB")
        self.assertEqual((self.root / "b.txt").read_text(encoding="utf-8"), "AAA")

    def test_shifting_numbers_does_not_lose_files(self):
        for i in (1, 2, 3):
            self.make(f"{i}.txt", str(i))
        plan = renamer.plan_rename(iter_files(self.root), pattern="{n}{ext}", start=2)
        execute(plan, root=self.root, command="rename", dry_run=False, write_log=False)
        self.assertEqual(self.tree(), {"2.txt", "3.txt", "4.txt"})
        self.assertEqual((self.root / "2.txt").read_text(encoding="utf-8"), "1")
        self.assertEqual((self.root / "4.txt").read_text(encoding="utf-8"), "3")

    def test_dry_run_plan_does_not_touch_anything(self):
        self.make("a.txt")
        plan = renamer.plan_rename(iter_files(self.root), pattern="{n}{ext}")
        execute(plan, root=self.root, command="rename", dry_run=True, write_log=False)
        self.assertEqual(self.tree(), {"a.txt"})

    def test_rejects_bad_input(self):
        self.make("a.txt")
        files = iter_files(self.root)
        with self.assertRaises(FileForgeError):
            renamer.plan_rename(files)  # no operation requested
        with self.assertRaises(FileForgeError):
            renamer.plan_rename(files, pattern="{nope}{ext}")
        with self.assertRaises(FileForgeError):
            renamer.plan_rename(files, regex="([", replace="x")
        with self.assertRaises(FileForgeError):
            renamer.plan_rename(files, pattern="../{name}{ext}")  # path escape
        with self.assertRaises(FileForgeError):
            renamer.plan_rename(files, regex=".*", replace="")  # empty name


if __name__ == "__main__":
    unittest.main()
