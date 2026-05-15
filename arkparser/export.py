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

from arkparser.common.map_config import MapConfig
from arkparser.files import Profile, Tribe
from arkparser.models.creature import TamedCreature, WildCreature
from arkparser.models.player import Player
from arkparser.models.stats import Location
from arkparser.models.structure import Structure
from arkparser.models.tribe import Tribe as TribeModel

ExportNaming = t.Literal["native", "asv"]

_EXPORT_NAME_MAPS: dict[ExportNaming, dict[str, str]] = {
    "native": {
        "tamed": "tamed",
        "wild": "wild",
        "players": "players",
        "tribes": "tribes",
        "structures": "structures",
        "tribe_logs": "tribe_logs",
        "map_structures": "map_structures",
    },
    "asv": {
        "tamed": "ASV_Tamed",
        "wild": "ASV_Wild",
        "players": "ASV_Players",
        "tribes": "ASV_Tribes",
        "structures": "ASV_Structures",
        "tribe_logs": "ASV_TribeLogs",
        "map_structures": "ASV_MapStructures",
    },
}


def _apply_map(loc: Location | None, map_config: MapConfig | None) -> Location | None:
    """Attach map config to a location for GPS conversion."""
    if loc and map_config:
        return loc.with_map(map_config)
    return loc


