#!/usr/bin/env python3
"""
Script to merge all Markdown files under a directory into one .md,
then convert that merged.md → PDF via Pandoc + Tectonic
Supports many command line arguments and a TOML config file.
"""

import os
import sys
import re
import subprocess
import tempfile
import shutil
import getpass
from pathlib import Path
from datetime import date
from tqdm import tqdm  # progress bar
import time
import selectors
import mdfusion.htmlark.htmlark as htmlark
import pypandoc

from dataclasses import dataclass, field
import importlib.resources as pkg_resources
import bs4
from playwright.sync_api import sync_playwright

from .config_utils import (
    config_dataclass,
    discover_config_path,
    merge_cli_args_with_config_for,
    parse_known_args_for,
)
from .error_handling import validate_local_image_links
from .pandoc_errors import SourceLineSpan, handle_pandoc_error


def natural_key(s: str):
    return [int(tok) if tok.isdigit() else tok.lower() for tok in re.split(r"(\d+)", s)]


def find_markdown_files(root_dir: Path) -> list[Path]:
    md_paths = list(root_dir.rglob("*.md"))
    md_paths.sort(key=lambda p: natural_key(str(p.relative_to(root_dir))))
    return md_paths


def build_header(
    header_tex: Path | None = None,
    separate_title_page: bool = False,
    page_break_after_toc: bool = False,
) -> Path:
    header_content = (
        r"\usepackage[margin=1in]{geometry}"
        "\n"
        r"\usepackage{float}"
        "\n"
        r"\floatplacement{figure}{H}"
        "\n"
        r"\usepackage{sectsty}"
        "\n"
        r"\sectionfont{\centering\fontsize{16}{18}\selectfont}"
        "\n"
    )
    if separate_title_page:
        header_content += (
            r"\makeatletter"
            "\n"
            r"\renewcommand{\maketitle}{%"
            "\n"
            r"  \begin{titlepage}"
            "\n"
            r"  \centering"
            "\n"
            r"  \vspace*{\fill}"
            "\n"
            r"  {\Huge \@title \par}"
            "\n"
            r"  \vspace{1.5cm}"
            "\n"
            r"  {\Large \@author \par}"
            "\n"
            r"  \vspace{1cm}"
            "\n"
            r"  {\large \@date \par}"
            "\n"
            r"  \vspace*{\fill}"
            "\n"
            r"  \end{titlepage}"
            "\n"
            r"}"
            "\n"
            r"\makeatother"
            "\n"
        )
    if page_break_after_toc:
        header_content += (
            r"\makeatletter"
            "\n"
            r"\let\mdfusionoldtableofcontents\tableofcontents"
            "\n"
            r"\renewcommand{\tableofcontents}{%"
            "\n"
            r"  \mdfusionoldtableofcontents"
            "\n"
            r"  \clearpage"
            "\n"
            r"}"
            "\n"
            r"\makeatother"
            "\n"
        )
    tmp = tempfile.NamedTemporaryFile(
        "w", suffix=".tex", delete=False, encoding="utf-8"
    )
    tmp.write(header_content)
    if header_tex and header_tex.is_file():
        tmp.write("\n% --- begin user header.tex ---\n")
        tmp.write(header_tex.read_text(encoding="utf-8"))
        tmp.write("\n% --- end user header.tex ---\n")
    tmp.flush()
    hdr = Path(tmp.name)
    tmp.close()
    return hdr


def format_document_date(
    document_date: str | None = None, date_format: str = "%d.%m.%Y"
) -> str:
    if document_date is not None:
        return document_date
    return date.today().strftime(date_format)


def create_metadata(title: str, author: str, document_date: str) -> str:
    return (
        f'---\ntitle: "{title}"\nauthor: "{author}"\ndate: "{document_date}"\n---\n\n'
    )


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


