"""Tests for cloud-inventory export functions + inventory item stats."""

from __future__ import annotations

from pathlib import Path

from arkparser import (
    CloudInventory,
    export_cloud_inventory,
    export_cluster_items,
)
from arkparser.export import _pascal_to_snake, _uploaded_item_dict


def test_pascal_to_snake_basic() -> None:
    assert _pascal_to_snake("ItemStatValues") == "item_stat_values"
    assert _pascal_to_snake("CrafterCharacterName") == "crafter_character_name"
    assert _pascal_to_snake("bIsBlueprint") == "b_is_blueprint"
    assert _pascal_to_snake("ItemID") == "item_id"


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
    assert all(k == k.lower() for k in item), "all keys snake_case-ish"


def test_uploaded_item_dict_no_skipped_keys(ase_obelisk_path: Path) -> None:
    cloud = CloudInventory.load(ase_obelisk_path)
    item = cloud.uploaded_items[0]
    entry = _uploaded_item_dict(item)
    for skip in ("ItemQuantity", "bIsBlueprint", "CustomItemDatas"):
        assert _pascal_to_snake(skip) not in entry
