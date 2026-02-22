"""
Export functions for producing C#-compatible JSON outputs.

Generates the 7 ASV export formats from parsed save data:
- ASV_Tamed: Tamed creature list
- ASV_Wild: Wild creature list
- ASV_Players: Player profiles
- ASV_Tribes: Tribe data
- ASV_Structures: Placed structures
- ASV_TribeLogs: Tribe log entries
- ASV_MapStructures: All structures with map coordinates

Each function accepts a parsed savegame (ASE or ASA) plus optional
map config and returns a list of dictionaries ready for JSON serialization.
"""

from __future__ import annotations

import json
import typing as t
from pathlib import Path

from arkparser.common.map_config import MapConfig, get_map_config
from arkparser.models.creature import TamedCreature, WildCreature
from arkparser.models.player import Player
from arkparser.models.stats import Location
from arkparser.models.structure import Structure
from arkparser.models.tribe import Tribe as TribeModel


def _apply_map(loc: Location | None, map_config: MapConfig | None) -> Location | None:
    """Attach map config to a location for GPS conversion."""
    if loc and map_config:
        return loc.with_map(map_config)
    return loc


# -------------------------------------------------------------------------
# Tamed Creatures (ASV_Tamed)
# -------------------------------------------------------------------------


def export_tamed(
    save: t.Any,
    map_config: MapConfig | None = None,
) -> list[dict[str, t.Any]]:
    """
    Export tamed creatures in ASV_Tamed format.

    Args:
        save: A parsed savegame (WorldSave — auto-detects ASE/ASA).
        map_config: Optional map config for GPS coordinates.

    Returns:
        List of tamed creature dictionaries.
    """
    results: list[dict[str, t.Any]] = []

    tamed_objs = save.tamed_objects if hasattr(save, "tamed_objects") else []
    objects = save.objects if hasattr(save, "objects") else {}
    obj_lookup = _build_lookup(objects)

    for obj in tamed_objs:
        status = _find_status_component(obj, obj_lookup)
        creature = TamedCreature.from_game_object(obj, status)
        data = creature.to_dict()

        if creature.location and map_config:
            mapped_loc = creature.location.with_map(map_config)
            if mapped_loc.latitude is not None:
                data["lat"] = mapped_loc.latitude
            if mapped_loc.longitude is not None:
                data["lon"] = mapped_loc.longitude

        inventory = _get_inventory_items(obj, obj_lookup)
        data["inventory"] = inventory

        results.append(data)

    return results


# -------------------------------------------------------------------------
# Wild Creatures (ASV_Wild)
# -------------------------------------------------------------------------


def export_wild(
    save: t.Any,
    map_config: MapConfig | None = None,
) -> list[dict[str, t.Any]]:
    """
    Export wild creatures in ASV_Wild format.

    Args:
        save: A parsed savegame.
        map_config: Optional map config for GPS coordinates.

    Returns:
        List of wild creature dictionaries.
    """
    results: list[dict[str, t.Any]] = []

    wild_objs = save.wild_objects if hasattr(save, "wild_objects") else []
    objects = save.objects if hasattr(save, "objects") else {}
    obj_lookup = _build_lookup(objects)

    for obj in wild_objs:
        status = _find_status_component(obj, obj_lookup)
        creature = WildCreature.from_game_object(obj, status)
        data = creature.to_dict()

        if creature.location and map_config:
            mapped_loc = creature.location.with_map(map_config)
            if mapped_loc.latitude is not None:
                data["lat"] = mapped_loc.latitude
            if mapped_loc.longitude is not None:
                data["lon"] = mapped_loc.longitude

        results.append(data)

    return results


# -------------------------------------------------------------------------
# Players (ASV_Players)
# -------------------------------------------------------------------------


def export_players(
    save: t.Any,
    map_config: MapConfig | None = None,
) -> list[dict[str, t.Any]]:
    """
    Export player profiles in ASV_Players format.

    Args:
        save: A parsed savegame with profile data.
        map_config: Optional map config for GPS coordinates.

    Returns:
        List of player dictionaries.
    """
    results: list[dict[str, t.Any]] = []

    profiles = save.profiles if hasattr(save, "profiles") else []

    for profile in profiles:
        profile_obj = None
        status_obj = None

        if hasattr(profile, "profile"):
            profile_obj = profile.profile
        elif hasattr(profile, "objects") and profile.objects:
            profile_obj = profile.objects[0]

        if hasattr(profile, "objects"):
            for obj in profile.objects:
                cs = str(getattr(obj, "class_name", ""))
                if "StatusComponent" in cs or "CharacterStatus" in cs:
                    status_obj = obj
                    break

        if profile_obj is None:
            continue

        player = Player.from_game_object(profile_obj, status_obj)
        data = player.to_dict()
        results.append(data)

    return results


