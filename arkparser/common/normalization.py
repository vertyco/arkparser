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
    # Scalars are by far the most common input. Inline the recursion's leaf
    # case at every call site below (``x if not container else recurse``) so a
    # scalar element costs one ``isinstance`` instead of a full recursive call;
    # this function was the hottest frame in the export profile (~2.5M calls).
    if isinstance(value, list):
        return [
            item
            if not isinstance(item, (list, dict))
            else normalize_indexed_data(item)
            for item in value
        ]

    if not isinstance(value, dict):
        return value

    all_int = True
    out: dict[t.Any, t.Any] = {}
    for key, item in value.items():
        out[key] = (
            item
            if not isinstance(item, (list, dict))
            else normalize_indexed_data(item)
        )
        if all_int and not isinstance(key, int):
            all_int = False

    if not out or not all_int:
        return out

    # All-int-keyed dicts represent indexed-property entries. Collapse to a
    # flat list only when keys form contiguous 0..n; sparse indices must keep
    # dict shape so callers can look up by stat index, not list position.
    n = len(out)
    if min(out) == 0 and max(out) == n - 1:
        values = list(out.values())
        return values[0] if n == 1 else values
    return out


def normalize_indexed_list(value: t.Any) -> list[t.Any]:
    """Normalize a possibly indexed value into a list."""
    normalized = normalize_indexed_data(value)
    if normalized is None:
        return []
    if isinstance(normalized, list):
        return normalized
    # A raw ByteProperty array is stored as `bytes` for memory efficiency
    # (8x lighter than list[int]); expose it element-wise as a list of ints so
    # consumers that iterate it (e.g. tribe MembersRankGroups -> int(rank))
    # see the same shape they did before byte arrays were stored as bytes.
    if isinstance(normalized, (bytes, bytearray)):
        return list(normalized)
    return [normalized]
