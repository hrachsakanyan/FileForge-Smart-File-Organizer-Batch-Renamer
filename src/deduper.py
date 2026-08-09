"""Duplicate detection by content hash, and a plan to clear the copies out."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from pathlib import Path
from typing import Sequence

from core import DELETE, MOVE, Action, FileForgeError, human_size, unique_destination

CHUNK_SIZE = 1024 * 1024  # 1 MB
PARTIAL_SIZE = 64 * 1024  # enough to separate most same-size files cheaply

KEEP_MODES = ("first", "oldest", "newest", "shortest-name", "shallowest")


def hash_file(path: Path, algo: str = "sha256", limit: int | None = None) -> str:
    """Hash a file in chunks; with *limit* only the first N bytes are read."""
    try:
        digest = hashlib.new(algo)
    except ValueError as exc:
        raise FileForgeError(f"unknown hash algorithm {algo!r}") from exc

    remaining = limit
    with open(path, "rb") as handle:
        while True:
            size = CHUNK_SIZE if remaining is None else min(CHUNK_SIZE, remaining)
            if size <= 0:
                break
            block = handle.read(size)
            if not block:
                break
            digest.update(block)
            if remaining is not None:
                remaining -= len(block)
    return digest.hexdigest()


def find_duplicates(
    files: Sequence[Path],
    *,
    algo: str = "sha256",
    on_progress=None,
) -> list[list[Path]]:
    """Group files with identical content.

    Three passes, cheapest first: size, then the first 64 KB, then the full
    hash.  Large media folders barely get read at all this way.
    """
    by_size: dict[int, list[Path]] = defaultdict(list)
    for path in files:
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size > 0:  # empty files are all "identical"; not worth reporting
            by_size[size].append(path)

    candidates = [group for group in by_size.values() if len(group) > 1]

    by_partial: dict[tuple[int, str], list[Path]] = defaultdict(list)
    for group in candidates:
        for path in group:
            try:
                key = (path.stat().st_size, hash_file(path, algo, PARTIAL_SIZE))
            except OSError:
                continue
            by_partial[key].append(path)

    duplicates: list[list[Path]] = []
    for group in by_partial.values():
        if len(group) < 2:
            continue
        by_full: dict[str, list[Path]] = defaultdict(list)
        for path in group:
            try:
                by_full[hash_file(path, algo)].append(path)
            except OSError:
                continue
            if on_progress is not None:
                on_progress(path)
        duplicates += [members for members in by_full.values() if len(members) > 1]

    return sorted(duplicates, key=lambda members: str(members[0]))


def pick_keeper(group: Sequence[Path], mode: str = "first") -> Path:
    """Choose the copy that stays."""
    if mode not in KEEP_MODES:
        raise FileForgeError(f"unknown keep mode {mode!r}, expected one of: {', '.join(KEEP_MODES)}")
    if mode == "oldest":
        return min(group, key=lambda p: (p.stat().st_mtime, str(p)))
    if mode == "newest":
        return max(group, key=lambda p: (p.stat().st_mtime, str(p)))
    if mode == "shortest-name":
        return min(group, key=lambda p: (len(p.name), str(p)))
    if mode == "shallowest":
        return min(group, key=lambda p: (len(p.parts), len(p.name), str(p)))
    return min(group, key=str)


def plan_dedupe(
    groups: Sequence[Sequence[Path]],
    *,
    keep: str = "first",
    trash: Path | None = None,
    root: Path | None = None,
) -> list[Action]:
    """Move (or delete) every copy except the keeper of each group.

    With *trash* set - the default in the CLI - duplicates are moved into
    ``.fileforge/trash/<timestamp>/`` instead of being unlinked, so the run
    stays undoable.  Passing ``trash=None`` produces real DELETE actions.
    """
    plan: list[Action] = []
    reserved: set[Path] = set()

    for group in groups:
        if len(group) < 2:
            continue
        keeper = pick_keeper(group, keep)
        for path in sorted(group, key=str):
            if path == keeper:
                continue
            reason = f"duplicate of {keeper.name}"
            if trash is None:
                plan.append(Action(kind=DELETE, src=str(path), reason=reason))
                continue
            target = _trash_target(path, trash, root)
            final = unique_destination(target, reserved)
            reserved.add(final)
            plan.append(Action(kind=MOVE, src=str(path), dst=str(final), reason=reason))
    return plan


def _trash_target(path: Path, trash: Path, root: Path | None) -> Path:
    """Mirror the file's location inside the trash so undo has a clear map."""
    if root is not None:
        try:
            return trash / path.resolve().relative_to(Path(root).resolve())
        except ValueError:
            pass
    return trash / path.name


def wasted_space(groups: Sequence[Sequence[Path]]) -> int:
    """Bytes that would be freed by keeping one copy per group."""
    total = 0
    for group in groups:
        if len(group) < 2:
            continue
        try:
            size = group[0].stat().st_size
        except OSError:
            continue
        total += size * (len(group) - 1)
    return total


def format_group(group: Sequence[Path], keeper: Path, root: Path | None = None) -> list[str]:
    """Human-readable lines for one duplicate group."""

    def show(path: Path) -> str:
        if root is not None:
            try:
                return path.relative_to(root).as_posix()
            except ValueError:
                pass
        return str(path)

    try:
        size = human_size(group[0].stat().st_size)
    except OSError:
        size = "?"
    lines = [f"  {len(group)} copies, {size} each"]
    for path in sorted(group, key=str):
        marker = "keep  " if path == keeper else "remove"
        lines.append(f"    [{marker}] {show(path)}")
    return lines
