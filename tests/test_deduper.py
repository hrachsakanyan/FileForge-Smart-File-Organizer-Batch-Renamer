import hashlib
import os
import unittest
from datetime import datetime

from context import TempFolderTest

import deduper
from core import DELETE, MOVE, execute, iter_files, trash_dir


class Hashing(TempFolderTest):
    def test_hash_matches_hashlib(self):
        path = self.make("a.txt", "content")
        expected = hashlib.sha256(b"content").hexdigest()
        self.assertEqual(deduper.hash_file(path), expected)

    def test_partial_hash_reads_only_the_prefix(self):
        path = self.make("a.txt", "abcdef")
        self.assertEqual(deduper.hash_file(path, limit=3), hashlib.sha256(b"abc").hexdigest())

    def test_hash_survives_large_files(self):
        path = self.make("big.bin", "x" * (deduper.CHUNK_SIZE + 17))
        self.assertEqual(len(deduper.hash_file(path)), 64)


class Finding(TempFolderTest):
    def test_groups_identical_content_only(self):
        self.make("a/one.txt", "same")
        self.make("b/two.txt", "same")
        self.make("c/three.txt", "different")
        self.make("d/four.txt", "same but longer")

        groups = deduper.find_duplicates(iter_files(self.root, recursive=True))
        self.assertEqual(len(groups), 1)
        self.assertEqual(sorted(p.name for p in groups[0]), ["one.txt", "two.txt"])

    def test_same_size_different_content_is_not_a_duplicate(self):
        self.make("a.txt", "abc")
        self.make("b.txt", "xyz")
        self.assertEqual(deduper.find_duplicates(iter_files(self.root)), [])

    def test_empty_files_are_ignored(self):
        self.make("a.txt", "")
        self.make("b.txt", "")
        self.assertEqual(deduper.find_duplicates(iter_files(self.root)), [])

    def test_wasted_space(self):
        for name in ("a.txt", "b.txt", "c.txt"):
            self.make(name, "x" * 10)
        groups = deduper.find_duplicates(iter_files(self.root))
        self.assertEqual(deduper.wasted_space(groups), 20)


class Keeping(TempFolderTest):
    def setUp(self):
        super().setUp()
        self.old = self.make("sub/old-name-is-long.txt", "same")
        self.new = self.make("recent.txt", "same")
        stamp = datetime(2020, 1, 1).timestamp()
        os.utime(self.old, (stamp, stamp))
        self.group = deduper.find_duplicates(iter_files(self.root, recursive=True))[0]

    def test_keep_modes(self):
        self.assertEqual(deduper.pick_keeper(self.group, "oldest"), self.old)
        self.assertEqual(deduper.pick_keeper(self.group, "newest"), self.new)
        self.assertEqual(deduper.pick_keeper(self.group, "shortest-name"), self.new)
        self.assertEqual(deduper.pick_keeper(self.group, "shallowest"), self.new)


class Planning(TempFolderTest):
    def setUp(self):
        super().setUp()
        self.make("keep.txt", "same")
        self.make("zz-copy.txt", "same")
        self.groups = deduper.find_duplicates(iter_files(self.root))

    def test_trash_plan_keeps_one_copy_and_stays_undoable(self):
        plan = deduper.plan_dedupe(
            self.groups, keep="first", trash=trash_dir(self.root, "stamp"), root=self.root
        )
        self.assertEqual([a.kind for a in plan], [MOVE])
        execute(plan, root=self.root, command="dedupe", dry_run=False, write_log=False)
        self.assertEqual(
            self.tree(),
            {"keep.txt", ".fileforge/trash/stamp/zz-copy.txt"},
        )

    def test_hard_delete_plan_removes_the_file(self):
        plan = deduper.plan_dedupe(self.groups, keep="first", trash=None)
        self.assertEqual([a.kind for a in plan], [DELETE])
        execute(plan, root=self.root, command="dedupe", dry_run=False, write_log=False)
        self.assertEqual(self.tree(), {"keep.txt"})

    def test_dry_run_deletes_nothing(self):
        plan = deduper.plan_dedupe(self.groups, trash=None)
        execute(plan, root=self.root, command="dedupe", dry_run=True, write_log=False)
        self.assertEqual(self.tree(), {"keep.txt", "zz-copy.txt"})


if __name__ == "__main__":
    unittest.main()