def _get_export_name_map(naming: ExportNaming) -> dict[str, str]:
    """Return the aggregate export names for the requested naming mode."""
    # Purpose: Resolve the public aggregate export names for a supported naming mode.
    # Preconditions: ``naming`` must be one of the supported literal values.
    # Postconditions: Returns the canonical name mapping for the requested mode.
    # Side effects: Reads the module-level export name registry.
    # Failure modes: Raises ValueError when ``naming`` is unsupported.
    name_map = _EXPORT_NAME_MAPS.get(naming)
    if name_map is None:
        raise ValueError(f"Unsupported export naming mode: {naming!r}")
    return name_map


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
        save: A parsed savegame (WorldSave, which auto-detects ASE/ASA).
        map_config: Optional map config for GPS coordinates.

    Returns:
        List of tamed creature dictionaries.
    """
    results: list[dict[str, t.Any]] = []

    tamed_objs = _get_worldsave_objects(save, "get_tamed_creatures", "tamed_objects")
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

    wild_objs = _get_worldsave_objects(save, "get_wild_creatures", "wild_objects")
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

    profiles = _get_collection(save, "profiles", Profile)

    for profile in profiles:
        if isinstance(profile, Profile):
            results.append(_export_profile_parser(profile))
            continue

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

    tribes = _get_collection(save, "tribes", Tribe)

    for tribe_parser in tribes:
        if isinstance(tribe_parser, Tribe):
            results.append(_export_tribe_parser(tribe_parser))
            continue

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

    struct_objs = _get_worldsave_objects(save, "get_structures", "structure_objects")

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

    tribes = _get_collection(save, "tribes", Tribe)

    for tribe_parser in tribes:
        if isinstance(tribe_parser, Tribe):
            results.append(
                {
                    "tribeid": tribe_parser.tribe_id or 0,
                    "tribe": tribe_parser.name or "",
                    "logs": list(tribe_parser.log_entries),
                }
            )
            continue

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
# Map Structures (ASV_MapStructures): structures with GPS coords
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
# Full Export: all 7 formats at once
# -------------------------------------------------------------------------


def export_all(
    save: t.Any,
    map_config: MapConfig | None = None,
    naming: ExportNaming = "native",
) -> dict[str, list[dict[str, t.Any]]]:
    """
    Export all 7 formats at once.

    Args:
        save: A parsed savegame.
        map_config: Optional map config for GPS coordinates.
        naming: Aggregate naming mode for returned keys.

    Returns:
        Dictionary keyed by the requested aggregate naming mode.
    """
    # Purpose: Export every supported data slice using one consistent aggregate naming mode.
    # Preconditions: ``save`` exposes the parser collections consumed by the export helpers.
    # Postconditions: Returns a dictionary containing all seven export payloads.
    # Side effects: Reads parsed save data and any nested collections referenced by the helpers.
    # Failure modes: Propagates export helper errors and raises ValueError for unsupported naming.
    name_map = _get_export_name_map(naming)
    return {
        name_map["tamed"]: export_tamed(save, map_config),
        name_map["wild"]: export_wild(save, map_config),
        name_map["players"]: export_players(save, map_config),
        name_map["tribes"]: export_tribes(save),
        name_map["structures"]: export_structures(save, map_config),
        name_map["tribe_logs"]: export_tribe_logs(save),
        name_map["map_structures"]: export_map_structures(save, map_config),
    }


def export_to_files(
    save: t.Any,
    output_dir: str | Path,
    map_config: MapConfig | None = None,
    naming: ExportNaming = "native",
) -> list[Path]:
    """
    Export all 7 formats to JSON files.

    Args:
        save: A parsed savegame.
        output_dir: Directory to write JSON files to.
        map_config: Optional map config for GPS coordinates.
        naming: Aggregate naming mode for file names.

    Returns:
        List of paths to the created files.
    """
    # Purpose: Serialize every supported export payload to JSON files in one directory.
    # Preconditions: ``output_dir`` is writable and ``save`` supports the export helpers.
    # Postconditions: Creates one JSON file per aggregate export payload and returns their paths.
    # Side effects: Creates directories and writes JSON files to disk.
    # Failure modes: Propagates filesystem errors, export helper errors, and ValueError for unsupported naming.
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    all_data = export_all(save, map_config, naming=naming)
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
    values = list(objects.values()) if isinstance(objects, dict) else list(objects) if isinstance(objects, list) else []
    result: dict[t.Any, t.Any] = {}

    for obj in values:
        obj_id = getattr(obj, "id", None)
        guid = getattr(obj, "guid", None)
        names = getattr(obj, "names", None) or []

        if obj_id is not None:
            result[obj_id] = obj
        if guid:
            result[guid] = obj
        for name in names:
            result[name] = obj

    return result


def _get_collection(source: t.Any, attr_name: str, parser_type: type[t.Any]) -> list[t.Any]:
    """Normalize a parser collection or single parser instance to a list."""
    if isinstance(source, parser_type):
        return [source]

    values = getattr(source, attr_name, None)
    if isinstance(values, (list, tuple)):
        return list(values)
    if values is None:
        return []
    return [values]


def _get_worldsave_objects(save: t.Any, getter_name: str, legacy_attr: str) -> list[t.Any]:
    """Get world-save object collections from modern or legacy APIs."""
    getter = getattr(save, getter_name, None)
    if callable(getter):
        return list(getter())

    values = getattr(save, legacy_attr, None)
    if isinstance(values, list):
        return values
    return []


def _resolve_reference(ref: t.Any, lookup: dict[t.Any, t.Any]) -> t.Any:
    """Resolve an object reference stored as an ID, GUID, or name."""
    if ref is None:
        return None
    return lookup.get(ref)


def _export_profile_parser(profile: Profile) -> dict[str, t.Any]:
    """Export a parsed `Profile` using its nested parser API."""
    stat_points = [int(profile.get_stat(i)["added"]) for i in range(12)]
    stats = {
        "health": stat_points[0],
        "stamina": stat_points[1],
        "torpidity": stat_points[2],
        "oxygen": stat_points[3],
        "food": stat_points[4],
        "water": stat_points[5],
        "temperature": stat_points[6],
        "weight": stat_points[7],
        "melee": stat_points[8],
        "speed": stat_points[9],
        "fortitude": stat_points[10],
        "crafting": stat_points[11],
    }
    steam_id = profile.unique_id or ""

    result: dict[str, t.Any] = {
        "playerid": profile.player_id or 0,
        "steam": "",
        "name": profile.player_name or "",
        "tribeid": profile.tribe_id or 0,
        "tribe": profile.tribe_name or "",
        "sex": "",
        "lvl": profile.level,
        "hp": stats["health"],
        "stam": stats["stamina"],
        "melee": stats["melee"],
        "weight": stats["weight"],
        "speed": stats["speed"],
        "food": stats["food"],
        "water": stats["water"],
        "oxy": stats["oxygen"],
        "craft": stats["crafting"],
        "fort": stats["fortitude"],
        "stats": stats,
        "engram_points": profile.total_engram_points,
        "experience": profile.experience,
    }
    if steam_id:
        result["steamid"] = steam_id
        result["dataFile"] = f"{steam_id}.arkprofile"
    return result


def _export_tribe_parser(tribe: Tribe) -> dict[str, t.Any]:
    """Export a parsed `Tribe` using its nested parser API."""
    return {
        "tribeid": tribe.tribe_id or 0,
        "tribe": tribe.name or "",
        "players": tribe.member_count,
        "members": tribe.get_members(),
        "owner_id": tribe.owner_player_id or 0,
        "owner_name": "",
        "alliance_ids": tribe.alliance_ids,
        "logs": tribe.log_entries,
    }


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

    return _resolve_reference(ref, lookup)


def _get_inventory_items(obj: t.Any, lookup: dict[t.Any, t.Any]) -> list[dict[str, t.Any]]:
    """Get inventory items for a creature."""
    items: list[dict[str, t.Any]] = []

    inv_ref = None
    if hasattr(obj, "get_property_value"):
        inv_ref = obj.get_property_value("MyInventoryComponent", default=None)

    inv_obj = _resolve_reference(inv_ref, lookup)

    if inv_obj is None:
        return items

    # Get item references from inventory
    item_refs = None
    if hasattr(inv_obj, "get_property_value"):
        item_refs = inv_obj.get_property_value("InventoryItems", default=None)

    if not isinstance(item_refs, list):
        return items

    for ref in item_refs:
        item_obj = _resolve_reference(ref, lookup)
        if item_obj is None:
            continue

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
