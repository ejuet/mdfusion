from pathlib import Path

import pytest

import mdfusion.mdfusion as mdfusion


def test_unknown_config_key_raises(tmp_path):
    cfg = tmp_path / "mdfusion.toml"
    cfg.write_text(
        """\
[mdfusion]
root_dir = "docs"
does_not_exist = true
"""
    )

    with pytest.raises(ValueError, match=r"Unknown config key"):
        mdfusion.load_config_defaults(cfg)
