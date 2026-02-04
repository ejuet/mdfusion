# mdfusion

Merge all Markdown files in a directory tree into a single PDF or HTML presentation with formatting via Pandoc + XeLaTeX.

---

## Features

- **Recursively collects and sorts** all `.md` files under a directory (natural sort order)
- **Merges** them into one document, rewriting image links to absolute paths (so images with the same name in different folders don't collide)
- **Optionally adds a title page** with configurable title, author, and date
- **Supports both PDF (via Pandoc + XeLaTeX) and HTML presentations (via reveal.js)**
- **Customizes output** with your own LaTeX or HTML headers/footers
- **Configurable via TOML** for repeatable builds (great for books, reports, or slides)
- **Bundles HTML presentations** with all assets for easy sharing

---

## Installation

### Requirements

You must have the following on your `PATH`:

- [pandoc](https://pandoc.org/)
- [xetex](https://www.tug.org/xetex/) (for PDF output)

For HTML presentations and PDF export from HTML, you may also want to install:

- [Playwright](https://playwright.dev/python/) (for HTML→PDF conversion) via `pip install playwright` and then `playwright install`

### Install via pip

```sh
pip install mdfusion
```

### Install from source

```sh
git clone https://github.com/ejuet/mdfusion.git
cd mdfusion
pip install .
```

---

## Usage

```sh
mdfusion [OPTIONS]
```

You can also pass extra Pandoc arguments at the end of the command; any unknown flags are forwarded to Pandoc.

### Common options

- `--root_dir DIR`         Root directory for Markdown files (default: current directory, or config file directory)
- `--output FILE`          Output filename (default: `<root_dir>.pdf` or `.html` for presentations)
- `--toc`                  Include table of contents (use `--notoc` to disable)
- `--title_page`           Include a title page (PDF only)
- `--title TITLE`          Set title for title page (default: directory name)
- `--author AUTHOR`        Set author for title page (default: OS user)
- `--pandoc_args ARGS`     Extra Pandoc arguments (whitespace-separated)
- `--config_path FILE`     Path to a `mdfusion.toml` config file (default: `mdfusion.toml` in the current directory)
- `--header_tex PATH`      Custom LaTeX header to include (defaults to `./header.tex` if present)
- `--merged_md DIR`        Write merged Markdown to this directory (uses a temp dir by default)
- `--remove_alt_texts TXT` Comma-separated list of image alt texts to strip (default: `alt text`)
- `--verbose`              Enable verbose Pandoc output

### Presentation options

- `--presentation`         Output as a reveal.js HTML presentation (also converts to PDF)
- `--footer_text TEXT`     Custom footer for presentations
- `--animate_all_lines`    Add reveal.js fragment animation to each line
- `--chromium_path PATH`   Path to Chromium for HTML→PDF conversion (default: `/usr/bin/chromium`)

### Example: Merge docs/ into a PDF with a title page

```sh
mdfusion --root_dir docs --title_page --title "My Book" --author "Jane Doe"
```

### Example: Create a reveal.js HTML presentation

```sh
mdfusion --root_dir slides --presentation --title "My Talk" --author "Speaker" --footer_text "My Conference 2025"
```

---

## Configuration file

You can create a `mdfusion.toml` file in your project directory to avoid long command lines. The `[mdfusion]` section supports all the same options as the CLI. Presentation-only settings live under `[presentation]` (these can also remain under `[mdfusion]` for backward compatibility).

### Example: Normal document (PDF)

```toml
[mdfusion]
root_dir = "docs"
output = "my-book.pdf"
toc = true
title_page = true
title = "My Book"
author = "Jane Doe"
pandoc_args = ["--number-sections", "--slide-level", "2", "--toc-depth", "4"]
# header_tex = "header.tex"  # Optional: custom LaTeX header
```

### Example: Presentation (HTML via reveal.js)

```toml
[mdfusion]
root_dir = "slides"
output = "my-presentation.html"
title = "My Talk"
author = "Speaker"
pandoc_args = ["--slide-level", "6", "--number-sections", "-V", "transition=fade", "-c", "custom.css"]
# You can add more reveal.js or pandoc options as needed with ["-V", "option=value"]

[presentation]
presentation = true
footer_text = "My Presentation 2025"
animate_all_lines = false
# chromium_path = "/usr/bin/chromium"
```

Then just run:

```sh
mdfusion
```

---

## How it works

1. Finds and sorts all Markdown files under the root directory (natural order)
2. Merges them into one file, rewriting image links to absolute paths
3. Optionally adds a YAML metadata block for title/author/date
4. Calls Pandoc with XeLaTeX (for PDF) or reveal.js (for HTML presentations)
5. Optionally bundles HTML output with all assets for easy sharing

---

## Testing

Run all tests with:

```sh
pytest
```

---

## Author

[ejuet](https://github.com/ejuet)
