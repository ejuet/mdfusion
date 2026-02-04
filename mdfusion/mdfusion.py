#!/usr/bin/env python3
"""
Script to merge all Markdown files under a directory into one .md,
then convert that merged.md → PDF via Pandoc + XeLaTeX
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

import toml as tomllib  # type: ignore
from dataclasses import dataclass, field
from simple_parsing import ArgumentParser
import importlib.resources as pkg_resources


def natural_key(s: str):
    return [int(tok) if tok.isdigit() else tok.lower() for tok in re.split(r"(\d+)", s)]


def find_markdown_files(root_dir: Path) -> list[Path]:
    md_paths = list(root_dir.rglob("*.md"))
    md_paths.sort(key=lambda p: natural_key(str(p.relative_to(root_dir))))
    return md_paths


def build_header(header_tex: Path | None = None) -> Path:
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


def create_metadata(title: str, author: str) -> str:
    today = date.today().isoformat()
    return f'---\ntitle: "{title}"\nauthor: "{author}"\ndate: "{today}"\n---\n\n'


def merge_markdown(md_files: list[Path], merged_md: Path, metadata: str, remove_alt: list[str] = []) -> None:
    """
    Merge multiple Markdown files into one, rewriting image links to absolute paths.
    If remove_alt is provided, all alt texts that match this string will be removed.
    """
    
    # Regex to find Markdown image links that are NOT already URLs
    IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
    
    with merged_md.open("w", encoding="utf-8") as out:
        if metadata:
            out.write(metadata)
        for md in tqdm(md_files, desc="Merging Markdown files", unit="file"):
            text = md.read_text(encoding="utf-8")

            def fix_link(m):
                alt, link = m.groups()
                if link.startswith("http://") or link.startswith("https://"):
                    return f"![{alt}]({link})"  # leave unchanged
                return f"![{alt}]({(md.parent/ link).resolve()})"

            # remove alt text if specified
            def fix_alt(m):
                alt, link = m.groups()
                alt_text = "" if alt in remove_alt else alt
                fixed = f"![{alt_text}]({link})"
                return fixed
            text = IMAGE_RE.sub(fix_alt, text)

            out.write(IMAGE_RE.sub(fix_link, text))
            out.write("\n\n")


def handle_pandoc_error(e, cmd):
    err = e.stderr or ""
    m = re.search(r"unrecognized option `([^']+)'", err) or re.search(
        r"Unknown option (--\\S+)", err
    )
    if m:
        bad = m.group(1)
        print(
            f"Error: argument '{bad}' not recognized.\n Try: pandoc --help",
            file=sys.stderr,
        )
    else:
        print(err.strip(), file=sys.stderr)
    sys.exit(1)



def run_pandoc_with_spinner(cmd, out_pdf):
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
                    # clear spinner line before printing output
                    print("\r" + " " * (len(spinner_msg) + 2) + "\r", end="")
                    print(line, end="")

            time.sleep(0.05)

        # drain remaining output
        for stream in (proc.stdout, proc.stderr):
            for line in stream:
                print(line, end="")

        print("\r" + " " * (len(spinner_msg) + 2) + "\r", end="", flush=True)

        if proc.returncode != 0:
            raise subprocess.CalledProcessError(proc.returncode, cmd)

        print(f"Merged PDF written to {out_pdf}")

    except subprocess.CalledProcessError as e:
        handle_pandoc_error(e, cmd)

def wait_for_render_stable(page, *, timeout: int = 30_000) -> None:
    # 1) DOM + subresources
    page.wait_for_load_state("domcontentloaded", timeout=timeout)
    page.wait_for_load_state("load", timeout=timeout)

    # 2) Fonts (common reason PDFs look “unstyled” or shift)
    page.wait_for_function(
        """() => !document.fonts || document.fonts.status === 'loaded'""",
        timeout=timeout,
    )
    # If fonts API exists, wait for the promise too (more strict)
    page.evaluate("""() => document.fonts ? document.fonts.ready : Promise.resolve()""")

    # 3) Give the browser a couple frames to flush style/layout/paint
    page.evaluate(
        """() => new Promise(resolve => {
            requestAnimationFrame(() => requestAnimationFrame(resolve));
        })"""
    )

    # 4) Optional: ensure there are no pending CSS animations/transitions
    # (Remove this if your page *intentionally* animates forever.)
    page.wait_for_function(
        """() => {
            const anims = document.getAnimations ? document.getAnimations() : [];
            return anims.every(a => a.playState === 'finished' || a.playState === 'idle');
        }""",
        timeout=timeout,
    )

def html_to_pdf(input_html: Path, chromium_path: str | None = None, output_pdf: Path | None = None):
    """Convert HTML to PDF using Playwright."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Error: Playwright is required for PDF conversion.", file=sys.stderr)
        sys.exit(1)

    if output_pdf is None:
        output_pdf = input_html.with_suffix(".pdf")

    with sync_playwright() as p:
        # if chromium is installed globally at specified path, use that
        if chromium_path and os.path.isfile(chromium_path):
            browser = p.chromium.launch(executable_path=chromium_path)
        else:
            browser = p.chromium.launch()
        page = browser.new_page()
        url = "file://" + str(input_html.resolve())
        page.goto(url + "?print-pdf", wait_until="networkidle")
        page.locator(".reveal.ready").wait_for()
        wait_for_render_stable(page)
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
        ignore_js=False
    )
    
    os.chdir(old_cwd)
    
    if output_html is None:
        output_html = input_html
    
    with open(output_html, "w", encoding="utf-8") as f:
        f.write(bundled_html)
    print(f"Bundled HTML written to {output_html}")

