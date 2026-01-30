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
mdfusion ROOT_DIR [OPTIONS]
```

### Common options

- `-o, --output FILE`      Output filename (default: `<root_dir>.pdf` or `.html` for presentations)
- `--no-toc`               Omit table of contents
- `--title-page`           Include a title page (PDF only)
- `--title TITLE`          Set title for title page (default: directory name)
- `--author AUTHOR`        Set author for title page (default: OS user)
- `--pandoc-args ARGS`     Extra Pandoc arguments (whitespace-separated)
- `-c, --config FILE`      Path to a `mdfusion.toml` config file (default: `mdfusion.toml` in the current directory)
- `--presentation`         Output as a reveal.js HTML presentation (not PDF)
- `--footer-text TEXT`     Custom footer for presentations

### Example: Merge docs/ into a PDF with a title page

```sh
mdfusion --title-page --title "My Book" --author "Jane Doe" docs/
```

### Example: Create a reveal.js HTML presentation

```sh
mdfusion --presentation --title "My Talk" --author "Speaker" --footer-text "My Conference 2025" slides/
```

---

## Configuration file

You can create a `mdfusion.toml` file in your project directory to avoid long command lines. The `[mdfusion]` section supports all the same options as the CLI.

### Example: Normal document (PDF)

```toml
[mdfusion]
root_dir = "docs"
output = "my-book.pdf"
no_toc = false
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
presentation = true
footer_text = "My Conference 2025"
pandoc_args = ["--slide-level", "6", "--number-sections", "-V", "transition=fade", "-c", "custom.css"]
# You can add more reveal.js or pandoc options as needed with ["-V", "option=value"]
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
