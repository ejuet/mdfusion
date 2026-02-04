
from pathlib import Path
import os
import mdfusion.mdfusion as mdfusion

def test_presentation():
    path_to_md = os.path.join(os.path.dirname(__file__), "my_presentation.md")
    output_pdf = os.path.splitext(path_to_md)[0] + ".html"
    css_path = os.path.join(os.path.dirname(__file__), "custom.css")

    params = mdfusion.RunParams(
        root_dir=Path(os.path.dirname(path_to_md)),
        output=output_pdf,
        title_page=False,
        title="Snails: The Ultimate Guide",
        author="From a loving snail fan",
        presentation=mdfusion.PresentationParams(
            presentation=True,
            footer_text="A fun presentation about snails",
        ),
        pandoc_args=["--slide-level", "6",
                    "--number-sections",
                    "-V", 'transition=fade',
                    # "-V", "theme=night",
                    # "-V", 'center=false',
                    "-c", css_path,
        ])
    mdfusion.run(params)