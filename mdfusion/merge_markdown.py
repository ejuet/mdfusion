import re
from pathlib import Path

from tqdm import tqdm  # progress bar

from .pandoc_errors import SourceLineSpan


def merge_markdown(
    md_files: list[Path],
    merged_md: Path,
    metadata: str,
    remove_alt: list[str] = [],
) -> list[SourceLineSpan]:
    """
    Merge multiple Markdown files into one, rewriting image links to absolute paths.

    Returns a span map that links merged line ranges back to the original
    Markdown files. The map only covers lines copied from source files; merged
    metadata and blank separator lines are intentionally left unmapped.
    """

    # Regex to find Markdown image links that are NOT already URLs
    IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
    source_spans: list[SourceLineSpan] = []
    merged_line_number = 1

    with merged_md.open("w", encoding="utf-8") as out:
        if metadata:
            out.write(metadata)
            merged_line_number += metadata.count("\n")
        for md in tqdm(md_files, desc="Merging Markdown files", unit="file"):
            text = md.read_text(encoding="utf-8")

            def fix_link(m):
                alt, link = m.groups()
                if link.startswith("http://") or link.startswith("https://"):
                    return f"![{alt}]({link})"  # leave unchanged
                return f"![{alt}]({(md.parent / link).resolve()})"

            # remove alt text if specified
            def fix_alt(m):
                alt, link = m.groups()
                alt_text = "" if alt in remove_alt else alt
                fixed = f"![{alt_text}]({link})"
                return fixed

            text = IMAGE_RE.sub(fix_alt, text)
            merged_text = IMAGE_RE.sub(fix_link, text)

            original_lines = text.splitlines()
            merged_lines = merged_text.splitlines()
            if original_lines and len(original_lines) == len(merged_lines):
                source_spans.append(
                    SourceLineSpan(
                        merged_start_line=merged_line_number,
                        merged_end_line=merged_line_number + len(original_lines) - 1,
                        source_path=md,
                        source_start_line=1,
                    )
                )

            out.write(merged_text)
            out.write("\n\n")
            merged_line_number += len(merged_lines) + 2

    return source_spans
