import os
from pathlib import Path

import mdfusion.htmlark.htmlark as htmlark


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
