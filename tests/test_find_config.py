import sys
import subprocess
from pathlib import Path

import pytest

import mdfusion.mdfusion as mdfusion


def test_with_config(tmp_path, monkeypatch):
    # 1) Create a docs/ tree with two markdown files
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.md").write_text("# First\n\nHello")
    (docs / "b.md").write_text("# Second\n\nWorld")

    # 2) Write a .mdfusion config in the cwd
    cfg = tmp_path / "mdfusion.toml"
    cfg.write_text(
        f"""\
[mdfusion]
root_dir = "{docs.as_posix()}"
output = "my-book.pdf"
toc = false
title_page = true
title = "Config Title"
author = "Config Author"
pandoc_args = "--number-sections"
"""
    )
    
    monkeypatch.chdir(tmp_path)
    
    mdfusion.run(mdfusion.RunParams(
        config_path=cfg,
    ))
    
    assert (tmp_path / "my-book.pdf").exists()
    
