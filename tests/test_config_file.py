import sys
import subprocess
from pathlib import Path

import pytest

import mdfusion.mdfusion as mdfusion


def test_with_config(tmp_path, monkeypatch, capsys):
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
pandoc_args ="--number-sections"
"""
    )

    # 3) chdir into tmp_path so script sees ./​.mdfusion
    monkeypatch.chdir(tmp_path)

    # 4) Stub out mdfusion.run_pandoc_with_spinner to capture the cmd
    captured = {}

    def fake_spinner(cmd, out_pdf):
        captured["cmd"] = cmd
        print(f"Merged PDF written to {out_pdf}")

    # call with no args => pick up config
    monkeypatch.setattr(mdfusion, "run_pandoc_with_spinner", fake_spinner)
    mdfusion.main()

    # 6) Check printed output
    out = capsys.readouterr().out
    assert "Merged PDF written to my-book.pdf" in out

    cmd = captured.get("cmd", [])
    # Should start with pandoc and merged.md → my-book.pdf
    assert cmd[0] == "pandoc"
    assert "-o" in cmd and "my-book.pdf" in cmd

    # toc=false means --toc must NOT appear
    assert "--toc" not in cmd

    print(cmd, file=sys.stderr)

    # title_page=true doesn't affect flags here, but pandoc_args does:
    assert "--number-sections" in cmd

    # Always include the header injection
    assert any(arg.startswith("--include-in-header=") for arg in cmd)
    # And resource-path pointing at our two files
    assert any("merged.md" in arg or str(docs) in arg for arg in cmd)
