"""Put ``src/`` on the import path and give tests a temp-folder base class."""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


class TempFolderTest(unittest.TestCase):
    """Base class: every test gets a throwaway folder in ``self.root``."""

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="fileforge-test-")).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def make(self, relative: str, content: str = "hello") -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def tree(self) -> set[str]:
        """Every file under the root, as posix paths relative to it."""
        return {
            p.relative_to(self.root).as_posix()
            for p in self.root.rglob("*")
            if p.is_file()
        }
