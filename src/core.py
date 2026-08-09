"""Core primitives shared by every FileForge command.

The whole tool is built on one rule: a command never touches the filesystem
directly.  It *plans* a list of :class:`Action` objects, and only
:func:`execute` may carry them out - and only when it is called with
``dry_run=False``.  That is what makes ``--dry-run`` trustworthy instead of a
best-effort afterthought, and it is what gives us a free undo log.
"""

from __future__ import annotations

import fnmatch
import json
import os
import shutil
import stat
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Sequence

#: Everything FileForge writes lives here, and scans always skip it.
WORKDIR_NAME = ".fileforge"
HISTORY_DIRNAME = "history"
TRASH_DIRNAME = "trash"

MOVE = "move"
DELETE = "delete"

LOG_VERSION = 1


class FileForgeError(Exception):
    """A problem worth showing to the user without a traceback."""


# --------------------------------------------------------------------------
# Actions
# --------------------------------------------------------------------------


@dataclass
class Action:
    """A single intended filesystem change.

    ``kind`` is :data:`MOVE` (also used for renames and for moving duplicates
    into the trash) or :data:`DELETE` (irreversible).  Paths are stored as
    strings so an action can be JSON-serialised into the undo log as-is.
    """

    kind: str
    src: str
    dst: str = ""
    reason: str = ""

    @property
    def src_path(self) -> Path:
        return Path(self.src)

    @property
    def dst_path(self) -> Path:
        return Path(self.dst)

    def to_dict(self) -> dict:
        return {"kind": self.kind, "src": self.src, "dst": self.dst, "reason": self.reason}

    @classmethod
    def from_dict(cls, data: dict) -> "Action":
        return cls(
            kind=data["kind"],
            src=data["src"],
            dst=data.get("dst", ""),
            reason=data.get("reason", ""),
        )


@dataclass
class ExecutionResult:
    """What actually happened (or would happen) when a plan was run."""

    dry_run: bool = True
    performed: list[Action] = field(default_factory=list)
    skipped: list[tuple[Action, str]] = field(default_factory=list)
    failed: list[tuple[Action, str]] = field(default_factory=list)
    log_path: Path | None = None

    @property
    def ok(self) -> bool:
        return not self.failed


# --------------------------------------------------------------------------
# Sizes
# --------------------------------------------------------------------------

_SIZE_UNITS = {
    "b": 1,
    "k": 1024,
    "kb": 1024,
    "m": 1024**2,
    "mb": 1024**2,
    "g": 1024**3,
    "gb": 1024**3,
    "t": 1024**4,
    "tb": 1024**4,
}


def parse_size(text: str) -> int:
    """Turn ``"10mb"`` / ``"512k"`` / ``"2048"`` into a byte count."""
    raw = str(text).strip().lower().replace(" ", "")
    if not raw:
        raise FileForgeError("empty size value")
    digits = raw
    unit = "b"
    for suffix in sorted(_SIZE_UNITS, key=len, reverse=True):
        if raw.endswith(suffix) and raw[: -len(suffix)]:
            digits, unit = raw[: -len(suffix)], suffix
            break
    try:
        value = float(digits)
    except ValueError as exc:
        raise FileForgeError(f"cannot read size {text!r}") from exc
    if value < 0:
        raise FileForgeError(f"size cannot be negative: {text!r}")
    return int(value * _SIZE_UNITS[unit])


def human_size(num_bytes: int) -> str:
    """Format a byte count the way a file manager would."""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"  # pragma: no cover - unreachable, kept for clarity


# --------------------------------------------------------------------------
# Scanning
# --------------------------------------------------------------------------


def is_hidden(path: Path) -> bool:
    """Dot-files everywhere, plus the hidden attribute on Windows."""
    if path.name.startswith("."):
        return True
    try:
        attrs = path.stat().st_file_attributes  # Windows only
    except (AttributeError, OSError):
        return False
    return bool(attrs & stat.FILE_ATTRIBUTE_HIDDEN)