def run_pandoc_with_spinner(
    cmd, out_pdf, source_spans: list[SourceLineSpan] | None = None
):
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,  # line-buffered
        )

        sel = selectors.DefaultSelector()
        sel.register(proc.stdout, selectors.EVENT_READ)
        sel.register(proc.stderr, selectors.EVENT_READ)

        spinner_cycle = ["|", "/", "-", "\\"]
        idx = 0
        spinner_msg = "Pandoc running... "
        stdout_lines: list[str] = []
        stderr_lines: list[str] = []

        while proc.poll() is None:
            # spinner
            print(
                f"\r{spinner_msg}{spinner_cycle[idx % len(spinner_cycle)]}",
                end="",
                flush=True,
            )
            idx += 1

            # read available pandoc output
            for key, _ in sel.select(timeout=0.1):
                line = key.fileobj.readline()
                if line:
                    if key.fileobj is proc.stdout:
                        stdout_lines.append(line)
                    else:
                        stderr_lines.append(line)
                    # clear spinner line before printing output
                    print("\r" + " " * (len(spinner_msg) + 2) + "\r", end="")
                    print(line, end="")

            time.sleep(0.05)

        # drain remaining output
        for stream, buffer in (
            (proc.stdout, stdout_lines),
            (proc.stderr, stderr_lines),
        ):
            for line in stream:
                buffer.append(line)
                print(line, end="")

        print("\r" + " " * (len(spinner_msg) + 2) + "\r", end="", flush=True)

        if proc.returncode != 0:
            raise subprocess.CalledProcessError(
                proc.returncode,
                cmd,
                output="".join(stdout_lines),
                stderr="".join(stderr_lines),
            )

        print(f"Merged PDF written to {out_pdf}")

    except subprocess.CalledProcessError as e:
        handle_pandoc_error(e, cmd, source_spans)


def wait_for_render_stable(page, *, timeout: int = 30_000) -> None:
    # DOM + subresources
    page.wait_for_load_state("domcontentloaded", timeout=timeout)
    page.wait_for_load_state("load", timeout=timeout)

    # Fonts (common reason PDFs look “unstyled” or shift)
    page.wait_for_function(
        """() => !document.fonts || document.fonts.status === 'loaded'""",
        timeout=timeout,
    )
    # If fonts API exists, wait for the promise too (more strict)
    page.evaluate("""() => document.fonts ? document.fonts.ready : Promise.resolve()""")

    # Give the browser a couple frames to flush style/layout/paint
    page.evaluate(
        """() => new Promise(resolve => {
            requestAnimationFrame(() => requestAnimationFrame(resolve));
        })"""
    )


def html_to_pdf(
    input_html: Path, chromium_path: str | None = None, output_pdf: Path | None = None
):
    """Convert HTML to PDF using Playwright."""
    if output_pdf is None:
        output_pdf = input_html.with_suffix(".pdf")

    with sync_playwright() as p:
        # if chromium is installed globally at specified path, use that
        if chromium_path and os.path.isfile(chromium_path):
            browser = p.chromium.launch(executable_path=chromium_path)
        else:
            try:
                browser = p.chromium.launch()
            except Exception as e:
                print("Error launching Chromium with Playwright:", e)
                print(
                    "Specify a chromium instance or make sure Playwright browsers are installed by running:"
                )
                print("    playwright install")
                sys.exit(1)
        page = browser.new_page()
        url = "file://" + str(input_html.resolve())
        page.goto(url + "?print-pdf", wait_until="networkidle")
        page.locator(".reveal.ready").wait_for()
        wait_for_render_stable(page)
        time.sleep(1)
        page.pdf(path=output_pdf, prefer_css_page_size=True)
        browser.close()


def bundle_html(input_html: Path, output_html: Path | None = None):
    """Bundle HTML with htmlark."""

    old_cwd = os.getcwd()
    os.chdir(input_html.parent)

    bundled_html = htmlark.convert_page(
        str(input_html),
        ignore_errors=False,
        ignore_images=False,
        ignore_css=False,
        ignore_js=False,
    )

    os.chdir(old_cwd)

    if output_html is None:
        output_html = input_html

    with open(output_html, "w", encoding="utf-8") as f:
        f.write(bundled_html)
    print(f"Bundled HTML written to {output_html}")


@config_dataclass("presentation")
class PresentationParams:
    presentation: bool = False  # if True, use reveal.js presentation mode
    footer_text: str | None = ""  # custom footer text for presentations
    animate_all_lines: bool = (
        False  # add reveal.js fragment animation to each line in presentations
    )
    chromium_path: str = "/usr/bin/chromium"  # path to chromium executable for HTML to PDF conversion. Optional, will use playwright's chromium if not provided. default: /usr/bin/chromium

    # Add help strings for simple-parsing
    def __post_init__(self):
        return


