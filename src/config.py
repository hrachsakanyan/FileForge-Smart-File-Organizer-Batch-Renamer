"""Category rules: the built-in defaults plus optional JSON overrides."""

from __future__ import annotations

import json
from pathlib import Path

from core import FileForgeError

#: Extension -> folder name.  Anything unlisted lands in :data:`OTHER_FOLDER`.
DEFAULT_CATEGORIES: dict[str, list[str]] = {
    "Images": [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg", ".heic", ".tiff", ".ico"],
    "Video": [".mp4", ".mkv", ".mov", ".avi", ".wmv", ".flv", ".webm", ".m4v"],
    "Audio": [".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma", ".opus"],
    "Documents": [
        ".pdf", ".doc", ".docx", ".odt", ".rtf", ".txt", ".md", ".tex",
        ".xls", ".xlsx", ".ods", ".csv", ".ppt", ".pptx", ".odp", ".epub",
    ],
    "Archives": [".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".iso"],
    "Code": [
        ".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css", ".scss", ".json",
        ".yaml", ".yml", ".xml", ".java", ".c", ".h", ".cpp", ".cs", ".go",
        ".rs", ".rb", ".php", ".sh", ".ps1", ".sql", ".ipynb",
    ],
    "Installers": [".exe", ".msi", ".apk", ".dmg", ".pkg", ".deb", ".rpm", ".appimage"],
    "Fonts": [".ttf", ".otf", ".woff", ".woff2"],
}

OTHER_FOLDER = "Other"

#: Skipped by every command unless the user overrides ``ignore`` in a config.
DEFAULT_IGNORE = ["*.tmp", "*.part", "*.crdownload", "desktop.ini", "Thumbs.db", ".DS_Store"]


class Config:
    """Resolved rules for one run."""

    def __init__(
        self,
        categories: dict[str, list[str]] | None = None,
        other_folder: str = OTHER_FOLDER,
        ignore: list[str] | None = None,
    ) -> None:
        self.categories = categories if categories is not None else _copy_defaults()
        self.other_folder = other_folder
        self.ignore = list(ignore) if ignore is not None else list(DEFAULT_IGNORE)
        self._by_ext = {
            ext.lower(): name
            for name, extensions in self.categories.items()
            for ext in extensions
        }

    def category_for(self, path: Path) -> str:
        """Folder name for *path*, based on its extension."""
        return self._by_ext.get(Path(path).suffix.lower(), self.other_folder)

    @property
    def folder_names(self) -> set[str]:
        return set(self.categories) | {self.other_folder}


def _copy_defaults() -> dict[str, list[str]]:
    return {name: list(exts) for name, exts in DEFAULT_CATEGORIES.items()}


def load_config(path: str | Path | None) -> Config:
    """Read a JSON rules file.  Without *path* the built-in defaults are used.

    The file may contain::

        {
          "replace_defaults": false,
          "other_folder": "Misc",
          "categories": {"Design": [".psd", ".ai"]},
          "ignore": ["*.tmp"]
        }

    By default the categories are *merged* into the built-ins, so a small
    config only has to describe what is different.
    """
    if path is None:
        return Config()

    config_path = Path(path)
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FileForgeError(f"config not found: {config_path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise FileForgeError(f"cannot read config {config_path}: {exc}") from exc

    if not isinstance(data, dict):
        raise FileForgeError(f"config must be a JSON object: {config_path}")

    categories = {} if data.get("replace_defaults") else _copy_defaults()
    raw_categories = data.get("categories", {})
    if not isinstance(raw_categories, dict):
        raise FileForgeError("config: 'categories' must be an object")

    for name, extensions in raw_categories.items():
        if isinstance(extensions, str) or not isinstance(extensions, (list, tuple)):
            raise FileForgeError(f"config: category {name!r} must map to a list of extensions")
        categories[name] = [
            ext.lower() if ext.startswith(".") else f".{ext.lower()}" for ext in extensions
        ]

    ignore = data.get("ignore")
    if ignore is not None and not isinstance(ignore, list):
        raise FileForgeError("config: 'ignore' must be a list of glob patterns")

    return Config(
        categories=categories,
        other_folder=str(data.get("other_folder", OTHER_FOLDER)),
        ignore=ignore,
    )
