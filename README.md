# FileForge — Smart File Organizer & Batch Renamer

A safety-first command line tool that cleans up messy folders: it sorts files
into subfolders by type or date, renames them in batches, finds duplicates by
content hash, and can undo everything it did.

Pure Python standard library — no dependencies.

```
$ py src/main.py organize ~/Downloads

FileForge - organize  (DRY RUN - nothing will be changed)
folder: C:\Users\you\Downloads

  move    backup.zip  ->  Archives/backup.zip
  move    IMG 001.jpg  ->  Images/IMG 001.jpg
  move    report final.pdf  ->  Documents/report final.pdf
  move    track.mp3  ->  Audio/track.mp3

summary: 4 planned, 0 skipped, 0 failed

Nothing was changed. Re-run with --apply to perform these changes.
```

## ⚠️ Dry run first

**Every command changes nothing until you add `--apply`.** Run it, read the
plan, and only then repeat the command with `--apply`. This is not a nicety —
it is the whole design: a command only ever *builds a list of actions*, and a
single executor is the only code allowed to touch the disk.

Two more safety nets:

- **Nothing is ever overwritten.** A name that is already taken becomes
  `report (1).pdf`.
- **Every applied run is logged** to `.fileforge/history/` and can be reversed
  with `undo`. Duplicates are moved to `.fileforge/trash/` rather than deleted,
  unless you explicitly ask for `--hard-delete`.

## Features

| Command | What it does |
| --- | --- |
| `organize` | Move files into subfolders by type, by date, or both |
| `rename` | Batch rename with `{n}`/`{date}` patterns and/or a regex |
| `dedupe` | Find identical files by hash and clear out the copies |
| `report` | Size and category breakdown, plus the biggest files |
| `undo` | Reverse the last run (or any run in the history) |
| `watch` | Keep a folder tidy as new files land in it |

Everything supports `--recursive`, `--ext`, `--min-size` / `--max-size`,
`--include-hidden`, `--config` and `--quiet`.

## Setup

```bash
git clone https://github.com/<you>/fileforge.git
cd fileforge
python --version   # 3.9 or newer
```

There is nothing to install. On Windows use `py` instead of `python`.

## Usage

### Organize

```bash
# by file type (Images/, Documents/, Audio/, ...)
python src/main.py organize ~/Downloads
python src/main.py organize ~/Downloads --apply

# by date: 2024/03-March/...
python src/main.py organize ~/Pictures --by date --date-format "%Y/%m-%B" --apply

# type first, then date, walking subfolders and cleaning up the empties
python src/main.py organize ~/Downloads --by type+date -r --prune-empty --apply
```

`--by` accepts `type`, `date`, `type+date`, `date+type`. Files already sitting
in the right place are left alone.

### Rename

```bash
# 001_holiday.jpg, 002_holiday.jpg, ...
python src/main.py rename ~/Pictures --pattern "{n:03d}_{name}{ext}" --apply

# spaces to underscores
python src/main.py rename ~/Docs --regex "\s+" --replace "_" --apply

# both: tidy the name, then date-and-number it, oldest first
python src/main.py rename ~/Pictures \
    --regex "\s+" --replace "-" \
    --pattern "{date}_{n:02d}_{name}{ext}" --sort date --apply
```

Placeholders: `{name}` (name without extension), `{ext}` (`.jpg`), `{n}`
(sequence number, format it as `{n:03d}`), `{date}` (from `--date-format`),
`{parent}` (folder name). The regex runs on `{name}` first, so the two compose.

Swaps and shifts are handled correctly — renaming `1,2,3` to `2,3,4` moves the
files through temporary names instead of overwriting each other.

### Find duplicates

```bash
python src/main.py dedupe ~/Downloads -r
python src/main.py dedupe ~/Downloads -r --keep oldest --apply
```

Files are compared in three passes — size, first 64 KB, then the full SHA-256 —
so large folders are barely read. `--keep` picks the survivor: `first`,
`oldest`, `newest`, `shortest-name`, `shallowest`.

### Report

```bash
python src/main.py report ~/Downloads -r --top 15
```

### Undo

```bash
python src/main.py undo ~/Downloads --list     # show the history
python src/main.py undo ~/Downloads            # preview the reversal
python src/main.py undo ~/Downloads --apply    # reverse the last run
```

Only `--hard-delete`d files cannot be restored; `undo` says so up front.

### Watch

```bash
python src/main.py watch ~/Downloads --interval 5 --apply
```

Polls the folder and organizes each new file once its size has stopped
changing, so half-finished downloads are never moved. Ctrl+C to stop.

## Config example

Custom categories live in a JSON file passed with `--config`
(see [`config.example.json`](config.example.json)):

```json
{
  "replace_defaults": false,
  "other_folder": "Misc",
  "categories": {
    "Design": [".psd", ".ai", ".fig"],
    "Ebooks": [".epub", ".mobi"]
  },
  "ignore": ["*.tmp", "*.part", "do-not-touch/*"]
}
```

Categories are merged into the built-ins unless `replace_defaults` is `true`.
`ignore` takes glob patterns and applies to every command.

## Project structure

```
fileforge/
├── src/
│   ├── main.py        # CLI: argument parsing and output
│   ├── core.py        # Action, scanning, safe execution, undo log
│   ├── config.py      # category rules and JSON config
│   ├── organizer.py   # organize + size report planning
│   ├── renamer.py     # batch rename planning
│   └── deduper.py     # hashing and duplicate planning
├── tests/             # 58 unittest tests, no third-party runner
├── config.example.json
├── requirements.txt
└── README.md
```

The interesting part is the split: `plan_*` functions are pure and return
`Action` objects, so a dry run is literally "build the plan, print it, stop".
`core.execute()` is the only function that writes to disk, which is why the
undo log is exact rather than a guess.

## Tests

```bash
python -m unittest discover -s tests -t tests -v
```

## Skills practised

`os` / `pathlib` / `shutil` for filesystem work, `re` for renaming, `hashlib`
for duplicate detection, `argparse` for the CLI, `json` for config and logs —
and dry-run/undo design, which is the habit worth keeping.