@dataclass
class RunParams:
    root_dir: Path | None = None  # root directory for Markdown files
    output: str | None = None  # output PDF filename (defaults to <root_dir>.pdf)
    title_page: bool = False  # include a title page
    title: str | None = None  # title for title page (defaults to dirname)
    author: str | None = None  # author for title page (defaults to OS user)
    pandoc_args: list[str] | str = field(default_factory=list)  # extra pandoc arguments, whitespace-separated
    config_path: Path | None = None  # path to a mdfusion.toml TOML config file
    header_tex: Path | None = None  # path to a user-defined header.tex file (default: ./header.tex)
    presentation: bool = False  # if True, use reveal.js presentation mode
    footer_text: str | None = ""  # custom footer text for presentations
    merged_md: Path | None = None  # folder to write merged markdown to. Using a temp folder by default.
    remove_alt_texts: list[str] = field(default_factory=lambda: ["alt text"])  # alt texts to remove from images, comma-separated
    toc: bool = False  # include a table of contents
    verbose: bool = False  # enable verbose output for pandoc
    chromium_path: str = "/usr/bin/chromium"  # path to chromium executable for HTML to PDF conversion. Optional, will use playwright's chromium if not provided. default: /usr/bin/chromium

    # Add help strings for simple-parsing
    def __post_init__(self):
        # Ensure pandoc_args is always a list of strings
        if isinstance(self.pandoc_args, str):
            self.pandoc_args = self.pandoc_args.split()
        elif not isinstance(self.pandoc_args, list):
            self.pandoc_args = list(self.pandoc_args)

        if self.presentation:
            if self.output and not self.output.lower().endswith(".html"):
                raise ValueError("Output file for presentations must be HTML, got: " + self.output)

            header_path = pkg_resources.files("mdfusion.reveal").joinpath("header.html").__fspath__()
            footer_path = pkg_resources.files("mdfusion.reveal").joinpath("footer.html").__fspath__()
            self.pandoc_args.extend(
                [
                    "-t",
                    "revealjs",
                    "-V",
                    "revealjs-url=https://cdn.jsdelivr.net/npm/reveal.js@4",
                    "-H", header_path,
                    "-A", footer_path
                ]
            )
        
        if self.verbose:
            self.pandoc_args.append("--verbose")


