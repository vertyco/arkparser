"""Unit tests for live CurrentStatusValues extraction.

ARK persists every character's instantaneous stat values on the status
component as ``CurrentStatusValues[0..11]``. ``_current_stats_dict`` reads
those entries (using either ``get_properties_by_name`` for objects that
expose it or per-index ``get_property_value`` lookups for synthetic /
cryopod objects) and returns ``{hp, stam, torp, oxy, food, water, temp,
weight, melee, speed, fort, craft}``.
"""

from __future__ import annotations

import typing as t
from dataclasses import dataclass

from arkparser.export import _current_stat_floats, _current_stats_dict

_STAT_ORDER = (
    "hp", "stam", "torp", "oxy", "food", "water",
    "temp", "weight", "melee", "speed", "fort", "craft",
)


@dataclass
class _IndexedProp:
    """Stand-in for an arkparser property with an array index."""

    name: str
    index: int
    value: float


class _FakeStatus:
    """Minimal stand-in for a character status component.

    Supports the ``get_properties_by_name`` interface used by
    ``_current_stat_floats``.
    """

    def __init__(self, current: list[tuple[int, float]]) -> None:
        self._props = [_IndexedProp("CurrentStatusValues", idx, val) for idx, val in current]

    def get_properties_by_name(self, name: str) -> list[_IndexedProp]:
        return [p for p in self._props if p.name == name]


class _PerIndexStatus:
    """Synthetic stand-in (matches ``_SyntheticGameObject`` interface).

    Stores values as ``CurrentStatusValues_{idx}`` keys, and
    ``get_property_value`` returns the indexed value.
    """

    def __init__(self, current: dict[int, float]) -> None:
        self._values = current

    def get_property_value(
        self,
        name: str,
        default: t.Any = None,
        index: int | None = None,
    ) -> t.Any:
        if name != "CurrentStatusValues":
            return default
        if index is None:
            return default
        return self._values.get(index, default)


def test_none_status_returns_none() -> None:
    assert _current_stat_floats(None) is None
    assert _current_stats_dict(None) is None


def test_empty_status_returns_none() -> None:
    """Status component carrying no CurrentStatusValues at all -> ``None``."""
    status = _FakeStatus(current=[])
    assert _current_stat_floats(status) is None
    assert _current_stats_dict(status) is None


def test_sparse_indices_fill_with_zeros() -> None:
    """Real saves only persist the stats that diverge from defaults; the
    rest get zero. Wyvern test: hp + stam + oxy set, the rest zero."""
    status = _FakeStatus(current=[
        (0, 25238.14),   # hp
        (1, 806.40),     # stam
        (3, 660.0),      # oxy
    ])
    result = _current_stats_dict(status)
    assert result is not None
    assert result["hp"] == 25238.14
    assert result["stam"] == 806.40
    assert result["oxy"] == 660.0
    assert result["torp"] == 0.0
    assert result["food"] == 0.0
    assert result["water"] == 0.0
    assert result["weight"] == 0.0
    assert result["melee"] == 0.0
    assert result["speed"] == 0.0
    assert result["temp"] == 0.0
    assert result["fort"] == 0.0
    assert result["craft"] == 0.0


def test_all_twelve_indices_round_trip() -> None:
    """Verify every stat slot maps to the correct name (catches off-by-one)."""
    status = _FakeStatus(current=[(i, float(i + 1) * 10) for i in range(12)])
    result = _current_stats_dict(status)
    assert result is not None
    for i, name in enumerate(_STAT_ORDER):
        assert result[name] == float(i + 1) * 10, f"slot {i} ({name}) mismatched"


def test_synthetic_object_uses_per_index_getter() -> None:
    """Cryopod-decoded creatures expose status via ``get_property_value``
    with an explicit ``index`` arg, not ``get_properties_by_name``."""
    status = _PerIndexStatus(current={0: 1000.0, 1: 500.0, 4: 3000.0})
    result = _current_stats_dict(status)
    assert result is not None
    assert result["hp"] == 1000.0
    assert result["stam"] == 500.0
    assert result["food"] == 3000.0
    assert result["torp"] == 0.0


def test_out_of_range_indices_are_ignored() -> None:
    """Defensive: stray index 12+ entries must not blow past the 12-slot array."""
    status = _FakeStatus(current=[(0, 100.0), (12, 999.0), (15, 999.0)])
    result = _current_stats_dict(status)
    assert result is not None
    assert result["hp"] == 100.0
    assert len(result) == 12
