# 🗂️ FileForge  

### Smart File Organizer & Batch Renamer

> **A safety-first CLI tool for organizing, renaming, deduplicating, reporting, and undoing filesystem changes — built with pure Python.**

<p align="center">

**🛡️ Dry Run First** · **↩️ Undoable** · **🚫 No Overwrites** · **🐍 Pure Python** 

</p>

---

## ✨ What is FileForge?

**FileForge** is a safety-first command-line tool designed to clean up messy folders without putting your files at risk.

It can:

* 📁 Organize files by **type** or **date**
* ✏️ Batch rename files using **patterns** or **regex**
* 🔍 Find duplicate files using **SHA-256**
* 📊 Generate folder size and category reports
* 👀 Watch folders and organize new files automatically
* ↩️ Undo previous operations
* 🗑️ Move duplicates to a safe trash instead of deleting them

And most importantly:

> **FileForge never changes anything until you explicitly use `--apply`.**

---

## 🛡️ Safety First

FileForge is built around one simple principle:

### **Plan first. Execute second.**

Every command initially runs in **dry-run mode**.

```text
$ py src/main.py organize ~/Downloads

FileForge - organize  (DRY RUN - nothing will be changed)
folder: C:\Users\you\Downloads

  move    backup.zip       -> Archives/backup.zip
  move    IMG 001.jpg      -> Images/IMG 001.jpg
  move    report final.pdf -> Documents/report final.pdf
  move    track.mp3        -> Audio/track.mp3

summary: 4 planned, 0 skipped, 0 failed

Nothing was changed.
Re-run with --apply to perform these changes.
```

### 🔐 Three layers of protection

| Protection          | Description                                  |
| ------------------- | -------------------------------------------- |
| 🧪 **Dry Run**      | Nothing changes without `--apply`            |
| 🚫 **No Overwrite** | Existing names become `file (1).ext`         |
| ↩️ **Undo History** | Applied operations are logged and reversible |

Duplicates are moved to:

```text
.fileforge/trash/
```

instead of being permanently deleted.

Permanent deletion is only possible when explicitly requested with:

```bash
--hard-delete
```

---

# 🚀 Features

| Command       | Description                                    |
| ------------- | ---------------------------------------------- |
| 📁 `organize` | Move files into folders by type, date, or both |
| ✏️ `rename`   | Batch rename using patterns and/or regex       |
| 🔍 `dedupe`   | Find identical files and safely remove copies  |
| 📊 `report`   | Analyze sizes, categories, and biggest files   |
| ↩️ `undo`     | Reverse previous FileForge operations          |
| 👀 `watch`    | Automatically organize newly created files     |

### Global options

All commands support:

```text
--recursive
--ext
--min-size
--max-size
--include-hidden
--config
--quiet
```

---

# 📁 Organize

Organize files by their type:

```bash
python src/main.py organize ~/Downloads
```

Preview the changes:

```bash
python src/main.py organize ~/Downloads
```

Actually perform them:

```bash
python src/main.py organize ~/Downloads --apply
```

### 📅 Organize by date

```bash
python src/main.py organize ~/Pictures \
    --by date \
    --date-format "%Y/%m-%B" \
    --apply
```

Result:

```text
Pictures/
├── 2024/
│   ├── 03-March/
│   ├── 04-April/
│   └── 05-May/
```

### 🗂️ Type + Date

```bash
python src/main.py organize ~/Downloads \
    --by type+date \
    -r \
    --prune-empty \
    --apply
```

Supported modes:

```text
type
date
type+date
date+type
```

Files already located in the correct destination are automatically left alone.

---

# ✏️ Batch Rename

Rename hundreds of files using patterns.

### Numbered files

```bash
python src/main.py rename ~/Pictures \
    --pattern "{n:03d}_{name}{ext}" \
    --apply
```

Example:

```text
holiday.jpg
beach.jpg
sunset.jpg
```