@config_dataclass("mdfusion")
class RunParams:
    presentation: PresentationParams = field(default_factory=PresentationParams)

    root_dir: Path | None = None  # root directory for Markdown files
    output: str | None = None  # output PDF filename (defaults to <root_dir>.pdf)
    title_page: bool = False  # include a title page
    separate_title_page: bool = (
        True  # render the title page on its own centered page with a page break after
    )
    title: str | None = None  # title for title page (defaults to dirname)
    author: str | None = None  # author for title page (defaults to OS user)
    document_date: str | None = None  # explicit date text for document metadata/title page
    date_format: str = "%d.%m.%Y"  # strftime format used when document_date is omitted
    pandoc_args: list[str] | str = field(
        default_factory=list
    )  # extra pandoc arguments, whitespace-separated
    config_path: Path | None = None  # path to a mdfusion.toml TOML config file
    header_tex: Path | None = (
        None  # path to a user-defined header.tex file (default: ./header.tex)
    )
    merged_md: Path | None = (
        None  # folder to write merged markdown to. Using a temp folder by default.
    )
    remove_alt_texts: list[str] = field(
        default_factory=lambda: ["alt text"]
    )  # alt texts to remove from images, comma-separated
    toc: bool = False  # include a table of contents
    page_break_after_toc: bool = False  # add a page break after the TOC in PDF output
    verbose: bool = False  # enable verbose output for pandoc

    # Add help strings for simple-parsing
    def __post_init__(self):
        # Ensure pandoc_args is always a list of strings
        if isinstance(self.pandoc_args, str):
            self.pandoc_args = self.pandoc_args.split()
        elif not isinstance(self.pandoc_args, list):
            self.pandoc_args = list(self.pandoc_args)

        if self.verbose:
            self.pandoc_args.append("--verbose")


def _normalize_params(params: RunParams) -> None:
    if isinstance(params.pandoc_args, str):
        params.pandoc_args = params.pandoc_args.split()
    elif params.pandoc_args is None:
        params.pandoc_args = []
    elif not isinstance(params.pandoc_args, list):
        params.pandoc_args = list(params.pandoc_args)

    if params.verbose and "--verbose" not in params.pandoc_args:
        params.pandoc_args.append("--verbose")


def _apply_presentation_pandoc_args(params: RunParams) -> None:
    if not params.presentation.presentation:
        return
    if params.output and not params.output.lower().endswith(".html"):
        raise ValueError(
            "Output file for presentations must be HTML, got: " + params.output
        )

    header_path = (
        pkg_resources.files("mdfusion.reveal").joinpath("header.html").__fspath__()
    )
    footer_path = (
        pkg_resources.files("mdfusion.reveal").joinpath("footer.html").__fspath__()
    )
    params.pandoc_args.extend(
        [
            "-t",
            "revealjs",
            "-V",
            "revealjs-url=https://cdn.jsdelivr.net/npm/reveal.js@4",
            "-H",
            header_path,
            "-A",
            footer_path,
        ]
    )


