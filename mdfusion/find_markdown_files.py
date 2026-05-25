import fnmatch
import re
from pathlib import Path


def natural_key(s: str):
    return [int(tok) if tok.isdigit() else tok.lower() for tok in re.split(r"(\d+)", s)]


def _matches_exclude_pattern(path: Path, root_dir: Path, pattern: str) -> bool:
    rel_path = path.relative_to(root_dir).as_posix()
    normalized_pattern = pattern.strip().replace("\\", "/").rstrip("/")
    if not normalized_pattern:
        return False

    if fnmatch.fnmatch(rel_path, normalized_pattern):
        return True
    if fnmatch.fnmatch(path.name, normalized_pattern):
        return True
    if rel_path == normalized_pattern or rel_path.startswith(normalized_pattern + "/"):
        return True
    return normalized_pattern in rel_path.split("/")


def find_markdown_files(root_dir: Path, exclude: list[str] | None = None) -> list[Path]:
    exclude_patterns = exclude or []
    md_paths = [
        path
        for path in root_dir.rglob("*.md")
        if not any(
            _matches_exclude_pattern(path, root_dir, pattern)
            for pattern in exclude_patterns
        )
    ]
    md_paths.sort(key=lambda p: natural_key(str(p.relative_to(root_dir))))
    return md_paths