def run(params_: "RunParams"):
    if not requirements_met():
        return

    # Merge config defaults with CLI args
    params: RunParams = merge_cli_args_with_config(params_, params_.config_path)

    if not params.root_dir:
        if params_.config_path:
            print(f"Using directory of config file as root_dir: {params_.config_path.parent}")
            params.root_dir = params_.config_path.parent
        else:
            print("Using current directory as root_dir: ", Path.cwd())
            params.root_dir = Path.cwd()
    md_files = find_markdown_files(params.root_dir)
    if not md_files:
        print(f"No Markdown files found in {params.root_dir}", file=sys.stderr)
        sys.exit(1)

    title = params.title or params.root_dir.name
    author = params.author or getpass.getuser()
    metadata = (
        create_metadata(title, author)
        if (params.title_page or params.title or params.author)
        else ""
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
        merge_markdown(md_files, merged, metadata, remove_alt=params.remove_alt_texts)

        resource_dirs = {str(p.parent) for p in md_files}
        resource_path = ":".join(sorted(resource_dirs))

        default_output = str(params.root_dir / f"{params.root_dir.name}.pdf" if not params.presentation else params.root_dir / f"{params.root_dir.name}.html")
        out_pdf = params.output or default_output
        cmd = [
            "pandoc",
            "-s",
            str(merged),
            "-o",
            out_pdf,
            "--pdf-engine=xelatex",
            f"--resource-path={resource_path}",
        ]
        # If md will be converted to latex, use latex header
        if out_pdf.endswith(".pdf"):
            hdr = build_header(user_header)
            cmd.append(f"--include-in-header={hdr}")

        if params.toc:
            cmd.append("--toc")
        
        cmd.extend(params.pandoc_args)

        run_pandoc_with_spinner(cmd, out_pdf)
        
        
        
                
        # If output is HTML, bundle it with htmlark
        # (always do this because custom plugins wont work otherwise)
        final_output = Path(out_pdf)
        if str(out_pdf).endswith(".html"):
            
            
            """
            Create a js object with the custom plugin config
            So we can read the values from the HTML file/ Reveal plugins
            """
            # TODO allow including html files for this
            # Prepare inline config script
            config_script = f"<script>window.config = {{ footerText: '{params.footer_text}' }};</script>"
            
            # Inject inline window.config script into <head> in HTML output
            output_file = Path(out_pdf)
            html_content = output_file.read_text(encoding="utf-8")
            if "</head>" in html_content:
                html_content = html_content.replace("</head>", f"{config_script}\n</head>")
            else:
                html_content = f"{config_script}\n" + html_content
            output_file.write_text(html_content, encoding="utf-8")
            
            # create a temp folder that contains the html and all necessary files:
            # copy the HTML output to a temp file
            temp_output = temp_dir / (Path(out_pdf).name)
            shutil.copy(str(final_output), str(temp_output))
            
            # copy public folder content into temp directory
            public_dir = Path(os.path.join(os.path.dirname(__file__), "reveal", "public"))
            if public_dir.is_dir():
                for item in public_dir.iterdir():
                    if item.is_file():
                        shutil.copy(item, temp_dir / item.name)

            bundle_html(temp_output, final_output)
                
        # if output is html presentation, convert to pdf as well
        if params.presentation:
            html_to_pdf(final_output, chromium_path=params.chromium_path)
            print(f"Converted HTML presentation to PDF: {final_output.with_suffix('.pdf')}")
    except Exception as e:
        print(f"Error during processing: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        if params.merged_md is None:
            shutil.rmtree(temp_dir)


def load_config_defaults(cfg_path: Path | None) -> RunParams:
    """Load config defaults from TOML file, if present. Returns RunParams object."""
    params = RunParams()
    if cfg_path and cfg_path.is_file():
        with cfg_path.open("r", encoding="utf-8") as f:
            toml_data = tomllib.load(f)
        conf = toml_data.get("mdfusion", {})
        from dataclasses import fields
        runparams_fields = {f.name: f.type for f in fields(RunParams)}
        for k, v in conf.items():
            if k in runparams_fields:
                typ = runparams_fields[k]
                # Convert to Path if needed
                if typ == Path or typ == (Path | None):
                    setattr(params, k, Path(v))
                else:
                    setattr(params, k, v)
                    
    params.__post_init__()  # Ensure pandoc_args is a list
    return params

def merge_cli_args_with_config(cli_args: RunParams, config_path: Path | None) -> RunParams:
    """Merge CLI args with config defaults. CLI args take precedence. Arrays are merged."""
    config_params = load_config_defaults(config_path)
    from dataclasses import fields
    for f in fields(RunParams):
        k = f.name
        v = getattr(config_params, k, None)
        current = getattr(cli_args, k, None)
        # If the field is a list, merge arrays (config first, then CLI)
        if isinstance(v, list):
            if current is None or current == []:
                setattr(cli_args, k, v)
            else:
                merged = v + [item for item in current if item not in v]
                setattr(cli_args, k, merged)
        else:
            if current in (None, False, [], ""):
                setattr(cli_args, k, v)
    return cli_args


def requirements_met() -> bool:
    """Check if requirements are met."""
    # shutil.which is a builtin cross-platform which utility
    pandoc = shutil.which("pandoc")
    xetex = shutil.which("xetex")

    if not pandoc:
        print("ERR: pandoc not found", file=sys.stderr)
    if not xetex:
        print("ERR: xetex not found", file=sys.stderr)

    return bool(pandoc and xetex)


def main():
    # Check if config is specified via -c/--config
    cfg_path = None
    for i, a in enumerate(sys.argv):
        if a in ("-c", "--config_path") and i + 1 < len(sys.argv):
            cfg_path = Path(sys.argv[i + 1])
            break
        
    # If no config specified, check for mdfusion.toml in cwd
    if cfg_path is None:
        default_cfg = Path.cwd() / "mdfusion.toml"
        if default_cfg.is_file():
            cfg_path = default_cfg

    # 3) Arg parsing using simple-parsing
    parser = ArgumentParser(
        description=(
            "Merge all Markdown files under a directory into one PDF, "
            "with optional title page, image-link rewriting, small margins."
        )
    )
    parser.add_arguments(RunParams, dest="params")

    # Parse known args, allow extra pandoc args
    args, extra = parser.parse_known_args()

    params = args.params
    params.config_path = cfg_path

    # Handle extra pandoc args
    if extra:
        params.pandoc_args.extend(extra)

    run(params)


if __name__ == "__main__":
    main()