def iter_files(
    root: Path,
    *,
    recursive: bool = False,
    include_hidden: bool = False,
    exts: Sequence[str] | None = None,
    min_size: int | None = None,
    max_size: int | None = None,
    ignore: Sequence[str] = (),
) -> list[Path]:
    """Collect files under *root*, newest filters applied, sorted by path.

    Symlinks and anything inside :data:`WORKDIR_NAME` are always skipped -
    FileForge must never reorganise its own logs or trash.
    """
    root = Path(root)
    if not root.exists():
        raise FileForgeError(f"path does not exist: {root}")
    if not root.is_dir():
        raise FileForgeError(f"not a folder: {root}")

    wanted_exts = {e.lower() if e.startswith(".") else f".{e.lower()}" for e in (exts or ())}
    found: list[Path] = []

    for dirpath, dirnames, filenames in os.walk(root):
        current = Path(dirpath)
        dirnames[:] = sorted(
            d
            for d in dirnames
            if d != WORKDIR_NAME and (include_hidden or not is_hidden(current / d))
        )
        if not recursive:
            dirnames[:] = []

        for name in sorted(filenames):
            path = current / name
            if path.is_symlink() or not path.is_file():
                continue
            if not include_hidden and is_hidden(path):
                continue
            if wanted_exts and path.suffix.lower() not in wanted_exts:
                continue
            if _matches_any(path, root, ignore):
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue  # vanished or unreadable - nothing we can plan for
            if min_size is not None and size < min_size:
                continue
            if max_size is not None and size > max_size:
                continue
            found.append(path)

    return sorted(found)


def _matches_any(path: Path, root: Path, patterns: Sequence[str]) -> bool:
    if not patterns:
        return False
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError:  # pragma: no cover - path is always under root here
        relative = path.name
    return any(
        fnmatch.fnmatch(path.name, pat) or fnmatch.fnmatch(relative, pat) for pat in patterns
    )


# --------------------------------------------------------------------------
# Collision-safe destinations
# --------------------------------------------------------------------------


def unique_destination(dst: Path, reserved: set[Path] | None = None) -> Path:
    """Return *dst*, or ``name (1).ext`` etc. if it is taken.

    ``reserved`` holds destinations already claimed earlier in the same plan,
    so two files never plan their way onto the same name.
    """
    reserved = reserved if reserved is not None else set()
    if dst not in reserved and not dst.exists():
        return dst
    stem, suffix = dst.stem, dst.suffix
    counter = 1
    while True:
        candidate = dst.with_name(f"{stem} ({counter}){suffix}")
        if candidate not in reserved and not candidate.exists():
            return candidate
        counter += 1


# --------------------------------------------------------------------------
# Execution
# --------------------------------------------------------------------------


def execute(
    actions: Iterable[Action],
    *,
    root: Path,
    command: str,
    dry_run: bool = True,
    write_log: bool = True,
    on_event: Callable[[str, Action, str], None] | None = None,
) -> ExecutionResult:
    """Carry out a plan.  With ``dry_run=True`` nothing is written at all."""
    result = ExecutionResult(dry_run=dry_run)

    def emit(status: str, action: Action, detail: str = "") -> None:
        if on_event is not None:
            on_event(status, action, detail)

    for action in actions:
        src = action.src_path
        if not src.exists():
            result.skipped.append((action, "source no longer exists"))
            emit("skip", action, "source no longer exists")
            continue

        if dry_run:
            result.performed.append(action)
            emit("plan", action, "")
            continue

        try:
            if action.kind == MOVE:
                dst = action.dst_path
                if dst == src:
                    result.skipped.append((action, "source and destination are the same"))
                    emit("skip", action, "source and destination are the same")
                    continue
                dst.parent.mkdir(parents=True, exist_ok=True)
                # Re-check at the last moment: the disk may have changed since
                # planning, and shutil.move would happily overwrite.
                if dst.exists():
                    dst = unique_destination(dst)
                    action.dst = str(dst)
                shutil.move(str(src), str(dst))
            elif action.kind == DELETE:
                src.unlink()
            else:
                raise FileForgeError(f"unknown action kind: {action.kind!r}")
        except (OSError, FileForgeError) as exc:
            result.failed.append((action, str(exc)))
            emit("fail", action, str(exc))
        else:
            result.performed.append(action)
            emit("done", action, "")

    if not dry_run and write_log and result.performed:
        result.log_path = write_history(root, command, result.performed)

    return result