becomes:

```text
001_holiday.jpg
002_beach.jpg
003_sunset.jpg
```

### 🔧 Regex renaming

Replace spaces with underscores:

```bash
python src/main.py rename ~/Docs \
    --regex "\s+" \
    --replace "_" \
    --apply
```

### 🔥 Combine regex + pattern

```bash
python src/main.py rename ~/Pictures \
    --regex "\s+" \
    --replace "-" \
    --pattern "{date}_{n:02d}_{name}{ext}" \
    --sort date \
    --apply
```

### Available placeholders

| Placeholder | Meaning                    |
| ----------- | -------------------------- |
| `{name}`    | Filename without extension |
| `{ext}`     | File extension             |
| `{n}`       | Sequence number            |
| `{date}`    | File date                  |
| `{parent}`  | Parent folder name         |

Number formatting is supported:

```text
{n:03d}
```

→ `001`, `002`, `003`

Regex runs on `{name}` first, allowing regex and patterns to be combined.

### 🔄 Safe rename operations 

FileForge correctly handles swaps and shifts.

For example:

```text
1.jpg → 2.jpg
2.jpg → 3.jpg
3.jpg → 4.jpg
```

Temporary filenames are used internally so files are never accidentally overwritten.

---

# 🔍 Duplicate Detection

Find duplicate files:

```bash
python src/main.py dedupe ~/Downloads -r
```

Preview which files would be removed:

```bash
python src/main.py dedupe ~/Downloads -r
```

Apply the operation:

```bash
python src/main.py dedupe ~/Downloads \
    -r \
    --keep oldest \
    --apply
```

### ⚡ Three-stage comparison

FileForge avoids unnecessarily hashing entire large files.

It compares files in three passes:

```text
1️⃣ File size
      ↓
2️⃣ First 64 KB
      ↓
3️⃣ Full SHA-256
```

Only files that survive the previous comparison move to the next stage.

### Survivor strategies

```text
first
oldest
newest
shortest-name
shallowest
```

---

# 📊 Reports

Get a breakdown of folder contents:

```bash
python src/main.py report ~/Downloads -r --top 15
```

Reports include:

* Total size
* Category breakdown
* Largest files
* File counts

---

# ↩️ Undo

FileForge keeps a history of applied operations.

View previous runs:

```bash
python src/main.py undo ~/Downloads --list
```

Preview the last reversal:

```bash
python src/main.py undo ~/Downloads
```

Actually undo it:

```bash
python src/main.py undo ~/Downloads --apply
```

History is stored inside:

```text
.fileforge/history/
```

Only files permanently removed with:

```bash
--hard-delete
```

cannot be restored.

FileForge explicitly reports this before performing an undo.

---

# 👀 Watch Mode

Keep a folder automatically organized:

```bash
python src/main.py watch ~/Downloads \
    --interval 5 \
    --apply
```

FileForge monitors the folder and waits until a new file's size stops changing before moving it.

This means partially downloaded files are not moved prematurely.

Stop watching with:

```text
Ctrl+C
```

---

# ⚙️ Configuration

Custom categories can be defined using a JSON configuration file.

Example:

```json
{
  "replace_defaults": false,
  "other_folder": "Misc",
  "categories": {
    "Design": [".psd", ".ai", ".fig"],
    "Ebooks": [".epub", ".mobi"]
  },
  "ignore": [
    "*.tmp",
    "*.part",
    "do-not-touch/*"
  ]
}
```

Pass the configuration file with:

```bash
--config config.json
```

### Configuration behavior

By default, custom categories are merged with built-in categories.

Set:

```json
"replace_defaults": true
```

to completely replace the default categories.

`ignore` patterns apply to every command.

---

# 🏗️ Architecture

The most important design decision in FileForge is the separation between **planning** and **execution**.

