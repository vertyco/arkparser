"""Tests for cloud-inventory export functions + inventory item stats."""

from __future__ import annotations

from pathlib import Path

from arkparser import (
    CloudInventory,
    export_cloud_inventory,
    export_cluster_items,
)
from arkparser.export import (
    _apply_stat_aliases,
    _combine_item_id,
    _expand_stat_slots,
    _pascal_to_snake,
    _uploaded_item_dict,
)

# Top-level inventory-entry keys that intentionally keep legacy (camelCase)
# casing for ASV schema parity; everything else is snake_case.
_LEGACY_CAMEL_KEYS = {"itemId"}


def test_pascal_to_snake_basic() -> None:
    assert _pascal_to_snake("ItemStatValues") == "item_stat_values"
    assert _pascal_to_snake("CrafterCharacterName") == "crafter_character_name"
    assert _pascal_to_snake("bIsBlueprint") == "b_is_blueprint"
    assert _pascal_to_snake("ItemID") == "item_id"


def test_expand_stat_slots_dict_and_list_agree() -> None:
    # Sparse dict (GameObject inventory path) and dense list (cloud path) must
    # produce identical named slots. Regression: the list shape was dropped
    # entirely because only dict was handled.
    sparse = {1: 6378, 2: 7106, 5: 11736, 7: 12857}
    dense = [0, 6378, 7106, 0, 0, 11736, 0, 12857]
    expected = {
        "armor": 6378,
        "durability_max": 7106,
        "hypo": 11736,
        "hyper": 12857,
    }
    assert _expand_stat_slots(sparse) == expected
    assert _expand_stat_slots(dense) == expected


def test_expand_stat_slots_single_slot_dict() -> None:
    # A single populated slot must keep its index (regression: collapsed to a
    # bare scalar upstream, which dropped the stat entirely).
    assert _expand_stat_slots({2: 2624}) == {"durability_max": 2624}
    # A bare scalar has no recoverable index -> ignored, no crash.
    assert _expand_stat_slots(2624) == {}
    assert _expand_stat_slots(None) == {}


def test_apply_stat_aliases_emits_slots_for_list_input() -> None:
    out = _apply_stat_aliases({"item_stat_values": [0, 6378, 7106, 0, 0, 0, 0, 0]})
    assert out["armor"] == 6378
    assert out["durability_max"] == 7106


def test_combine_item_id_keeps_legit_zero() -> None:
    # Falsy-zero trap: ItemID1 == 0 must not be replaced by an _0 variant key.
    assert _combine_item_id({"ItemID1": 0, "ItemID1_0": 77, "ItemID2": 5}) == "0_5"
    assert _combine_item_id({"ItemID1": 12, "ItemID2": 34}) == "12_34"
    # Non-numeric / corrupt components return None instead of raising.
    assert _combine_item_id({"ItemID1": "NaN", "ItemID2": 5}) is None
    assert _combine_item_id("not-a-dict") is None


def test_export_cloud_inventory_shape(ase_obelisk_path: Path) -> None:
    cloud = CloudInventory.load(ase_obelisk_path)
    out = export_cloud_inventory(cloud)
    assert set(out.keys()) == {"ASV_Tamed", "ASV_Items"}
    assert isinstance(out["ASV_Tamed"], list)
    assert isinstance(out["ASV_Items"], list)


def test_cloud_items_have_flat_stats(ase_obelisk_path: Path) -> None:
    cloud = CloudInventory.load(ase_obelisk_path)
    items = export_cluster_items([cloud])
    assert items, "ASE obelisk fixture has uploaded items"
    item = items[0]
    assert "itemId" in item
    assert "qty" in item
    # Stat keys are snake_case; only the legacy top-level keys keep camelCase.
    assert all(
        k == k.lower() or k in _LEGACY_CAMEL_KEYS for k in item
    ), f"unexpected non-snake_case key in {sorted(item)}"


def test_uploaded_item_dict_no_skipped_keys(ase_obelisk_path: Path) -> None:
    cloud = CloudInventory.load(ase_obelisk_path)
    item = cloud.uploaded_items[0]
    entry = _uploaded_item_dict(item)
    for skip in ("ItemQuantity", "bIsBlueprint", "CustomItemDatas"):
        assert _pascal_to_snake(skip) not in entry