def prune_empty_dirs(root: Path, *, dry_run: bool = True) -> list[Path]:
    """Remove directories left empty after a move.  *root* itself is kept.

    Walking bottom-up and remembering what was (or would be) removed means a
    folder whose only content is other empty folders is reported too - even in
    a dry run, where nothing actually disappears.
    """
    root = Path(root)
    removed: list[Path] = []
    gone: set[Path] = set()

    for dirpath, _dirnames, _filenames in os.walk(root, topdown=False):
        current = Path(dirpath)
        if current == root or WORKDIR_NAME in current.relative_to(root).parts:
            continue
        try:
            if any(child not in gone for child in current.iterdir()):
                continue
            if not dry_run:
                current.rmdir()
        except OSError:
            continue
        gone.add(current)
        removed.append(current)
    return removed


# --------------------------------------------------------------------------
# History / undo log
# --------------------------------------------------------------------------


def prune_dirs(paths: Iterable[Path], root: Path, *, dry_run: bool = True) -> list[Path]:
    """Remove the given folders, and their parents up to *root*, if empty.

    Used after an undo so the category folders a run created do not linger.
    Unlike :func:`prune_empty_dirs` this never touches unrelated folders.
    """
    root = Path(root).resolve()
    removed: list[Path] = []
    candidates = sorted({Path(p).resolve() for p in paths}, key=lambda p: len(p.parts), reverse=True)

    for path in candidates:
        current = path
        while current != root and root in current.parents:
            if WORKDIR_NAME in current.relative_to(root).parts:
                break
            try:
                if any(current.iterdir()):
                    break
                if not dry_run:
                    current.rmdir()
            except OSError:
                break
            removed.append(current)
            current = current.parent
    return removed


def workdir(root: Path) -> Path:
    return Path(root) / WORKDIR_NAME


def trash_dir(root: Path, stamp: str | None = None) -> Path:
    stamp = stamp or datetime.now().strftime("%Y%m%d-%H%M%S")
    return workdir(root) / TRASH_DIRNAME / stamp


def write_history(root: Path, command: str, actions: Sequence[Action]) -> Path:
    """Append one JSON file describing everything a command just did."""
    history = workdir(root) / HISTORY_DIRNAME
    history.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    path = history / f"{stamp}-{command}.json"
    payload = {
        "version": LOG_VERSION,
        "command": command,
        "root": str(Path(root).resolve()),
        "created": datetime.now().isoformat(timespec="seconds"),
        "actions": [a.to_dict() for a in actions],
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def list_history(root: Path) -> list[Path]:
    """Every log for *root*, oldest first."""
    history = workdir(root) / HISTORY_DIRNAME
    if not history.is_dir():
        return []
    return sorted(history.glob("*.json"))


def load_history(path: Path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FileForgeError(f"cannot read log {path}: {exc}") from exc
    if data.get("version") != LOG_VERSION:
        raise FileForgeError(f"unsupported log version in {path}")
    return data


def plan_undo(entry: dict) -> tuple[list[Action], list[Action]]:
    """Split a log entry into (reversible moves, unrecoverable deletes).

    Moves are reversed in the opposite order they were performed, so chained
    operations unwind cleanly.
    """
    actions = [Action.from_dict(a) for a in entry.get("actions", [])]
    undoable: list[Action] = []
    lost: list[Action] = []
    reserved: set[Path] = set()

    for action in reversed(actions):
        if action.kind != MOVE:
            lost.append(action)
            continue
        target = unique_destination(action.src_path, reserved)
        reserved.add(target)
        undoable.append(
            Action(kind=MOVE, src=action.dst, dst=str(target), reason="undo")
        )
    return undoable, lost
