"""Batch renaming: pattern placeholders and/or a regex substitution."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Sequence

from core import MOVE, Action, FileForgeError, unique_destination

#: Documented in ``--help`` and in the README.
PLACEHOLDERS = {
    "{name}": "current file name without extension",
    "{ext}": "extension including the dot (.jpg)",
    "{n}": "sequence number, formattable as {n:03d}",
    "{date}": "file date, controlled by --date-format",
    "{parent}": "name of the containing folder",
}

SORT_KEYS = ("name", "date", "size")
CASE_MODES = ("keep", "lower", "upper")

#: Windows forbids these outright; keeping the same rule everywhere avoids
#: producing names that only break once the folder is copied to Windows.
_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_TMP_PREFIX = ".fileforge-tmp-"


def sort_files(files: Sequence[Path], key: str = "name") -> list[Path]:
    if key not in SORT_KEYS:
        raise FileForgeError(f"unknown sort key {key!r}, expected one of: {', '.join(SORT_KEYS)}")
    if key == "date":
        return sorted(files, key=lambda p: (p.stat().st_mtime, str(p)))
    if key == "size":
        return sorted(files, key=lambda p: (p.stat().st_size, str(p)))
    return sorted(files, key=lambda p: str(p).lower())


def apply_regex(stem: str, pattern: str, replacement: str) -> str:
    try:
        return re.sub(pattern, replacement, stem)
    except re.error as exc:
        raise FileForgeError(f"bad regex {pattern!r}: {exc}") from exc


def render_pattern(
    pattern: str,
    path: Path,
    stem: str,
    number: int,
    date_format: str = "%Y-%m-%d",
) -> str:
    """Fill the placeholders of *pattern* for one file."""
    fields = {
        "name": stem,
        "ext": path.suffix,
        "n": number,
        "date": datetime.fromtimestamp(path.stat().st_mtime).strftime(date_format),
        "parent": path.parent.name,
    }
    try:
        return pattern.format(**fields)
    except KeyError as exc:
        known = ", ".join(sorted(PLACEHOLDERS))
        raise FileForgeError(f"unknown placeholder {{{exc.args[0]}}}; available: {known}") from exc
    except (ValueError, IndexError) as exc:
        raise FileForgeError(f"bad pattern {pattern!r}: {exc}") from exc


def validate_name(name: str, original: Path) -> str:
    """Reject names that would escape the folder or break on Windows."""
    cleaned = name.strip().rstrip(".")
    if not cleaned:
        raise FileForgeError(f"renaming {original.name!r} produced an empty name")
    if cleaned.startswith("."):
        # e.g. --pattern "{name}{ext}" after a regex wiped the whole stem: the
        # file would silently become hidden instead of just being renamed.
        raise FileForgeError(
            f"renaming {original.name!r} produced {cleaned!r}, which would hide the file"
        )
    if _ILLEGAL.search(cleaned):
        raise FileForgeError(
            f"renaming {original.name!r} produced an invalid name: {name!r}"
        )
    return cleaned


def plan_rename(
    files: Sequence[Path],
    *,
    pattern: str | None = None,
    regex: str | None = None,
    replace: str = "",
    start: int = 1,
    step: int = 1,
    sort: str = "name",
    case: str = "keep",
    date_format: str = "%Y-%m-%d",
) -> list[Action]:
    """Build the rename plan.

    ``regex`` is applied to the stem first, then ``pattern`` formats the
    result - so the two compose (``--regex "\\s+" --replace "_"`` to tidy
    names, then ``--pattern "{n:03d}_{name}{ext}"`` to number them).
    """
    if pattern is None and regex is None and case == "keep":
        raise FileForgeError("nothing to do: pass --pattern, --regex or --case")
    if case not in CASE_MODES:
        raise FileForgeError(f"unknown case mode {case!r}, expected one of: {', '.join(CASE_MODES)}")

    ordered = sort_files(files, sort)

    # Pass 1: what would each file like to be called?
    wanted: list[tuple[Path, Path]] = []
    number = start
    for path in ordered:
        stem = path.stem
        if regex is not None:
            stem = apply_regex(stem, regex, replace)
        if case == "lower":
            stem = stem.lower()
        elif case == "upper":
            stem = stem.upper()

        new_name = (
            render_pattern(pattern, path, stem, number, date_format)
            if pattern is not None
            else f"{stem}{path.suffix}"
        )
        new_name = validate_name(new_name, path)
        number += step

        target = path.parent / new_name
        # String compare, not Path compare: on Windows ``Path`` equality is
        # case-insensitive, which would silently drop a --case rename.
        if str(target) != str(path):
            wanted.append((path, target))

    if not wanted:
        return []

    # Pass 2: resolve collisions.  A name held by a file that is itself moving
    # away in this batch counts as free; anything else gets a " (1)" suffix.
    movers = {src.resolve() for src, _dst in wanted}
    targets: list[tuple[Path, Path]] = []
    reserved: set[Path] = set()
    for src, target in wanted:
        if target.resolve() in movers and target not in reserved:
            final = target
        else:
            final = unique_destination(target, reserved)
        reserved.add(final)
        targets.append((src, final))

    if _needs_two_phase(targets, movers):
        return _two_phase_plan(targets)

    return [
        Action(kind=MOVE, src=str(src), dst=str(dst), reason="rename")
        for src, dst in targets
    ]


def _needs_two_phase(targets: Sequence[tuple[Path, Path]], movers: set[Path]) -> bool:
    """True when some file's new name is another file's current name."""
    return any(dst.resolve() in movers for _src, dst in targets)


def _two_phase_plan(targets: Sequence[tuple[Path, Path]]) -> list[Action]:
    """Route every rename through a temporary name so swaps and shifts work.

    Renaming ``a -> b`` while ``b -> c`` (or worse, ``a <-> b``) cannot be done
    in place, so the whole batch moves aside first and then lands.
    """
    staged: list[tuple[Path, Path, Path]] = []
    for index, (src, dst) in enumerate(targets):
        tmp = unique_destination(
            src.parent / f"{_TMP_PREFIX}{index}-{src.name}",
            {t for _s, t, _d in staged},
        )
        staged.append((src, tmp, dst))

    plan = [
        Action(kind=MOVE, src=str(src), dst=str(tmp), reason="rename (staging)")
        for src, tmp, _dst in staged
    ]
    plan += [
        Action(kind=MOVE, src=str(tmp), dst=str(dst), reason="rename")
        for _src, tmp, dst in staged
    ]
    return plan
