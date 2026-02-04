from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from pathlib import Path
from typing import get_args, get_origin

import toml as tomllib  # type: ignore
from simple_parsing import ArgumentParser


@dataclass(frozen=True)
class _ConfigSection:
    name: str
    cls: type
    path: tuple[str, ...]


def _is_dataclass_type(tp) -> bool:
    return isinstance(tp, type) and is_dataclass(tp)


def _is_path_type(tp) -> bool:
    if tp is Path:
        return True
    origin = get_origin(tp)
    if origin is None:
        return False
    return Path in get_args(tp)


def _iter_config_sections(root_cls) -> list[_ConfigSection]:
    root_name = getattr(root_cls, "__config_section__", None)
    if not root_name:
        root_name = root_cls.__name__.lower()
    sections: list[_ConfigSection] = [_ConfigSection(root_name, root_cls, ())]

    def walk(cls, path: tuple[str, ...]) -> None:
        for f in fields(cls):
            if _is_dataclass_type(f.type):
                nested_cls = f.type
                section_name = getattr(nested_cls, "__config_section__", f.name)
                nested_path = path + (f.name,)
                sections.append(_ConfigSection(section_name, nested_cls, nested_path))
                walk(nested_cls, nested_path)

    walk(root_cls, ())
    return sections


def _get_section_obj(root, path: tuple[str, ...]):
    obj = root
    for attr in path:
        obj = getattr(obj, attr)
    return obj


def _section_field_map(section_cls) -> dict[str, type]:
    return {
        f.name: f.type
        for f in fields(section_cls)
        if not _is_dataclass_type(f.type)
    }


def _clear_dataclass_instance(obj) -> None:
    for f in fields(type(obj)):
        value = getattr(obj, f.name)
        if is_dataclass(value):
            _clear_dataclass_instance(value)
        else:
            setattr(obj, f.name, None)


def _make_unset_instance(cls):
    obj = cls()
    _clear_dataclass_instance(obj)
    return obj


def discover_config_path(
    argv: list[str] | None,
    *,
    flag_names: tuple[str, ...] = ("-c", "--config_path"),
    default_filename: str = "mdfusion.toml",
    cwd: Path | None = None,
) -> Path | None:
    args = argv if argv is not None else []
    cfg_path = None
    for i, a in enumerate(args):
        if a in flag_names and i + 1 < len(args):
            cfg_path = Path(args[i + 1])
            break
    if cfg_path is None:
        base = cwd if cwd is not None else Path.cwd()
        default_cfg = base / default_filename
        if default_cfg.is_file():
            cfg_path = default_cfg
    return cfg_path


def parse_known_args_for(
    root_cls,
    *,
    description: str | None = None,
    argv: list[str] | None = None,
    parser_factory=ArgumentParser,
):
    parser = parser_factory(description=description)
    parser.add_arguments(root_cls, dest="params")
    args, extra = parser.parse_known_args(argv)
    return args.params, extra


def load_config_defaults_for(cfg_path: Path | None, *, root_cls):
    """Load config defaults from TOML file, if present. Returns a dataclass instance."""
    params = _make_unset_instance(root_cls)
    sections = _iter_config_sections(root_cls)

    if cfg_path and cfg_path.is_file():
        with cfg_path.open("r", encoding="utf-8") as f:
            toml_data = tomllib.load(f)

        allowed_sections = {s.name for s in sections}
        unknown_sections = [k for k in toml_data.keys() if k not in allowed_sections]
        if unknown_sections:
            unknown_list = ", ".join(sorted(unknown_sections))
            raise ValueError(f"Unknown config section(s): {unknown_list}")

        unknown_keys: list[str] = []
        for section in sections:
            section_data = toml_data.get(section.name, {})
            if not section_data:
                continue
            field_map = _section_field_map(section.cls)
            extra = sorted(set(section_data.keys()) - set(field_map.keys()))
            if extra:
                unknown_keys.append(f"[{section.name}]: " + ", ".join(extra))
                continue
            target = _get_section_obj(params, section.path)
            for k, v in section_data.items():
                typ = field_map[k]
                if _is_path_type(typ) and v is not None:
                    setattr(target, k, Path(v))
                else:
                    setattr(target, k, v)

        if unknown_keys:
            raise ValueError("Unknown config key(s): " + "; ".join(unknown_keys))

    return params


def merge_cli_args_with_config_for(
    cli_args,
    config_path: Path | None,
    *,
    root_cls,
    normalize=None,
):
    """Merge CLI args with config defaults. CLI args take precedence. Arrays are merged."""
    config_params = load_config_defaults_for(config_path, root_cls=root_cls)
    if normalize is not None:
        normalize(config_params)
        normalize(cli_args)
    default_params = root_cls()

    def merge_section(cli_section, config_section, default_section) -> None:
        for f in fields(type(cli_section)):
            k = f.name
            current = getattr(cli_section, k, None)
            v = getattr(config_section, k, None)
            default = getattr(default_section, k, None)
            if is_dataclass(current):
                merge_section(current, v, default)
                continue
            # If the field is a list, merge arrays (config first, then CLI)
            if isinstance(v, list):
                if current is None or current == [] or current == default:
                    setattr(cli_section, k, v)
                else:
                    merged = v + [item for item in current if item not in v]
                    setattr(cli_section, k, merged)
            else:
                if v is not None and (current is None or current == "" or current == default):
                    setattr(cli_section, k, v)

    merge_section(cli_args, config_params, default_params)
    if normalize is not None:
        normalize(cli_args)
    return cli_args