# -------------------------------------------------------------------------
# Tribes (ASV_Tribes)
# -------------------------------------------------------------------------


def export_tribes(
    save: t.Any,
) -> list[dict[str, t.Any]]:
    """
    Export tribe data in ASV_Tribes format.

    Args:
        save: A parsed savegame with tribe data.

    Returns:
        List of tribe dictionaries.
    """
    results: list[dict[str, t.Any]] = []

    tribes = save.tribes if hasattr(save, "tribes") else []

    for tribe_parser in tribes:
        tribe_obj = None
        if hasattr(tribe_parser, "tribe"):
            tribe_obj = tribe_parser.tribe
        elif hasattr(tribe_parser, "objects") and tribe_parser.objects:
            tribe_obj = tribe_parser.objects[0]

        if tribe_obj is None:
            continue

        tribe_model = TribeModel.from_game_object(tribe_obj)
        data = tribe_model.to_dict()
        results.append(data)

    return results


# -------------------------------------------------------------------------
# Structures (ASV_Structures)
# -------------------------------------------------------------------------


def export_structures(
    save: t.Any,
    map_config: MapConfig | None = None,
) -> list[dict[str, t.Any]]:
    """
    Export placed structures in ASV_Structures format.

    Args:
        save: A parsed savegame.
        map_config: Optional map config for GPS coordinates.

    Returns:
        List of structure dictionaries.
    """
    results: list[dict[str, t.Any]] = []

    struct_objs = save.structure_objects if hasattr(save, "structure_objects") else []

    for obj in struct_objs:
        structure = Structure.from_game_object(obj)
        data = structure.to_dict()

        if structure.location and map_config:
            mapped_loc = structure.location.with_map(map_config)
            if mapped_loc.latitude is not None:
                data["lat"] = mapped_loc.latitude
            if mapped_loc.longitude is not None:
                data["lon"] = mapped_loc.longitude

        results.append(data)

    return results


# -------------------------------------------------------------------------
# Tribe Logs (ASV_TribeLogs)
# -------------------------------------------------------------------------


def export_tribe_logs(
    save: t.Any,
) -> list[dict[str, t.Any]]:
    """
    Export tribe log entries in ASV_TribeLogs format.

    Args:
        save: A parsed savegame with tribe data.

    Returns:
        List of tribe log dictionaries (one per tribe).
    """
    results: list[dict[str, t.Any]] = []

    tribes = save.tribes if hasattr(save, "tribes") else []

    for tribe_parser in tribes:
        tribe_obj = None
        if hasattr(tribe_parser, "tribe"):
            tribe_obj = tribe_parser.tribe
        elif hasattr(tribe_parser, "objects") and tribe_parser.objects:
            tribe_obj = tribe_parser.objects[0]

        if tribe_obj is None:
            continue

        tribe_model = TribeModel.from_game_object(tribe_obj)
        results.append(
            {
                "tribeid": tribe_model.tribe_id,
                "tribe": tribe_model.name,
                "logs": [entry.to_dict() for entry in tribe_model.log],
            }
        )

    return results


# -------------------------------------------------------------------------
# Map Structures (ASV_MapStructures) — structures with GPS coords
# -------------------------------------------------------------------------


def export_map_structures(
    save: t.Any,
    map_config: MapConfig | None = None,
) -> list[dict[str, t.Any]]:
    """
    Export structures with map coordinates in ASV_MapStructures format.

    Same as ASV_Structures but intended for map visualisation with GPS coords.

    Args:
        save: A parsed savegame.
        map_config: Map config for GPS coordinate conversion.

    Returns:
        List of structure dictionaries with GPS coordinates.
    """
    return export_structures(save, map_config)


# -------------------------------------------------------------------------
# Full Export — all 7 formats at once
# -------------------------------------------------------------------------


