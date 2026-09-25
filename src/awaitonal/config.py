"""One editable TOML instrument, with optional partial user overrides."""

from __future__ import annotations

from copy import deepcopy
from importlib.resources import files
from pathlib import Path
import tomllib


def _merge(base: dict, overrides: dict) -> dict:
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = deepcopy(value)
    return base


def load_config(path: str | Path | None = None) -> dict:
    """Load the packaged palette; a supplied TOML file overrides its fields.

    Each call returns fresh data. Lists (including a state's events) replace
    the default list, while tables merge recursively.
    """
    config = tomllib.loads(files("awaitonal").joinpath("palette.toml").read_text())
    if path is not None:
        with Path(path).expanduser().open("rb") as stream:
            _merge(config, tomllib.load(stream))
    return config
