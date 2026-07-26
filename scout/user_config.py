"""Validation helpers for small user-edited JSON configuration files."""

import json


def load_budget_overrides(path):
    """Return {captain: non-negative integer budget}; reject invalid shapes."""
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, dict):
        raise ValueError("expected a JSON object mapping captain names to budgets")

    budgets = {}
    for name, value in raw.items():
        if isinstance(value, bool):
            raise ValueError(f"budget for {name!r} must be an integer")
        try:
            budget = int(value)
        except (TypeError, ValueError) as e:
            raise ValueError(f"budget for {name!r} must be an integer") from e
        if budget < 0:
            raise ValueError(f"budget for {name!r} cannot be negative")
        budgets[str(name)] = budget
    return budgets


def load_target_sets(path):
    """Return {captain: {steam32, ...}}; reject invalid shapes and values."""
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, dict):
        raise ValueError("expected a JSON object mapping captains to player lists")

    targets = {}
    for captain, values in raw.items():
        if not isinstance(values, (list, tuple, set)):
            raise ValueError(f"targets for {captain!r} must be a list")
        parsed = set()
        for value in values:
            if isinstance(value, bool):
                raise ValueError(f"target {value!r} for {captain!r} is not a Steam ID")
            try:
                parsed.add(int(value))
            except (TypeError, ValueError) as e:
                raise ValueError(
                    f"target {value!r} for {captain!r} is not a Steam ID"
                ) from e
        targets[str(captain)] = parsed
    return targets