def export_all(
    save: t.Any,
    map_config: MapConfig | None = None,
) -> dict[str, list[dict[str, t.Any]]]:
    """
    Export all 7 ASV formats at once.

    Args:
        save: A parsed savegame.
        map_config: Optional map config for GPS coordinates.

    Returns:
        Dictionary with keys ASV_Tamed, ASV_Wild, ASV_Players,
        ASV_Tribes, ASV_Structures, ASV_TribeLogs, ASV_MapStructures.
    """
    return {
        "ASV_Tamed": export_tamed(save, map_config),
        "ASV_Wild": export_wild(save, map_config),
        "ASV_Players": export_players(save, map_config),
        "ASV_Tribes": export_tribes(save),
        "ASV_Structures": export_structures(save, map_config),
        "ASV_TribeLogs": export_tribe_logs(save),
        "ASV_MapStructures": export_map_structures(save, map_config),
    }


def export_to_files(
    save: t.Any,
    output_dir: str | Path,
    map_config: MapConfig | None = None,
) -> list[Path]:
    """
    Export all 7 ASV formats to JSON files.

    Args:
        save: A parsed savegame.
        output_dir: Directory to write JSON files to.
        map_config: Optional map config for GPS coordinates.

    Returns:
        List of paths to the created files.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    all_data = export_all(save, map_config)
    created: list[Path] = []

    for name, data in all_data.items():
        path = out / f"{name}.json"
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        created.append(path)

    return created


# -------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------


def _build_lookup(objects: t.Any) -> dict[t.Any, t.Any]:
    """Build an object lookup dict from various container formats."""
    if isinstance(objects, dict):
        return objects
    if isinstance(objects, list):
        result: dict[t.Any, t.Any] = {}
        for obj in objects:
            key = getattr(obj, "guid", None) or id(obj)
            result[key] = obj
        return result
    return {}


def _find_status_component(obj: t.Any, lookup: dict[t.Any, t.Any]) -> t.Any:
    """
    Find the status component object for a creature.

    Looks for MyCharacterStatusComponent reference or component link.
    """
    # Check components dict
    if hasattr(obj, "components"):
        for key, comp in obj.components.items():
            if "status" in str(key).lower():
                return comp

    # Check property reference
    ref = None
    if hasattr(obj, "get_property_value"):
        ref = obj.get_property_value("MyCharacterStatusComponent", default=None)

    if ref is None:
        return None

    # Resolve reference
    guid = None
    if hasattr(ref, "guid") and ref.guid:
        guid = ref.guid
    elif hasattr(ref, "object_id") and ref.object_id >= 0:
        if isinstance(lookup, list):
            return lookup[ref.object_id] if ref.object_id < len(lookup) else None

    if guid and guid in lookup:
        return lookup[guid]

    return None


def _get_inventory_items(obj: t.Any, lookup: dict[t.Any, t.Any]) -> list[dict[str, t.Any]]:
    """Get inventory items for a creature."""
    items: list[dict[str, t.Any]] = []

    inv_ref = None
    if hasattr(obj, "get_property_value"):
        inv_ref = obj.get_property_value("MyInventoryComponent", default=None)

    if inv_ref is None:
        return items

    # Resolve inventory object
    inv_obj = None
    guid = None
    if hasattr(inv_ref, "guid") and inv_ref.guid:
        guid = inv_ref.guid

    if guid and guid in lookup:
        inv_obj = lookup[guid]

    if inv_obj is None:
        return items

    # Get item references from inventory
    item_refs = None
    if hasattr(inv_obj, "get_property_value"):
        item_refs = inv_obj.get_property_value("InventoryItems", default=None)

    if not isinstance(item_refs, list):
        return items

    for ref in item_refs:
        item_guid = None
        if hasattr(ref, "guid") and ref.guid:
            item_guid = ref.guid

        if item_guid and item_guid in lookup:
            item_obj = lookup[item_guid]
            item_class = str(getattr(item_obj, "class_name", ""))
            qty = 1
            is_bp = False
            if hasattr(item_obj, "get_property_value"):
                q = item_obj.get_property_value("ItemQuantity", default=1)
                qty = int(q) if q else 1
                is_bp = item_obj.get_property_value("bIsBlueprint", default=False)

            items.append(
                {
                    "itemId": item_class,
                    "qty": qty,
                    "blueprint": bool(is_bp),
                }
            )

    return items
