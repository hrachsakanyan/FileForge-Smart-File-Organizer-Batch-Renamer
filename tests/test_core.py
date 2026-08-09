import unittest

from context import TempFolderTest  # noqa: F401  (also fixes sys.path)

from core import (
    MOVE,
    Action,
    FileForgeError,
    execute,
    human_size,
    iter_files,
    list_history,
    load_history,
    parse_size,
    plan_undo,
    prune_empty_dirs,
    unique_destination,
)


class SizeHelpers(unittest.TestCase):
    def test_parse_size_units(self):
        self.assertEqual(parse_size("1024"), 1024)
        self.assertEqual(parse_size("1kb"), 1024)
        self.assertEqual(parse_size("2 MB"), 2 * 1024**2)
        self.assertEqual(parse_size("1.5g"), int(1.5 * 1024**3))

    def test_parse_size_rejects_nonsense(self):
        with self.assertRaises(FileForgeError):
            parse_size("later")

    def test_human_size(self):
        self.assertEqual(human_size(0), "0 B")
        self.assertEqual(human_size(2048), "2.0 KB")


class Scanning(TempFolderTest):
    def test_non_recursive_by_default(self):
        self.make("a.txt")
        self.make("sub/b.txt")
        self.assertEqual([p.name for p in iter_files(self.root)], ["a.txt"])
        self.assertEqual(
            sorted(p.name for p in iter_files(self.root, recursive=True)),
            ["a.txt", "b.txt"],
        )

    def test_skips_hidden_and_workdir(self):
        self.make("visible.txt")
        self.make(".secret.txt")
        self.make(".fileforge/history/log.json")
        names = [p.name for p in iter_files(self.root, recursive=True)]
        self.assertEqual(names, ["visible.txt"])
        names = sorted(p.name for p in iter_files(self.root, recursive=True, include_hidden=True))
        self.assertEqual(names, [".secret.txt", "visible.txt"])

    def test_extension_and_size_filters(self):
        self.make("a.txt", "x")
        self.make("b.jpg", "x" * 100)
        self.assertEqual([p.name for p in iter_files(self.root, exts=["jpg"])], ["b.jpg"])
        self.assertEqual([p.name for p in iter_files(self.root, exts=[".JPG"])], ["b.jpg"])
        self.assertEqual([p.name for p in iter_files(self.root, min_size=50)], ["b.jpg"])
        self.assertEqual([p.name for p in iter_files(self.root, max_size=50)], ["a.txt"])

    def test_ignore_patterns(self):
        self.make("keep.txt")
        self.make("skip.tmp")
        found = [p.name for p in iter_files(self.root, ignore=["*.tmp"])]
        self.assertEqual(found, ["keep.txt"])

    def test_missing_folder_raises(self):
        with self.assertRaises(FileForgeError):
            iter_files(self.root / "nope")


class Destinations(TempFolderTest):
    def test_unique_destination_suffixes(self):
        self.make("a.txt")
        first = unique_destination(self.root / "a.txt")
        self.assertEqual(first.name, "a (1).txt")
        second = unique_destination(self.root / "a.txt", {first})
        self.assertEqual(second.name, "a (2).txt")


class Execution(TempFolderTest):
    def test_dry_run_changes_nothing(self):
        source = self.make("a.txt")
        action = Action(MOVE, str(source), str(self.root / "out" / "a.txt"))
        result = execute([action], root=self.root, command="test", dry_run=True)
        self.assertEqual(len(result.performed), 1)
        self.assertTrue(source.exists())
        self.assertEqual(self.tree(), {"a.txt"})
        self.assertIsNone(result.log_path)

    def test_apply_moves_and_logs(self):
        source = self.make("a.txt")
        action = Action(MOVE, str(source), str(self.root / "out" / "a.txt"))
        result = execute([action], root=self.root, command="test", dry_run=False)
        self.assertTrue(result.ok)
        self.assertEqual(self.tree(), {"out/a.txt", *self._log_files()})
        self.assertIsNotNone(result.log_path)
        self.assertEqual(load_history(result.log_path)["command"], "test")

    def test_missing_source_is_skipped_not_fatal(self):
        action = Action(MOVE, str(self.root / "ghost.txt"), str(self.root / "out.txt"))
        result = execute([action], root=self.root, command="test", dry_run=False)
        self.assertEqual(result.performed, [])
        self.assertEqual(len(result.skipped), 1)
        self.assertTrue(result.ok)

    def test_existing_destination_is_never_overwritten(self):
        source = self.make("a.txt", "new")
        self.make("out/a.txt", "old")
        action = Action(MOVE, str(source), str(self.root / "out" / "a.txt"))
        execute([action], root=self.root, command="test", dry_run=False)
        self.assertEqual((self.root / "out" / "a.txt").read_text(encoding="utf-8"), "old")
        self.assertEqual((self.root / "out" / "a (1).txt").read_text(encoding="utf-8"), "new")

    def test_undo_restores_the_original_layout(self):
        source = self.make("a.txt")
        before = self.tree()
        execute(
            [Action(MOVE, str(source), str(self.root / "Documents" / "a.txt"))],
            root=self.root,
            command="organize",
            dry_run=False,
        )
        self.assertNotIn("a.txt", self.tree())

        entry = load_history(list_history(self.root)[-1])
        undo, lost = plan_undo(entry)
        self.assertEqual(lost, [])
        execute(undo, root=self.root, command="undo", dry_run=False, write_log=False)
        self.assertEqual(self.tree() - self._log_files(), before)

    def test_prune_empty_dirs(self):
        (self.root / "empty" / "deep").mkdir(parents=True)
        self.make("full/a.txt")
        planned = prune_empty_dirs(self.root, dry_run=True)
        self.assertTrue((self.root / "empty").exists())
        self.assertEqual(len(planned), 2)
        prune_empty_dirs(self.root, dry_run=False)
        self.assertFalse((self.root / "empty").exists())
        self.assertTrue((self.root / "full").exists())

    def _log_files(self) -> set:
        return {
            p.relative_to(self.root).as_posix()
            for p in (self.root / ".fileforge").rglob("*")
            if p.is_file()
        }


if __name__ == "__main__":
    unittest.main()
