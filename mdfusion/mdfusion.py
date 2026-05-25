#!/usr/bin/env python3
"""
Script to merge all Markdown files under a directory into one .md,
then convert that merged.md → PDF via Pandoc + Tectonic
Supports many command line arguments and a TOML config file.
"""

import os
import sys
import subprocess
import tempfile
import shutil
import getpass
import mimetypes
from pathlib import Path
from datetime import date
from tqdm import tqdm  # progress bar
import time
import selectors
import pypandoc
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from dataclasses import dataclass, field
import importlib.resources as pkg_resources
import bs4

from .bundle_html import bundle_html
from .config_utils import (
    config_dataclass,
    discover_config_path,
    merge_cli_args_with_config_for,
    parse_known_args_for,
)
from .error_handling import validate_local_image_links
from .find_markdown_files import find_markdown_files
from .html_to_pdf import html_to_pdf
from .merge_markdown import merge_markdown
from .pandoc_errors import SourceLineSpan, handle_pandoc_error


def build_header(
    header_tex: Path | None = None,
    separate_title_page: bool = False,
    page_break_after_toc: bool = False,
    title_page_image: str | None = None,
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
        r"\usepackage{graphicx}"
        "\n"
        r"\sectionfont{\centering\fontsize{16}{18}\selectfont}"
        "\n"
    )
    if separate_title_page or title_page_image:
        title_wrapper_start = (
            "  \\begin{titlepage}\n  \\centering\n  \\vspace*{\\fill}\n"
            if separate_title_page
            else "  \\begin{center}\n"
        )
        title_wrapper_end = (
            "  \\vspace*{\\fill}\n  \\end{titlepage}\n"
            if separate_title_page
            else "  \\end{center}\n"
        )
        image_block = ""
        if title_page_image:
            image_block = (
                r"  \vspace{1cm}"
                "\n"
                + rf"  \includegraphics[width=0.45\textwidth]{{{title_page_image}}}"
                + r"\\"
                + "\n"
                + r"  \vspace{1cm}"
                + "\n"
            )

        header_content += (
            "\\makeatletter\n"
            "\\renewcommand{\\maketitle}{%\n"
            f"{title_wrapper_start}"
            f"{image_block}"
            "  {\\Huge \\@title \\par}\n"
            "  \\vspace{1.5cm}\n"
            "  {\\Large \\@author \\par}\n"
            "  \\vspace{1cm}\n"
            "  {\\large \\@date \\par}\n"
            f"{title_wrapper_end}"
            "}\n"
            "\\makeatother\n"
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


def create_metadata(
    title: str, author: str, document_date: str, subtitle: str | None = None
) -> str:
    metadata_lines = [
        "---",
        f'title: "{title}"',
    ]
    if subtitle:
        metadata_lines.append(f'subtitle: "{subtitle}"')
    metadata_lines.extend(
        [
            f'author: "{author}"',
            f'date: "{document_date}"',
            "---",
            "",
        ]
    )
    return "\n".join(metadata_lines) + "\n"


def prepare_title_page_image(
    title_page_image: str | None, temp_dir: Path, base_dir: Path
) -> str | None:
    """Resolve local paths and download remote title-page images for LaTeX."""

    if not title_page_image:
        return None

    if title_page_image.startswith(("http://", "https://")):
        return _download_title_page_image(title_page_image, temp_dir)

    image_path = Path(title_page_image).expanduser()
    if not image_path.is_absolute():
        image_path = base_dir / image_path
    return image_path.resolve().as_posix()


def _download_title_page_image(title_page_image: str, temp_dir: Path) -> str:
    """Download a remote title-page image into the working temp directory."""

    request = Request(title_page_image, headers={"User-Agent": "mdfusion"})
    with urlopen(request, timeout=10) as response:
        content_type = response.headers.get_content_type()
        suffix = Path(urlparse(title_page_image).path).suffix.lower()
        if not suffix and content_type:
            suffix = mimetypes.guess_extension(content_type) or ""
        if suffix == ".jpe":
            suffix = ".jpg"
        if not suffix:
            suffix = ".img"

        image_path = temp_dir / f"title-page-image{suffix}"
        image_path.write_bytes(response.read())
        return image_path.resolve().as_posix()


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
    subtitle: str | None = None  # optional subtitle for the title page
    title_page_image: str | None = (
        None  # optional local path or URL for a title-page image
    )
    author: str | None = None  # author for title page (defaults to OS user)
    document_date: str | None = (
        None  # explicit date text for document metadata/title page
    )
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
    exclude: list[str] = field(
        default_factory=list
    )  # file/directory paths, names, or glob patterns to skip while merging
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


def _create_reveal_presentation(
    raw_html_file: str,
    final_output_html: Path,
    params: RunParams,
    temp_dir: Path,
):
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
    output_file = Path(raw_html_file)
    html_content = output_file.read_text(encoding="utf-8")
    if "</head>" in html_content:
        html_content = html_content.replace("</head>", f"{config_script}\n</head>")
    else:
        html_content = f"{config_script}\n" + html_content
    output_file.write_text(html_content, encoding="utf-8")

    # create a temp folder that contains the html and all necessary files:
    # copy the HTML output to a temp file
    temp_output = temp_dir / (Path(raw_html_file).name)
    shutil.copy(str(final_output_html), str(temp_output))

    # copy public folder content into temp directory
    public_dir = Path(os.path.join(os.path.dirname(__file__), "reveal", "public"))
    if public_dir.is_dir():
        for item in public_dir.iterdir():
            if item.is_file():
                shutil.copy(item, temp_dir / item.name)

    bundle_html(temp_output, final_output_html)


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
    md_files = find_markdown_files(params.root_dir, exclude=params.exclude)
    if not md_files:
        print(f"No Markdown files found in {params.root_dir}", file=sys.stderr)
        sys.exit(1)

    validate_local_image_links(md_files)

    title = params.title or params.root_dir.name
    author = params.author or getpass.getuser()
    document_date = format_document_date(params.document_date, params.date_format)
    metadata = (
        create_metadata(title, author, document_date, params.subtitle)
        if (
            params.title_page
            or params.title
            or params.subtitle
            or params.author
            or params.document_date
        )
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
        output_file = params.output or default_output
        resolved_title_page_image = None
        if (
            params.title_page
            and params.title_page_image
            and not params.presentation.presentation
            and str(output_file).endswith(".pdf")
        ):
            resolved_title_page_image = prepare_title_page_image(
                params.title_page_image, temp_dir, params.root_dir
            )
        pandoc_bin = pypandoc.get_pandoc_path()
        cmd = [
            pandoc_bin,
            "-s",
            str(merged),
            "-o",
            output_file,
            "--pdf-engine=tectonic",
            # Tectonic omits the `l.<line> ...` context on failure unless
            # printing engine chatter. We need that snippet to map errors back
            # to the merged Markdown and then to the original source file.
            "--pdf-engine-opt=-p",
            f"--resource-path={resource_path}",
        ]
        # If md will be converted to latex, use latex header
        if output_file.endswith(".pdf"):
            hdr = build_header(
                user_header,
                separate_title_page=use_separate_title_page,
                page_break_after_toc=use_page_break_after_toc,
                title_page_image=resolved_title_page_image,
            )
            cmd.append(f"--include-in-header={hdr}")

        if params.toc:
            cmd.append("--toc")

        cmd.extend(params.pandoc_args)

        run_pandoc_with_spinner(cmd, output_file, source_spans)

        # If output is HTML, bundle it with htmlark
        # (always do this because custom plugins wont work otherwise)
        final_output = Path(
            output_file
        )  # we write to the same file as the pandoc output
        if str(output_file).endswith(".html"):
            _create_reveal_presentation(output_file, final_output, params, temp_dir)

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