def run(params_: "RunParams"):
    # Merge config defaults with CLI args
    params: RunParams = merge_cli_args_with_config_for(
        params_, params_.config_path, root_cls=RunParams, normalize=_normalize_params
    )
    _apply_presentation_pandoc_args(params)

    if not params.root_dir:
        if params_.config_path:
            print(
                f"Using directory of config file as root_dir: {params_.config_path.parent}"
            )
            params.root_dir = params_.config_path.parent
        else:
            print("Using current directory as root_dir: ", Path.cwd())
            params.root_dir = Path.cwd()
    md_files = find_markdown_files(params.root_dir)
    if not md_files:
        print(f"No Markdown files found in {params.root_dir}", file=sys.stderr)
        sys.exit(1)

    validate_local_image_links(md_files)

    title = params.title or params.root_dir.name
    author = params.author or getpass.getuser()
    document_date = format_document_date(params.document_date, params.date_format)
    metadata = (
        create_metadata(title, author, document_date)
        if (params.title_page or params.title or params.author or params.document_date)
        else ""
    )
    use_separate_title_page = bool(
        params.title_page
        and metadata
        and not params.presentation.presentation
        and params.separate_title_page
    )
    use_page_break_after_toc = bool(
        params.toc
        and not params.presentation.presentation
        and params.page_break_after_toc
    )

    temp_dir = params.merged_md or Path(tempfile.mkdtemp(prefix="mdfusion_"))
    try:
        # Use params.header_tex if provided, else default to cwd/header.tex
        user_header = params.header_tex
        if user_header is None:
            user_header = Path.cwd() / "header.tex"
        if not user_header.is_file():
            user_header = None
        merged = temp_dir / "merged.md"
        source_spans = merge_markdown(
            md_files, merged, metadata, remove_alt=params.remove_alt_texts
        )

        resource_dirs = {str(p.parent) for p in md_files}
        resource_path = ":".join(sorted(resource_dirs))

        default_output = str(
            params.root_dir / f"{params.root_dir.name}.pdf"
            if not params.presentation.presentation
            else params.root_dir / f"{params.root_dir.name}.html"
        )
        out_pdf = params.output or default_output
        pandoc_bin = pypandoc.get_pandoc_path()
        cmd = [
            pandoc_bin,
            "-s",
            str(merged),
            "-o",
            out_pdf,
            "--pdf-engine=tectonic",
            # Tectonic omits the `l.<line> ...` context on failure unless
            # printing engine chatter. We need that snippet to map errors back
            # to the merged Markdown and then to the original source file.
            "--pdf-engine-opt=-p",
            f"--resource-path={resource_path}",
        ]
        # If md will be converted to latex, use latex header
        if out_pdf.endswith(".pdf"):
            hdr = build_header(
                user_header,
                separate_title_page=use_separate_title_page,
                page_break_after_toc=use_page_break_after_toc,
            )
            cmd.append(f"--include-in-header={hdr}")

        if params.toc:
            cmd.append("--toc")

        cmd.extend(params.pandoc_args)

        run_pandoc_with_spinner(cmd, out_pdf, source_spans)

        # If output is HTML, bundle it with htmlark
        # (always do this because custom plugins wont work otherwise)
        final_output = Path(out_pdf)
        if str(out_pdf).endswith(".html"):
            """
            Provide a config script tag with data attributes so public JS can read it.
            """
            # TODO allow including html files for this
            # Prepare inline config script
            config_script = (
                "<script>"
                f"window.config = {{ footerText: '{params.presentation.footer_text}', animateAllLines: {str(params.presentation.animate_all_lines).lower()} }};"
                "</script>"
            )

            # Inject inline window.config script into <head> in HTML output
            output_file = Path(out_pdf)
            html_content = output_file.read_text(encoding="utf-8")
            if "</head>" in html_content:
                html_content = html_content.replace(
                    "</head>", f"{config_script}\n</head>"
                )
            else:
                html_content = f"{config_script}\n" + html_content
            output_file.write_text(html_content, encoding="utf-8")

            # create a temp folder that contains the html and all necessary files:
            # copy the HTML output to a temp file
            temp_output = temp_dir / (Path(out_pdf).name)
            shutil.copy(str(final_output), str(temp_output))

            # copy public folder content into temp directory
            public_dir = Path(
                os.path.join(os.path.dirname(__file__), "reveal", "public")
            )
            if public_dir.is_dir():
                for item in public_dir.iterdir():
                    if item.is_file():
                        shutil.copy(item, temp_dir / item.name)

            bundle_html(temp_output, final_output)

        # if output is html presentation, convert to pdf as well
        if params.presentation.presentation:
            html_to_pdf(final_output, chromium_path=params.presentation.chromium_path)
            print(
                f"Converted HTML presentation to PDF: {final_output.with_suffix('.pdf')}"
            )
    except Exception as e:
        print(f"Error during processing: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        if params.merged_md is None:
            shutil.rmtree(temp_dir)


def main():
    cfg_path = discover_config_path(sys.argv)

    params, extra = parse_known_args_for(
        RunParams,
        description=(
            "Merge all Markdown files under a directory into one PDF, "
            "with optional title page, image-link rewriting, small margins."
        ),
    )
    params.config_path = cfg_path

    if extra:
        params.pandoc_args.extend(extra)

    run(params)


if __name__ == "__main__":
    main()
