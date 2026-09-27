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
    the default list, while tables merge recursively. A custom phrase drops
    inherited variations unless its override explicitly supplies them. Timing
    groups are complete mappings tied to a phrase, never partially inherited.
    """
    config = tomllib.loads(files("awaitonal").joinpath("palette.toml").read_text())
    if path is not None:
        with Path(path).expanduser().open("rb") as stream:
            overrides = tomllib.load(stream)
        # Authored variations belong to the phrase they accompany. Replacing a
        # custom phrase must not intermittently play the packaged melody instead.
        states = overrides.get("states", {})
        if isinstance(states, dict):
            for state in ("answer", "done"):
                patch = states.get(state)
                if not isinstance(patch, dict):
                    continue
                phrase_changed = bool({"events", "duration", "long_turn"}.intersection(patch))
                if "variations" not in patch and phrase_changed:
                    config["states"][state].pop("variations", None)
                if phrase_changed or "variations" in patch or "variation_groups" in patch:
                    # Full replacement also rejects accidentally partial groups;
                    # custom notes cannot silently inherit the stock semantics.
                    config["states"][state].pop("variation_groups", None)
        _merge(config, overrides)
    return config
