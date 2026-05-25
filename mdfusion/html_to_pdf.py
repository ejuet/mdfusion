import os
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


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
