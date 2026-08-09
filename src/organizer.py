"""Planning moves: sort a messy folder by file type, by date, or by both."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Sequence

from config import Config
from core import MOVE, Action, FileForgeError, human_size, unique_destination

BY_TYPE = "type"
BY_DATE = "date"
BY_TYPE_DATE = "type+date"
BY_DATE_TYPE = "date+type"

MODES = (BY_TYPE, BY_DATE, BY_TYPE_DATE, BY_DATE_TYPE)

DEFAULT_DATE_FORMAT = "%Y/%m-%B"


def date_folder(path: Path, date_format: str = DEFAULT_DATE_FORMAT, source: str = "mtime") -> str:
    """Folder path (possibly nested, e.g. ``2024/03-March``) for a file's date."""
    stats = path.stat()
    timestamp = stats.st_ctime if source == "ctime" else stats.st_mtime
    try:
        return datetime.fromtimestamp(timestamp).strftime(date_format)
    except ValueError as exc:
        raise FileForgeError(f"bad date format {date_format!r}: {exc}") from exc


def destination_for(
    path: Path,
    root: Path,
    config: Config,
    *,
    mode: str = BY_TYPE,
    date_format: str = DEFAULT_DATE_FORMAT,
    date_source: str = "mtime",
) -> Path:
    """Where *path* belongs under *root*, before collision handling."""
    if mode not in MODES:
        raise FileForgeError(f"unknown mode {mode!r}, expected one of: {', '.join(MODES)}")

    category = config.category_for(path)
    if mode == BY_TYPE:
        parts = [category]
    elif mode == BY_DATE:
        parts = [date_folder(path, date_format, date_source)]
    elif mode == BY_TYPE_DATE:
        parts = [category, date_folder(path, date_format, date_source)]
    else:  # BY_DATE_TYPE
        parts = [date_folder(path, date_format, date_source), category]

    target = Path(root)
    for part in parts:
        target = target / part
    return target / path.name


def plan_organize(
    root: Path,
    files: Sequence[Path],
    config: Config,
    *,
    mode: str = BY_TYPE,
    date_format: str = DEFAULT_DATE_FORMAT,
    date_source: str = "mtime",
) -> list[Action]:
    """Build the move plan.  Files already in the right place are left alone."""
    root = Path(root)
    plan: list[Action] = []
    reserved: set[Path] = set()

    for path in files:
        target = destination_for(
            path,
            root,
            config,
            mode=mode,
            date_format=date_format,
            date_source=date_source,
        )
        if target == path:
            continue  # already sorted - moving it would be busywork
        final = unique_destination(target, reserved)
        reserved.add(final)
        plan.append(
            Action(
                kind=MOVE,
                src=str(path),
                dst=str(final),
                reason=final.parent.relative_to(root).as_posix(),
            )
        )
    return plan


# --------------------------------------------------------------------------
# Size report
# --------------------------------------------------------------------------


def summarize(files: Sequence[Path], config: Config, top: int = 10) -> dict:
    """Counts and sizes per category, plus the biggest files."""
    per_category: dict[str, dict[str, int]] = defaultdict(lambda: {"count": 0, "bytes": 0})
    sized: list[tuple[int, Path]] = []
    total_bytes = 0

    for path in files:
        try:
            size = path.stat().st_size
        except OSError:
            continue
        category = config.category_for(path)
        per_category[category]["count"] += 1
        per_category[category]["bytes"] += size
        total_bytes += size
        sized.append((size, path))

    sized.sort(key=lambda item: item[0], reverse=True)
    ordered = sorted(per_category.items(), key=lambda item: item[1]["bytes"], reverse=True)

    return {
        "files": len(files),
        "bytes": total_bytes,
        "human": human_size(total_bytes),
        "categories": [
            {
                "name": name,
                "count": stats["count"],
                "bytes": stats["bytes"],
                "human": human_size(stats["bytes"]),
                "share": (stats["bytes"] / total_bytes * 100) if total_bytes else 0.0,
            }
            for name, stats in ordered
        ],
        "largest": [
            {"path": path, "bytes": size, "human": human_size(size)}
            for size, path in sized[:top]
        ],
    }
