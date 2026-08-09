import json
import os
import unittest
from datetime import datetime
from pathlib import Path

from context import TempFolderTest

import organizer
from config import Config, load_config
from core import execute, iter_files


class Categories(TempFolderTest):
    def test_known_and_unknown_extensions(self):
        config = Config()
        self.assertEqual(config.category_for(Path("a.JPG")), "Images")
        self.assertEqual(config.category_for(Path("a.pdf")), "Documents")
        self.assertEqual(config.category_for(Path("a.py")), "Code")
        self.assertEqual(config.category_for(Path("a.qqq")), "Other")
        self.assertEqual(config.category_for(Path("noext")), "Other")

    def test_config_file_merges_with_defaults(self):
        path = self.root / "rules.json"
        path.write_text(
            json.dumps({"categories": {"Design": ["psd", ".ai"]}, "other_folder": "Misc"}),
            encoding="utf-8",
        )
        config = load_config(path)
        self.assertEqual(config.category_for(Path("a.psd")), "Design")
        self.assertEqual(config.category_for(Path("a.jpg")), "Images")  # default kept
        self.assertEqual(config.category_for(Path("a.qqq")), "Misc")

    def test_config_can_replace_defaults(self):
        path = self.root / "rules.json"
        path.write_text(
            json.dumps({"replace_defaults": True, "categories": {"Pics": [".jpg"]}}),
            encoding="utf-8",
        )
        config = load_config(path)
        self.assertEqual(config.category_for(Path("a.jpg")), "Pics")
        self.assertEqual(config.category_for(Path("a.pdf")), "Other")


class OrganizeByType(TempFolderTest):
    def setUp(self):
        super().setUp()
        self.config = Config()

    def plan(self, **kwargs):
        files = iter_files(self.root, recursive=kwargs.pop("recursive", False))
        return organizer.plan_organize(self.root, files, self.config, **kwargs)

    def test_moves_each_file_into_its_category(self):
        self.make("photo.jpg")
        self.make("notes.pdf")
        self.make("weird.qqq")
        plan = self.plan()
        destinations = {Path(a.dst).relative_to(self.root).as_posix() for a in plan}
        self.assertEqual(
            destinations, {"Images/photo.jpg", "Documents/notes.pdf", "Other/weird.qqq"}
        )

    def test_already_sorted_files_are_left_alone(self):
        self.make("Images/photo.jpg")
        self.assertEqual(self.plan(recursive=True), [])

    def test_name_collisions_get_a_suffix(self):
        self.make("a/photo.jpg", "one")
        self.make("b/photo.jpg", "two")
        plan = self.plan(recursive=True)
        destinations = sorted(Path(a.dst).name for a in plan)
        self.assertEqual(destinations, ["photo (1).jpg", "photo.jpg"])

    def test_plan_survives_execution(self):
        self.make("photo.jpg")
        self.make("song.mp3")
        execute(self.plan(), root=self.root, command="organize", dry_run=False, write_log=False)
        self.assertEqual(self.tree(), {"Images/photo.jpg", "Audio/song.mp3"})


class OrganizeByDate(TempFolderTest):
    def test_date_folders(self):
        path = self.make("photo.jpg")
        stamp = datetime(2023, 5, 17, 12, 0).timestamp()
        os.utime(path, (stamp, stamp))

        files = iter_files(self.root)
        plan = organizer.plan_organize(
            self.root, files, Config(), mode=organizer.BY_DATE, date_format="%Y/%m"
        )
        self.assertEqual(
            Path(plan[0].dst).relative_to(self.root).as_posix(), "2023/05/photo.jpg"
        )

    def test_type_and_date_combined(self):
        path = self.make("photo.jpg")
        stamp = datetime(2023, 5, 17, 12, 0).timestamp()
        os.utime(path, (stamp, stamp))

        plan = organizer.plan_organize(
            self.root,
            iter_files(self.root),
            Config(),
            mode=organizer.BY_TYPE_DATE,
            date_format="%Y-%m",
        )
        self.assertEqual(
            Path(plan[0].dst).relative_to(self.root).as_posix(), "Images/2023-05/photo.jpg"
        )


class Report(TempFolderTest):
    def test_summarize_counts_and_sizes(self):
        self.make("a.jpg", "x" * 100)
        self.make("b.jpg", "x" * 50)
        self.make("c.pdf", "x" * 10)
        summary = organizer.summarize(iter_files(self.root), Config(), top=2)

        self.assertEqual(summary["files"], 3)
        self.assertEqual(summary["bytes"], 160)
        self.assertEqual(summary["categories"][0]["name"], "Images")
        self.assertEqual(summary["categories"][0]["count"], 2)
        self.assertEqual(len(summary["largest"]), 2)
        self.assertEqual(summary["largest"][0]["bytes"], 100)


if __name__ == "__main__":
    unittest.main()
