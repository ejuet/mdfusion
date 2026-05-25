import re
from datetime import date

import pytest

import mdfusion.mdfusion as mdfusion
from mdfusion.mdfusion import (
    natural_key,
    find_markdown_files,
    build_header,
    create_metadata,
    format_document_date,
    merge_markdown,
)


def test_natural_key_sorts_correctly():
    items = ["file2.md", "file10.md", "file1.md", "File20.md", "file3.md"]
    sorted_items = sorted(items, key=natural_key)
    assert sorted_items == [
        "file1.md",
        "file2.md",
        "file3.md",
        "file10.md",
        "File20.md",
    ]


def test_find_markdown_files(tmp_path):
    # create nested structure
    root = tmp_path / "docs"
    (root / "a").mkdir(parents=True)
    (root / "b").mkdir()
    # files in mixed order
    for name in ["2.md", "10.md", "1.md"]:
        (root / name).write_text(f"# {name}")
    (root / "a" / "3.md").write_text("# 3")
    (root / "b" / "11.md").write_text("# 11")
    # find and sort
    found = find_markdown_files(root)
    rel = [p.relative_to(root).as_posix() for p in found]
    assert rel == ["1.md", "2.md", "10.md", "a/3.md", "b/11.md"]


def test_build_header_without_user(tmp_path):
    hdr_path = build_header(None)
    content = hdr_path.read_text(encoding="utf-8")
    # default packages must be present
    assert r"\usepackage[margin=1in]{geometry}" in content
    assert r"\sectionfont{\centering\fontsize{16}{18}\selectfont}" in content
    assert r"\renewcommand{\maketitle}" not in content
    # no user header markers
    assert "% --- begin user header.tex ---" not in content
    hdr_path.unlink()


def test_build_header_with_user(tmp_path):
    # create a fake user header.tex
    user_hdr = tmp_path / "myhdr.tex"
    user_hdr.write_text("% custom header\n\\newcommand{\\foo}{bar}")
    hdr_path = build_header(user_hdr)
    content = hdr_path.read_text(encoding="utf-8")
    # default + user content wrapped
    assert "% --- begin user header.tex ---" in content
    assert "% custom header" in content
    assert "% --- end user header.tex ---" in content
    hdr_path.unlink()


def test_build_header_with_separate_title_page(tmp_path):
    hdr_path = build_header(None, separate_title_page=True)
    content = hdr_path.read_text(encoding="utf-8")
    assert r"\renewcommand{\maketitle}" in content
    assert r"\begin{titlepage}" in content
    assert r"\vspace*{\fill}" in content
    hdr_path.unlink()


def test_build_header_with_page_break_after_toc(tmp_path):
    hdr_path = build_header(None, page_break_after_toc=True)
    content = hdr_path.read_text(encoding="utf-8")
    assert r"\renewcommand{\tableofcontents}" in content
    assert r"\clearpage" in content
    hdr_path.unlink()


def test_run_params_enable_separate_title_page_by_default():
    params = mdfusion.RunParams()
    assert params.separate_title_page is True


def test_run_params_disable_subtitle_by_default():
    params = mdfusion.RunParams()
    assert params.subtitle is None


def test_run_params_disable_page_break_after_toc_by_default():
    params = mdfusion.RunParams()
    assert params.page_break_after_toc is False


def test_run_params_default_date_format():
    params = mdfusion.RunParams()
    assert params.date_format == "%d.%m.%Y"


def test_format_document_date_uses_default_format():
    expected = date.today().strftime("%d.%m.%Y")
    assert format_document_date() == expected


def test_format_document_date_uses_custom_format():
    expected = date.today().strftime("%Y/%m/%d")
    assert format_document_date(date_format="%Y/%m/%d") == expected


def test_format_document_date_prefers_explicit_value():
    assert format_document_date("2026-05-25", "%Y/%m/%d") == "2026-05-25"


def test_create_metadata_includes_fields_and_formatted_date():
    title = "My Title"
    author = "Jane Doe"
    document_date = "25.05.2026"
    md = create_metadata(title, author, document_date)
    # YAML block markers
    assert md.startswith("---\n")
    assert f'title: "{title}"' in md
    assert f'author: "{author}"' in md
    assert f'date: "{document_date}"' in md
    assert md.endswith("\n\n")


def test_create_metadata_includes_subtitle_when_present():
    md = create_metadata("My Title", "Jane Doe", "25.05.2026", "My Subtitle")
    assert 'subtitle: "My Subtitle"' in md


def test_merge_markdown_rewrites_image_links_and_adds_pages(tmp_path):
    # setup two markdown files with relative images
    base = tmp_path / "project"
    sub = base / "sub"
    sub.mkdir(parents=True)
    img1 = base / "pic.png"
    img1.write_bytes(b"PNGDATA")
    img2 = sub / "pic.png"
    img2.write_bytes(b"PNGDATA2")

    md1 = base / "one.md"
    md1.write_text("Intro text\n\n![A pic](pic.png)\nEnd.")
    md2 = sub / "two.md"
    md2.write_text("Second file\n\n![Another](pic.png)\nDone.")

    merged = tmp_path / "merged.md"
    metadata = "METABLOCK\n\n"
    source_spans = merge_markdown([md1, md2], merged, metadata)

    out = merged.read_text(encoding="utf-8")
    # metadata at top
    assert out.startswith("METABLOCK")

    # check that each image link was replaced with absolute path
    abs1 = str((md1.parent / "pic.png").resolve())
    abs2 = str((md2.parent / "pic.png").resolve())
    # regex to find rewritten links
    assert re.search(rf"!\[A pic\]\({re.escape(abs1)}\)", out)
    assert re.search(rf"!\[Another\]\({re.escape(abs2)}\)", out)
    
    # Also check that the mapping from merged lines back to source lines is correct
    assert len(source_spans) == 2
    assert source_spans[0].source_path == md1
    assert source_spans[0].source_start_line == 1
    assert source_spans[0].merged_start_line == metadata.count("\n") + 1
    assert source_spans[0].merged_end_line == source_spans[0].merged_start_line + 3
    assert source_spans[1].source_path == md2
    assert source_spans[1].source_start_line == 1
    assert source_spans[1].merged_start_line == source_spans[0].merged_end_line + 3
    assert source_spans[1].merged_end_line == source_spans[1].merged_start_line + 3


def test_merge_without_metadata(tmp_path):
    # one empty md
    md = tmp_path / "a.md"
    md.write_text("Hello")
    merged = tmp_path / "merged2.md"
    source_spans = merge_markdown([md], merged, metadata="")
    out = merged.read_text(encoding="utf-8")
    # no YAML, but page break before content
    assert "Hello" in out
    assert len(source_spans) == 1
    assert source_spans[0].source_path == md
    assert source_spans[0].merged_start_line == 1
    assert source_spans[0].merged_end_line == 1
