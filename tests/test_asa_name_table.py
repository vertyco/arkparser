"""Regression test for KNOWN_ISSUES #1: ASA ``__UNKNOWN_CLASS_`` name-table leak.

Root cause: arkparser read the ASA worldsave name table sequentially after the
data-files section instead of seeking to the v14 header's name-table offset
(``actual_offset``). On maps where the sequential cursor landed short of that
offset (ragnarok, scorchedearth) the table was truncated and ~half the class
references resolved to ``__UNKNOWN_CLASS_<hash>__``. Fix: seek to
``actual_offset`` on v14+ (mirrors C# ``AsaSavegame.readNametable``).

Fixture-gated: uses real saves under
``references/local_saves/survival_ascended/`` which are not committed; skips
when absent (same convention as ``conftest`` example fixtures).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from arkparser import WorldSave

SAVES = (
    Path(__file__).resolve().parent.parent
    / "references"
    / "local_saves"
    / "survival_ascended"
)


def _ark_or_skip(map_name: str) -> Path:
    d = SAVES / map_name
    arks = sorted(d.glob("*_WP.ark")) if d.exists() else []
    if not arks:
        pytest.skip(f"Fixture not available: {d}\\*_WP.ark")
    return arks[0]


@pytest.mark.parametrize("map_name", ["scorchedearth_wp", "ragnarok_wp"])
def test_asa_name_table_no_unknown_class(map_name: str) -> None:
    """Every parsed object resolves to a real class name (no name-table drift)."""
    save = WorldSave.load(_ark_or_skip(map_name))
    unknown = [
        o.class_name
        for o in save.objects
        if str(getattr(o, "class_name", "") or "").startswith("__UNKNOWN_CLASS_")
    ]
    assert not unknown, (
        f"{map_name}: {len(unknown)} objects leaked __UNKNOWN_CLASS_ "
        f"(e.g. {unknown[:3]})"
    )
