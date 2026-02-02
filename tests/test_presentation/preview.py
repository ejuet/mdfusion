#!/usr/bin/env python3
import os
import argparse
from playwright.sync_api import sync_playwright

def main():
    parser = argparse.ArgumentParser(
        description="Open a Reveal.js deck in Chromium with print CSS emulation"
    )
    parser.add_argument(
        "--input",
        help="Path to your Reveal.js HTML file",
        type=os.path.abspath,
        default=os.path.join(os.path.dirname(__file__), "my_presentation.html"),
    )
    args = parser.parse_args()

    with sync_playwright() as p:
        # Launch the Chromium that comes with Playwright, in headed mode
        browser = p.chromium.launch(headless=False, executable_path="/usr/bin/chromium")
        page = browser.new_page()

        # Tell the page to use your @media print rules
        page.emulate_media(media="print")

        # Navigate, including the print-pdf query so Reveal sets itself up as for PDF
        url = "file://" + args.input + "?print-pdf"
        page.goto(url, wait_until="networkidle")

        # Wait until Reveal signals it’s ready
        page.locator(".reveal.ready").wait_for()

        print()
        print("▶  Your deck is now open in Chromium with print styles applied.")
        print("   Tweak your CSS or plugin live, then close the browser window when you’re done.")
        input("Press Enter here to exit this script…")

        browser.close()

if __name__ == "__main__":
    main()
