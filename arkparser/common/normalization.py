"""Helpers for normalizing parser output shapes.

The parser preserves indexed-property information by serializing repeated or
non-zero-index properties as dictionaries keyed by their property indices.
These helpers convert those internal shapes back into more convenient Python
values for higher-level APIs.
"""

from __future__ import annotations

import typing as t


def normalize_indexed_data(value: t.Any) -> t.Any:
    """Recursively unwrap indexed-property dictionaries.

    Rules:
    - Plain lists are normalized element-by-element.
    - Dicts with only integer keys are treated as indexed-property wrappers.
      Their values are preserved in insertion order, recursively normalized,
      and collapsed to a single value when only one indexed entry exists.
    - Other dicts are normalized value-by-value while keeping their keys.
    """
    if isinstance(value, list):
        return [normalize_indexed_data(item) for item in value]

    if not isinstance(value, dict):
        return value

    normalized_items = [(key, normalize_indexed_data(item)) for key, item in value.items()]
    if normalized_items and all(isinstance(key, int) for key, _ in normalized_items):
        normalized_values = [item for _, item in normalized_items]
        return normalized_values[0] if len(normalized_values) == 1 else normalized_values

    return {key: item for key, item in normalized_items}


def normalize_indexed_list(value: t.Any) -> list[t.Any]:
    """Normalize a possibly indexed value into a list."""
    normalized = normalize_indexed_data(value)
    if normalized is None:
        return []
    if isinstance(normalized, list):
        return normalized
    return [normalized]
