"""Regression test for KNOWN_ISSUES #2: ASE cloud/cluster cursor drift.

Root cause: ASE struct arrays of native fixed-size structs addressed only by
name (e.g. ``CustomItemColors`` = ``Color[]``) were read as property-list
structs because the array name was not in ``ARRAY_NAME_TO_STRUCT_TYPE``. That
mis-read drifted the cursor and a later property-name length read exploded with
``EndOfDataError``, so the whole cluster file (and all its uploads) was dropped.

Fix: ``_read_array_elements`` now infers the native element type from the array
body size when the name is unmapped (mirrors legacy ``ArkArrayStruct.Init``:
``count*4+4 == data_size`` -> Color, ``*12`` -> Vector, ``*16`` -> LinearColor).

Fixture-gated: uses real cluster files under
``references/local_saves/ase_cluster_drift/`` (not committed - they hold player
upload data); skips when absent.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from arkparser import CloudInventory

DRIFT_DIR = (
    Path(__file__).resolve().parent.parent
    / "references"
    / "local_saves"
    / "ase_cluster_drift"
)

# (filename, minimum uploaded-item count) for files that used to raise
# EndOfDataError mid-parse on the CustomItemColors native-struct array.
CASES = [
    ("2533274829298794", 50),
    ("2533274854487560", 9),
    ("2533274905839355", 3),
]


@pytest.mark.parametrize(("name", "min_items"), CASES)
def test_ase_cluster_native_struct_array_no_drift(name: str, min_items: int) -> None:
    """Previously-drifting cluster files parse fully and recover their uploads."""
    p = DRIFT_DIR / name
    if not p.exists():
        pytest.skip(f"Fixture not available: {p}")
    inv = CloudInventory.load(p)  # used to raise EndOfDataError mid-parse
    assert inv.item_count >= min_items, (
        f"{name}: expected >= {min_items} items, got {inv.item_count}"
    )
