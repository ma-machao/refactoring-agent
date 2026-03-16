from pathlib import Path
from typing import Iterable


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def read_text(path: Path, encoding: str = "utf-8") -> str:
    return path.read_text(encoding=encoding, errors="ignore")


def write_text(path: Path, content: str, encoding: str = "utf-8") -> None:
    ensure_dir(path.parent)
    path.write_text(content, encoding=encoding)


def list_all_files(root: Path, ignore_dirs: set[str] | None = None) -> list[Path]:
    ignore_dirs = ignore_dirs or set()
    files: list[Path] = []

    for path in root.rglob("*"):
        if not path.is_file():
            continue

        if _is_ignored(path, root, ignore_dirs):
            continue

        files.append(path)

    return sorted(files)


def find_files_by_name(root: Path, filename: str, ignore_dirs: set[str] | None = None) -> list[Path]:
    ignore_dirs = ignore_dirs or set()
    matched: list[Path] = []

    for path in root.rglob(filename):
        if path.is_file() and not _is_ignored(path, root, ignore_dirs):
            matched.append(path)

    return sorted(matched)


def find_files_by_suffixes(
    root: Path,
    suffixes: Iterable[str],
    ignore_dirs: set[str] | None = None,
) -> list[Path]:
    ignore_dirs = ignore_dirs or set()
    suffixes = set(suffixes)

    matched: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix not in suffixes:
            continue
        if _is_ignored(path, root, ignore_dirs):
            continue
        matched.append(path)

    return sorted(matched)


def relative_to_root(path: Path, root: Path) -> str:
    return str(path.relative_to(root))


def _is_ignored(path: Path, root: Path, ignore_dirs: set[str]) -> bool:
    try:
        rel_parts = path.relative_to(root).parts
    except ValueError:
        rel_parts = path.parts

    return any(part in ignore_dirs for part in rel_parts)
