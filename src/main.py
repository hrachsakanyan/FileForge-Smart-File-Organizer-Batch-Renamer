"""FileForge - smart file organizer, batch renamer and duplicate finder.

Every command is a dry run by default: it prints the plan and changes nothing.
Add ``--apply`` once the plan looks right.

    py src/main.py organize ~/Downloads
    py src/main.py organize ~/Downloads --apply
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import deduper  # noqa: E402
import organizer  # noqa: E402
import renamer  # noqa: E402
from config import load_config  # noqa: E402
from core import (  # noqa: E402
    DELETE,
    Action,
    ExecutionResult,
    FileForgeError,
    execute,
    human_size,
    iter_files,
    list_history,
    load_history,
    plan_undo,
    prune_dirs,
    prune_empty_dirs,
    trash_dir,
)

BANNER = "FileForge"


# --------------------------------------------------------------------------
# Output helpers
# --------------------------------------------------------------------------


def show(path: str | Path, root: Path) -> str:
    """Paths read better relative to the folder being worked on."""
    path = Path(path)
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def print_header(command: str, root: Path, dry_run: bool, quiet: bool) -> None:
    if quiet:
        return
    mode = "DRY RUN - nothing will be changed" if dry_run else "APPLYING CHANGES"
    print(f"{BANNER} - {command}  ({mode})")
    print(f"folder: {root}")
    print()


def print_plan(actions: list[Action], root: Path, quiet: bool, limit: int = 0) -> None:
    if quiet:
        return
    shown = actions if limit <= 0 else actions[:limit]
    for action in shown:
        if action.kind == DELETE:
            print(f"  delete  {show(action.src, root)}    ({action.reason})")
        else:
            print(f"  move    {show(action.src, root)}  ->  {show(action.dst, root)}")
    if limit and len(actions) > limit:
        print(f"  ... and {len(actions) - limit} more")


def print_result(result: ExecutionResult, root: Path, quiet: bool) -> None:
    if quiet:
        return
    verb = "planned" if result.dry_run else "done"
    print()
    print(f"summary: {len(result.performed)} {verb}, {len(result.skipped)} skipped, "
          f"{len(result.failed)} failed")
    for action, why in result.skipped:
        print(f"  skipped {show(action.src, root)}: {why}")
    for action, why in result.failed:
        print(f"  FAILED  {show(action.src, root)}: {why}")
    if result.dry_run and result.performed:
        print("\nNothing was changed. Re-run with --apply to perform these changes.")
    if result.log_path is not None:
        print(f"log: {result.log_path}")
        print("undo with: py src/main.py undo " + str(root) + " --apply")


def collect(args, config) -> list[Path]:
    return iter_files(
        args.path,
        recursive=args.recursive,
        include_hidden=args.include_hidden,
        exts=args.ext,
        min_size=args.min_size,
        max_size=args.max_size,
        ignore=config.ignore,
    )


def run_plan(args, command: str, actions: list[Action], root: Path) -> int:
    dry_run = not args.apply
    print_plan(actions, root, args.quiet)
    if not actions:
        if not args.quiet:
            print("  (nothing to do)")
        return 0
    result = execute(
        actions,
        root=root,
        command=command,
        dry_run=dry_run,
        write_log=not args.no_log,
    )
    print_result(result, root, args.quiet)
    return 0 if result.ok else 1


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------


def cmd_organize(args) -> int:
    config = load_config(args.config)
    root = Path(args.path).resolve()
    print_header("organize", root, not args.apply, args.quiet)

    files = collect(args, config)
    actions = organizer.plan_organize(
        root,
        files,
        config,
        mode=args.by,
        date_format=args.date_format,
        date_source=args.date_source,
    )
    status = run_plan(args, "organize", actions, root)

    if args.prune_empty:
        removed = prune_empty_dirs(root, dry_run=not args.apply)
        if removed and not args.quiet:
            word = "would remove" if not args.apply else "removed"
            print(f"\n{word} {len(removed)} empty folder(s)")
            for path in removed:
                print(f"  {show(path, root)}")
    return status


def cmd_rename(args) -> int:
    config = load_config(args.config)
    root = Path(args.path).resolve()
    print_header("rename", root, not args.apply, args.quiet)

    files = collect(args, config)
    actions = renamer.plan_rename(
        files,
        pattern=args.pattern,
        regex=args.regex,
        replace=args.replace,
        start=args.start,
        step=args.step,
        sort=args.sort,
        case=args.case,
        date_format=args.date_format,
    )
    return run_plan(args, "rename", actions, root)


def cmd_dedupe(args) -> int:
    config = load_config(args.config)
    root = Path(args.path).resolve()
    print_header("dedupe", root, not args.apply, args.quiet)

    files = collect(args, config)
    groups = deduper.find_duplicates(files, algo=args.algo)

    if not groups:
        if not args.quiet:
            print("  no duplicates found")
        return 0

    if not args.quiet:
        for group in groups:
            keeper = deduper.pick_keeper(group, args.keep)
            for line in deduper.format_group(group, keeper, root):
                print(line)
        print(f"\nreclaimable: {human_size(deduper.wasted_space(groups))} "
              f"across {len(groups)} group(s)")
        print()

    destination = None if args.hard_delete else trash_dir(root)
    actions = deduper.plan_dedupe(groups, keep=args.keep, trash=destination, root=root)

    if args.hard_delete and not args.quiet:
        print("WARNING: --hard-delete removes files permanently and cannot be undone.\n")

    return run_plan(args, "dedupe", actions, root)


def cmd_report(args) -> int:
    config = load_config(args.config)
    root = Path(args.path).resolve()
    files = collect(args, config)
    summary = organizer.summarize(files, config, top=args.top)

    print(f"{BANNER} - report")
    print(f"folder: {root}")
    print(f"files:  {summary['files']}   total: {summary['human']}")
    print()
    if summary["categories"]:
        width = max(len(c["name"]) for c in summary["categories"])
        print(f"  {'category'.ljust(width)}  {'files':>6}  {'size':>10}  share")
        for entry in summary["categories"]:
            bar = "#" * max(1, round(entry["share"] / 5)) if entry["share"] else ""
            print(f"  {entry['name'].ljust(width)}  {entry['count']:>6}  "
                  f"{entry['human']:>10}  {entry['share']:5.1f}% {bar}")
    if summary["largest"]:
        print(f"\n  largest {len(summary['largest'])} file(s):")
        for entry in summary["largest"]:
            print(f"    {entry['human']:>10}  {show(entry['path'], root)}")
    return 0


def cmd_undo(args) -> int:
    root = Path(args.path).resolve()
    logs = list_history(root)
    if not logs:
        print(f"no FileForge history in {root}")
        return 0

    if args.list:
        print(f"{BANNER} - history for {root}")
        for path in logs:
            entry = load_history(path)
            print(f"  {path.name}  {entry['command']:<9} "
                  f"{len(entry['actions']):>4} action(s)  {entry['created']}")
        return 0

    target = logs[-1]
    if args.log:
        matches = [p for p in logs if p.name == args.log or p.stem == args.log]
        if not matches:
            raise FileForgeError(f"no log named {args.log!r} in {root}")
        target = matches[-1]

    entry = load_history(target)
    print_header(f"undo {target.name}", root, not args.apply, args.quiet)

    actions, lost = plan_undo(entry)
    if lost and not args.quiet:
        print(f"  {len(lost)} deleted file(s) cannot be restored:")
        for action in lost:
            print(f"    {show(action.src, root)}")
        print()

    status = run_plan(args, "undo", actions, root)
    if args.apply:
        # Folders the original run created are now empty - clear them away.
        emptied = prune_dirs(
            (a.src_path.parent for a in actions), root, dry_run=False
        )
        if emptied and not args.quiet:
            print(f"removed {len(emptied)} empty folder(s)")
        if status == 0 and not args.no_log:
            target.rename(target.with_suffix(".json.undone"))
    return status


def cmd_watch(args) -> int:
    config = load_config(args.config)
    root = Path(args.path).resolve()
    print_header("watch", root, not args.apply, args.quiet)
    print(f"polling every {args.interval}s - press Ctrl+C to stop\n")

    sizes: dict[Path, int] = {}
    seen: set[Path] = set()
    try:
        while True:
            settled: list[Path] = []
            for path in collect(args, config):
                try:
                    size = path.stat().st_size
                except OSError:
                    continue
                # Only touch a file once its size stopped changing, so we never
                # move a download that is still being written.
                if sizes.get(path) == size and path not in seen:
                    settled.append(path)
                sizes[path] = size

            if settled:
                actions = organizer.plan_organize(
                    root,
                    settled,
                    config,
                    mode=args.by,
                    date_format=args.date_format,
                    date_source=args.date_source,
                )
                print(f"[{time.strftime('%H:%M:%S')}] {len(actions)} new file(s)")
                print_plan(actions, root, args.quiet)
                result = execute(
                    actions,
                    root=root,
                    command="watch",
                    dry_run=not args.apply,
                    write_log=not args.no_log,
                )
                if not args.apply:
                    seen.update(settled)  # do not re-announce the same files
                for action, why in result.failed:
                    print(f"  FAILED  {show(action.src, root)}: {why}")
                print()
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


# --------------------------------------------------------------------------
# CLI wiring
# --------------------------------------------------------------------------


def add_common(parser: argparse.ArgumentParser, *, scan: bool = True) -> None:
    parser.add_argument("path", help="folder to work on")
    parser.add_argument("--apply", action="store_true",
                        help="actually perform the changes (default: dry run)")
    parser.add_argument("--dry-run", action="store_true",
                        help="explicit no-op flag; dry run is already the default")
    parser.add_argument("--config", help="JSON rules file (see config.example.json)")
    parser.add_argument("--quiet", action="store_true", help="print only errors")
    parser.add_argument("--no-log", action="store_true", help="do not write an undo log")
    if scan:
        parser.add_argument("-r", "--recursive", action="store_true",
                            help="also scan subfolders")
        parser.add_argument("--include-hidden", action="store_true",
                            help="include hidden files")
        parser.add_argument("--ext", nargs="+", metavar="EXT",
                            help="only these extensions, e.g. --ext jpg png")
        parser.add_argument("--min-size", type=str, help="skip files smaller than, e.g. 10mb")
        parser.add_argument("--max-size", type=str, help="skip files larger than, e.g. 2gb")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fileforge",
        description="Organize, rename and de-duplicate folders - safely.",
        epilog="Every command is a dry run until you add --apply.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # organize -------------------------------------------------------------
    p_org = subparsers.add_parser("organize", help="move files into subfolders")
    add_common(p_org)
    p_org.add_argument("--by", choices=organizer.MODES, default=organizer.BY_TYPE,
                       help="grouping strategy (default: type)")
    p_org.add_argument("--date-format", default=organizer.DEFAULT_DATE_FORMAT,
                       help=r"strftime format for date folders (default: %%Y/%%m-%%B)")
    p_org.add_argument("--date-source", choices=("mtime", "ctime"), default="mtime",
                       help="which timestamp to group by (default: mtime)")
    p_org.add_argument("--prune-empty", action="store_true",
                       help="remove folders left empty afterwards")
    p_org.set_defaults(func=cmd_organize)

    # rename ---------------------------------------------------------------
    placeholders = "  ".join(f"{k} = {v}" for k, v in renamer.PLACEHOLDERS.items())
    p_ren = subparsers.add_parser(
        "rename",
        help="batch rename by pattern and/or regex",
        epilog="placeholders: " + placeholders,
    )
    add_common(p_ren)
    p_ren.add_argument("--pattern", help='e.g. "{n:03d}_{name}{ext}" or "{date}-{name}{ext}"')
    p_ren.add_argument("--regex", help="regex applied to the name (without extension)")
    p_ren.add_argument("--replace", default="", help="replacement for --regex")
    p_ren.add_argument("--start", type=int, default=1, help="first {n} value (default: 1)")
    p_ren.add_argument("--step", type=int, default=1, help="{n} increment (default: 1)")
    p_ren.add_argument("--sort", choices=renamer.SORT_KEYS, default="name",
                       help="numbering order (default: name)")
    p_ren.add_argument("--case", choices=renamer.CASE_MODES, default="keep",
                       help="force the name to lower/upper case")
    p_ren.add_argument("--date-format", default="%Y-%m-%d",
                       help=r"strftime format for {date} (default: %%Y-%%m-%%d)")
    p_ren.set_defaults(func=cmd_rename)

    # dedupe ---------------------------------------------------------------
    p_dup = subparsers.add_parser("dedupe", help="find duplicates by content hash")
    add_common(p_dup)
    p_dup.add_argument("--keep", choices=deduper.KEEP_MODES, default="first",
                       help="which copy survives (default: first by path)")
    p_dup.add_argument("--algo", default="sha256", help="hash algorithm (default: sha256)")
    p_dup.add_argument("--hard-delete", action="store_true",
                       help="delete permanently instead of moving to .fileforge/trash")
    p_dup.set_defaults(func=cmd_dedupe)

    # report ---------------------------------------------------------------
    p_rep = subparsers.add_parser("report", help="size and category breakdown")
    add_common(p_rep)
    p_rep.add_argument("--top", type=int, default=10, help="how many large files to list")
    p_rep.set_defaults(func=cmd_report)

    # undo -----------------------------------------------------------------
    p_undo = subparsers.add_parser("undo", help="reverse a previous run")
    add_common(p_undo, scan=False)
    p_undo.add_argument("--list", action="store_true", help="show the history and exit")
    p_undo.add_argument("--log", help="undo this log instead of the most recent one")
    p_undo.set_defaults(func=cmd_undo)

    # watch ----------------------------------------------------------------
    p_watch = subparsers.add_parser("watch", help="keep a folder organized as files arrive")
    add_common(p_watch)
    p_watch.add_argument("--interval", type=float, default=5.0,
                         help="seconds between scans (default: 5)")
    p_watch.add_argument("--by", choices=organizer.MODES, default=organizer.BY_TYPE)
    p_watch.add_argument("--date-format", default=organizer.DEFAULT_DATE_FORMAT)
    p_watch.add_argument("--date-source", choices=("mtime", "ctime"), default="mtime")
    p_watch.set_defaults(func=cmd_watch)

    return parser


def normalize(args: argparse.Namespace) -> argparse.Namespace:
    """Fill in defaults for options a subcommand may not define, parse sizes."""
    from core import parse_size

    for name, default in (
        ("recursive", False),
        ("include_hidden", False),
        ("ext", None),
        ("min_size", None),
        ("max_size", None),
        ("quiet", False),
        ("no_log", False),
        ("config", None),
    ):
        if not hasattr(args, name):
            setattr(args, name, default)

    if args.dry_run:
        args.apply = False
    for field in ("min_size", "max_size"):
        value = getattr(args, field)
        if isinstance(value, str):
            setattr(args, field, parse_size(value))
    return args


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(normalize(args))
    except FileForgeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
