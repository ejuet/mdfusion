from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from mdfusion import config_utils


@config_utils.config_dataclass("inner")
class _Inner:
    value: int | None = None


@config_utils.config_dataclass("root")
class _Root:
    inner: _Inner = field(default_factory=_Inner)
    name: str | None = None
    path: Path | None = None
    items: list[str] = field(default_factory=list)


def test_discover_config_path_cli_flag(tmp_path):
    cfg = tmp_path / "cfg.toml"
    cfg.write_text("[root]\nname = 'x'\n")
    argv = ["prog", "-c", str(cfg)]

    found = config_utils.discover_config_path(argv, cwd=tmp_path)

    assert found == cfg


def test_discover_config_path_default(tmp_path):
    cfg = tmp_path / "mdfusion.toml"
    cfg.write_text("[root]\nname = 'x'\n")

    found = config_utils.discover_config_path([], cwd=tmp_path)

    assert found == cfg


def test_load_config_defaults_for_nested(tmp_path):
    cfg = tmp_path / "mdfusion.toml"
    cfg.write_text(
        """\
[root]
name = "Config Name"
path = "docs"
items = ["a"]

[inner]
value = 42
"""
    )

    params = config_utils.load_config_defaults_for(cfg, root_cls=_Root)

    assert params.name == "Config Name"
    assert params.path == Path("docs")
    assert params.items == ["a"]
    assert params.inner.value == 42


def test_merge_cli_args_with_config_for_lists(tmp_path):
    cfg = tmp_path / "mdfusion.toml"
    cfg.write_text(
        """\
[root]
items = ["a"]
"""
    )
    cli = _Root(items=["b"])

    merged = config_utils.merge_cli_args_with_config_for(
        cli, cfg, root_cls=_Root
    )

    assert merged.items == ["a", "b"]


def test_load_config_defaults_for_unknown_section(tmp_path):
    cfg = tmp_path / "mdfusion.toml"
    cfg.write_text(
        """\
[root]
name = "ok"

[unknown]
value = "nope"
"""
    )

    with pytest.raises(ValueError, match=r"Unknown config section"):
        config_utils.load_config_defaults_for(cfg, root_cls=_Root)