```text
                 ┌──────────────────┐
                 │      CLI         │
                 │    main.py       │
                 └────────┬─────────┘
                          │
                          ▼
                ┌────────────────────┐
                │   Planning Layer   │
                │                    │
                │ plan_organize()    │
                │ plan_rename()      │
                │ plan_dedupe()      │
                └─────────┬──────────┘
                          │
                          ▼
                 ┌─────────────────┐
                 │     Action      │
                 │     Objects     │
                 └────────┬────────┘
                          │
                   --apply only
                          │
                          ▼
                 ┌─────────────────┐
                 │    Executor     │
                 │   core.py       │
                 └────────┬────────┘
                          │
                          ▼
                    💾 Filesystem
                          │
                          ▼
                 ┌─────────────────┐
                 │  History Log    │
                 │ .fileforge/     │
                 └─────────────────┘
```

### Why this matters

`plan_*` functions are pure functions that return `Action` objects.

Therefore:

```text
Dry Run
   ↓
Build plan
   ↓
Print plan
   ↓
STOP
```

Nothing touches the filesystem.

Only:

```text
core.execute()
```

is allowed to perform filesystem modifications.

This makes the undo history exact rather than an educated guess.

---

# 📂 Project Structure

```text
fileforge/
│
├── src/
│   ├── main.py
│   │   └── CLI, argument parsing and output
│   │
│   ├── core.py
│   │   └── Action, scanning, execution and undo log
│   │
│   ├── config.py
│   │   └── Category rules and JSON configuration
│   │
│   ├── organizer.py
│   │   └── Organizing and size-report planning
│   │
│   ├── renamer.py
│   │   └── Batch rename planning
│   │
│   └── deduper.py
│       └── Hashing and duplicate planning
│
├── tests/
│   └── 58 unittest tests
│
├── config.example.json
├── requirements.txt
└── README.md
```

---

# 🧪 Tests

FileForge uses Python's built-in `unittest` framework.

No third-party test runner is required.

Run all tests:

```bash
python -m unittest discover -s tests -t tests -v
```

Current test suite:

```text
58 tests
```

---

# 🐍 Setup

FileForge uses only the Python standard library.

### Requirements

```text
Python 3.9+
```

Clone the repository:

```bash
git clone https://github.com/<you>/fileforge.git
cd fileforge
```

Check your Python version:

```bash
python --version
```

On Windows:

```bash
py --version
```

### Dependencies

```text
No external dependencies.
```

Everything is powered by Python's standard library.

---

# 🧰 Technologies

FileForge practices several important Python concepts:

| Technology | Purpose                     |
| ---------- | --------------------------- |
| `pathlib`  | Filesystem paths            |
| `os`       | Filesystem operations       |
| `shutil`   | Moving files                |
| `re`       | Regex-based renaming        |
| `hashlib`  | SHA-256 duplicate detection |
| `argparse` | CLI interface               |
| `json`     | Configuration and history   |
| `unittest` | Testing                     |

---

# 🧠 Skills Practised

Building FileForge reinforces:

* Python filesystem programming
* CLI application design
* `pathlib`
* `os`
* `shutil`
* Regular expressions
* SHA-256 hashing
* JSON configuration
* Unit testing
* Safe file operations
* Dry-run architecture
* Undo/rollback systems
* Batch processing
* Separation of planning and execution

The most important lesson:

> **Don't make destructive operations irreversible.**

---

# 🛣️ Roadmap

Possible future improvements:

* [ ] Richer terminal UI
* [ ] Interactive confirmation mode
* [ ] More file categories
* [ ] Parallel hashing for huge directories
* [ ] Scheduled organization
* [ ] Plugin system
* [ ] Cross-platform packaging
* [ ] Standalone executable
* [ ] More advanced reports

---

# 📜 License

This project is open source.

Add your preferred license here.

---

<p align="center">

### 🗂️ FileForge

**Clean folders. Rename smarter. Delete nothing by accident.**

</p>

<p align="center">
  Made with 🐍 Python
</p>

