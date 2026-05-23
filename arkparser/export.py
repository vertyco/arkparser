"""
Legacy-parity JSON export for ARK save data.

Produces dicts matching the C# ``ASVExport.exe`` output schema for the seven
canonical exports:

- Tamed creatures (``ASV_Tamed``)
- Wild creatures (``ASV_Wild``)
- Players (``ASV_Players``)
- Tribes (``ASV_Tribes``)
- Structures (``ASV_Structures``)
- Tribe logs (``ASV_TribeLogs``)
- Map structures (``ASV_MapStructures``)

Each ``export_*`` function reads directly from ``GameObject`` (or the relevant
file parser) and returns a flat dict matching the legacy keys.

Parser-only fields (data the legacy exporter could not produce) are added
alongside the legacy keys with their own descriptive names (no namespace
prefix). The full per-export field list is documented in ``README.md``.

Performance:

- ``WorldSave``-level export functions share a single object-lookup dict
  built once per ``WorldSave`` via :func:`_save_lookup`. Subsequent calls in
  the same export run reuse it instead of rebuilding (key win on maps with
  50k+ objects).
- Status / inventory component pointers are resolved once per creature and
  reused across the export shape.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import typing as t
from pathlib import Path

from arkparser.common.map_config import MapConfig
from arkparser.common.normalization import normalize_indexed_data, normalize_indexed_list
from arkparser.data_models import CryopodCreature
from arkparser.files import CloudInventory, Profile, Tribe

_CRYOPOD_CLASS_PATTERNS: tuple[str, ...] = (
    "Cryopod", "SoulTrap", "Vivarium", "DinoBall",
)


def _is_cryopod_class(class_name: str) -> bool:
    return any(p in class_name for p in _CRYOPOD_CLASS_PATTERNS)


def _decode_inventory_cryopod(item_obj: t.Any) -> CryopodCreature | None:
    """Decode the dino blob embedded in an inventory-stored cryopod item.

    Cryopod items carry the serialized creature snapshot in ``CustomItemDatas``
    (byte-blob form on ASE, structured-dict form on ASA). Returns ``None`` for
    empty cryopods or unrecognized payloads. Mirrors the logic in
    :meth:`WorldSave.iter_cryopod_creatures` but operates on a single item
    object so we can decode cryopods discovered inside other containers
    (cryofridges, vaults, dedicated storage, etc.).
    """
    custom_datas_raw = item_obj.get_property_value("CustomItemDatas")
    if custom_datas_raw is None:
        return None
    custom_datas = normalize_indexed_list(custom_datas_raw)
    for entry in custom_datas:
        if not isinstance(entry, dict) or entry.get("CustomDataName") != "Dino":
            continue
        cryo_bytes_wrapper = normalize_indexed_data(entry.get("CustomDataBytes", {}))
        if isinstance(cryo_bytes_wrapper, dict):
            byte_arrays = normalize_indexed_list(cryo_bytes_wrapper.get("ByteArrays"))
            if byte_arrays and isinstance(byte_arrays[0], dict) and "Bytes" in byte_arrays[0]:
                cryo = CryopodCreature.from_cryopod_bytes(byte_arrays[0]["Bytes"])
                if cryo is not None:
                    strings = normalize_indexed_list(entry.get("CustomDataStrings"))
                    if len(strings) > 9 and strings[9]:
                        cryo.species = strings[9]
                    return cryo
        if entry.get("CustomDataStrings"):
            cryo = CryopodCreature.from_asa_cryopod_data(entry)
            if cryo is not None:
                return cryo
    return None

_RICH_COLOR_RE = re.compile(r"<RichColor[^>]*>|</>")
_LOG_RE = re.compile(r"Day\s+(\d+),?\s+([\d:]+):\s*(.*)", re.DOTALL)

_STAT_NAMES: tuple[str, ...] = (
    "hp", "stam", "torp", "oxy", "food", "water",
    "temp", "weight", "melee", "speed", "fort", "craft",
)
_STAT_INDEX: dict[str, int] = {name: i for i, name in enumerate(_STAT_NAMES)}
# Legacy ASVExport keeps stats in this order in JSON; the trailing four were
# never emitted by legacy and are appended after the legacy block.
_LEGACY_STAT_ORDER: tuple[str, ...] = (
    "hp", "stam", "melee", "weight", "speed", "food", "oxy", "craft",
)
_EXTRA_STAT_ORDER: tuple[str, ...] = ("torp", "water", "temp", "fort")
_FLAT_STAT_ORDER: tuple[str, ...] = _LEGACY_STAT_ORDER + _EXTRA_STAT_ORDER


def _prop(obj: t.Any, name: str, default: t.Any = None, index: int | None = None) -> t.Any:
    if obj is None:
        return default
    if index is None:
        return obj.get_property_value(name, default=default)
    return obj.get_property_value(name, default=default, index=index)


def _int(val: t.Any, default: int = 0) -> int:
    if val is None or val is False:
        return default
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _float(val: t.Any, default: float = 0.0) -> float:
    if val is None or val is False:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _str(val: t.Any) -> str:
    """Coerce to stripped string. Empty for falsy values."""
    if val is None or val is False:
        return ""
    return str(val).strip()


# Empty defaults that get pruned from parser-added fields. Legacy keys
# (preserved via LEGACY_*_KEYS frozensets below) are emitted unconditionally
# so ASVExport-schema consumers never see a missing key.
_EMPTY_DEFAULTS: tuple[t.Any, ...] = (None, "", 0, 0.0, False, [])


def _compact(data: dict[str, t.Any], legacy: frozenset[str]) -> dict[str, t.Any]:
    """Drop parser-added keys whose value is an ARK-default empty.

    Keys in ``legacy`` are kept regardless of value (ASVExport.exe schema
    parity). Everything else is dropped when the value is ``None``, an empty
    string, an empty list, ``False``, or numeric zero.
    """
    return {k: v for k, v in data.items() if k in legacy or v not in _EMPTY_DEFAULTS}


LEGACY_TAMED_KEYS: frozenset[str] = frozenset({
    "id", "tribeid", "tribe", "tamer", "imprinter", "imprint", "creature",
    "name", "sex", "base", "lvl", "lat", "lon",
    "hp-w", "stam-w", "melee-w", "weight-w", "speed-w", "food-w", "oxy-w", "craft-w",
    "hp-t", "stam-t", "melee-t", "weight-t", "speed-t", "food-t", "oxy-t", "craft-t",
    "c0", "c1", "c2", "c3", "c4", "c5",
    "mut-f", "mut-m", "cryo", "ccc", "dinoid",
    "isMating", "isNeutered", "isClone",
    "tamedServer", "uploadedServer", "maturation", "traits", "inventory",
})
LEGACY_WILD_KEYS: frozenset[str] = frozenset({
    "id", "creature", "sex", "lvl", "lat", "lon",
    "hp", "stam", "melee", "weight", "speed", "food", "oxy", "craft",
    "c0", "c1", "c2", "c3", "c4", "c5",
    "ccc", "dinoid", "tameable", "trait",
})
LEGACY_PLAYER_KEYS: frozenset[str] = frozenset({
    "playerid", "steam", "name", "tribeid", "tribe", "sex", "lvl",
    "lat", "lon",
    "hp", "stam", "melee", "weight", "speed", "food", "water", "oxy", "craft", "fort",
    "active", "ccc", "achievements", "inventory", "netAddress",
    "steamid", "dataFile",
})
LEGACY_TRIBE_KEYS: frozenset[str] = frozenset({
    "tribeid", "tribe", "players", "members",
    "tames", "uploadedTames", "structures",
    "active", "dataFile",
})
LEGACY_STRUCT_KEYS: frozenset[str] = frozenset({
    "id", "tribeid", "tribe", "struct", "name", "locked", "created", "inventory",
    "lat", "lon", "ccc",
})
LEGACY_MAP_STRUCT_KEYS: frozenset[str] = frozenset({
    "struct", "inventory", "lat", "lon", "ccc",
})


def _stat_array(status: t.Any, prop_name: str) -> list[int]:
    if status is None:
        return [0] * 12
    out = [0] * 12
    getter = getattr(status, "get_properties_by_name", None)
    if callable(getter):
        for prop in getter(prop_name):
            idx = getattr(prop, "index", 0)
            if 0 <= idx < 12:
                out[idx] = _int(getattr(prop, "value", 0))
        return out
    for i in range(12):
        out[i] = _int(_prop(status, prop_name, default=0, index=i))
    return out


def _current_stat_floats(status: t.Any) -> list[float] | None:
    """Read ``CurrentStatusValues[0..11]`` from a character status component.

    Status components persist the live in-world values of all 12 stats. The
    array is indexed by ARK's ``EPrimalCharacterStatusValue`` enum:
    0=hp, 1=stam, 2=torpor, 3=oxy, 4=food, 5=water, 6=temp, 7=weight,
    8=melee, 9=speed, 10=temp-fortitude, 11=crafting.

    Returns ``None`` when the status component is missing or carries no
    CurrentStatusValues entries (e.g. uninitialised baby actor) so callers
    can distinguish "no data" from "all zeros".
    """
    if status is None:
        return None
    out: list[float] = [0.0] * 12
    seen = False
    getter = getattr(status, "get_properties_by_name", None)
    if callable(getter):
        # Real GameObject: get_properties_by_name surfaces every indexed
        # entry. Empty result == component carries no CurrentStatusValues
        # at all (uninitialised); return None so callers can distinguish
        # "no data" from "all zeros".
        for prop in getter("CurrentStatusValues"):
            idx = getattr(prop, "index", 0)
            if 0 <= idx < 12:
                out[idx] = _float(getattr(prop, "value", 0.0))
                seen = True
        return out if seen else None
    # Synthetic / cryopod stand-in: per-index get_property_value lookups.
    for i in range(12):
        val = _prop(status, "CurrentStatusValues", default=None, index=i)
        if val is not None:
            out[i] = _float(val)
            seen = True
    return out if seen else None


def _current_stats_dict(status: t.Any) -> dict[str, float] | None:
    """Return current stat values keyed by short stat name.

    Pre-conditions: ``status`` is the character status component (creature or
    player). May be ``None`` (e.g. offline player with no spawned pawn).
    Post-conditions: returns a dict ``{hp, stam, ..., craft}`` of floats, or
    ``None`` when no CurrentStatusValues are persisted on the component.
    """
    floats = _current_stat_floats(status)
    if floats is None:
        return None
    return {_STAT_NAMES[i]: floats[i] for i in range(12)}


def _flat_stats(points: list[int], suffix: str = "") -> dict[str, int]:
    """Emit all 12 stats as a flat dict.

    With ``suffix`` (``"w"`` / ``"t"`` / ``"m"``) emits ``hp-{suffix}`` …
    ``fort-{suffix}``. Without a suffix emits unsuffixed legacy wild keys
    (``hp``, ``stam``, …). The legacy ASVExport 8-stat block (hp, stam,
    melee, weight, speed, food, oxy, craft) is emitted first to preserve
    legacy diff order; the four stats legacy never surfaced (torp, water,
    temp, fort) are appended at the end.
    """
    sep = "-" if suffix else ""
    return {
        f"{name}{sep}{suffix}": points[_STAT_INDEX[name]]
        for name in _FLAT_STAT_ORDER
    }


def _gps_payload(
    obj: t.Any,
    map_config: MapConfig | None,
    ndigits: int | None = 2,
) -> dict[str, t.Any]:
    """Return ``ccc`` / ``lat`` / ``lon`` keys for a GameObject.

    ``ndigits`` rounds each ccc component and lat/lon to that many decimals.
    Defaults to ``2`` (matches legacy ASVExport's typical precision; passing
    ``None`` disables rounding).
    """
    loc = getattr(obj, "location", None)
    if loc is None:
        return {"ccc": "0 0 0", "lat": 0.0, "lon": 0.0}
    x = getattr(loc, "x", 0.0) or 0.0
    y = getattr(loc, "y", 0.0) or 0.0
    z = getattr(loc, "z", 0.0) or 0.0
    if ndigits is not None:
        x = round(x, ndigits)
        y = round(y, ndigits)
        z = round(z, ndigits)
    out: dict[str, t.Any] = {"ccc": f"{x} {y} {z}"}
    if map_config is not None:
        lat = float(map_config.ue_to_lat(y))
        lon = float(map_config.ue_to_lon(x))
        if ndigits is not None:
            lat = round(lat, ndigits)
            lon = round(lon, ndigits)
        out["lat"] = lat
        out["lon"] = lon
    else:
        out["lat"] = 0.0
        out["lon"] = 0.0
    return out


def _approx_real_datetime(
    in_game_time: t.Any,
    save: t.Any,
) -> dt.datetime | None:
    """Mirror legacy ContentContainer.GetApproxDateTimeOf.

    Returns the real-world datetime for an ``OriginalCreationTime`` /
    ``TamedAtTime``-style in-game seconds value, computed as::

        save.file_mtime + (in_game_time - save.game_time)

    Returns ``None`` if the conversion can't be made (no mtime, no game
    time, or non-numeric input).
    """
    if not in_game_time:
        return None
    mtime: dt.datetime | None = getattr(save, "file_mtime", None) if save else None
    if mtime is None:
        return None
    game_time = _float(getattr(save, "game_time", 0.0)) if save else 0.0
    if game_time <= 0:
        return None
    try:
        offset = float(in_game_time) - game_time
    except (TypeError, ValueError):
        return None
    return mtime + dt.timedelta(seconds=offset)


def _combine_dino_id(id1: t.Any, id2: t.Any) -> int:
    a, b = _int(id1), _int(id2)
    if a == 0 and b == 0:
        return 0
    return (a << 32) | (b & 0xFFFFFFFF)


def _colors(obj: t.Any) -> list[int]:
    out = [0] * 6
    getter = getattr(obj, "get_properties_by_name", None)
    if callable(getter):
        for prop in getter("ColorSetIndices"):
            idx = getattr(prop, "index", 0)
            if 0 <= idx < 6:
                out[idx] = _int(getattr(prop, "value", 0))
        return out
    for i in range(6):
        out[i] = _int(_prop(obj, "ColorSetIndices", default=0, index=i))
    return out


def _ancestor_parent(obj: t.Any, prefix: str) -> tuple[int | None, str]:
    """Extract parent dino_id + name from the first DinoAncestors entry."""
    ancestors = _prop(obj, "DinoAncestors")
    if not isinstance(ancestors, list) or not ancestors:
        return None, ""
    first = ancestors[0]
    if not isinstance(first, dict):
        return None, ""
    id1 = first.get(f"{prefix}DinoID1", 0)
    id2 = first.get(f"{prefix}DinoID2", 0)
    combined = _combine_dino_id(id1, id2) if (id1 or id2) else None
    name = first.get(f"{prefix}Name", "") or first.get("DinoName", "") or ""
    return combined, str(name).strip()


def _traits(obj: t.Any) -> list[str]:
    """Tamed/wild creature trait list (mutation traits, ASA + late ASE)."""
    val = _prop(obj, "CreatureTraits")
    if isinstance(val, list):
        return [str(v).strip() for v in val if v]
    getter = getattr(obj, "get_properties_by_name", None)
    if callable(getter):
        return [str(p.value).strip() for p in getter("CreatureTraits") if p.value]
    return []


def _save_lookup(save: t.Any) -> dict[t.Any, t.Any]:
    """Return cached id/guid/name → GameObject lookup, building once per save."""
    cached = getattr(save, "_export_lookup", None)
    if isinstance(cached, dict):
        return cached
    objects = getattr(save, "objects", None) or []
    iterable = objects.values() if isinstance(objects, dict) else objects
    result: dict[t.Any, t.Any] = {}
    for obj in iterable:
        oid = getattr(obj, "id", None)
        guid = getattr(obj, "guid", None)
        names = getattr(obj, "names", None) or ()
        if oid is not None:
            result[oid] = obj
        if guid:
            result[guid] = obj
        for nm in names:
            result[nm] = obj
    try:
        save._export_lookup = result
    except (AttributeError, TypeError):
        pass
    return result


def _ref_name(ref: t.Any) -> t.Any:
    """Best-effort identifier for an object reference property value.

    Object refs in the parser come through as ``(class_name, key)`` tuples;
    the key is either a numeric GameObject id (matches ``GameObject.id``)
    or a string name / blueprint path. Numeric ids are returned as ``int``
    so they cross-reference cleanly against the structures export's ``id``
    field. String keys are returned as ``str``. Empty / ``None`` → ``""``.
    """
    if ref is None or ref == "":
        return ""
    if isinstance(ref, tuple) and len(ref) == 2:
        val = ref[1]
        return val if isinstance(val, int) else str(val)
    return ref if isinstance(ref, int) else str(ref)


def _ref_list(val: t.Any) -> list[t.Any]:
    """Resolve a list of object refs to ids/names (used by LinkedStructures, etc.)."""
    if not isinstance(val, list):
        return []
    return [name for name in (_ref_name(v) for v in val) if name != ""]


def _saddle_structure_refs(val: t.Any) -> list[str]:
    """Extract the ``MyStructure`` ref from each entry of ``SaddleStructures``.

    Each entry is a struct with relative-location + bone-name + a structure
    object reference. Only the reference is useful for cross-linking, so
    drop the rest to keep export size sane.
    """
    if not isinstance(val, list):
        return []
    out: list[str] = []
    for entry in val:
        if isinstance(entry, dict):
            ref = entry.get("MyStructure")
            if ref:
                out.append(_ref_name(ref))
    return out


def _pin_code(obj: t.Any) -> int:
    """Return the active PIN code (or ``0`` for "no PIN").

    ARK serializes PINs in two forms; only one is ever populated:

    - ``CurrentPinCode`` (singular) — a scalar carrying the actual code.
      This is where every observed non-zero PIN lives on real saves.
    - ``CurrentPinCodes`` (plural) — an ``ArrayProperty`` of ints. In
      practice this is always zero-filled across every reference dump
      (ASE + Primitive+); historical PINs from earlier ARK versions are
      not persisted. The plural form is checked as a fallback only.

    Returns ``0`` (pruned by ``_compact``) when no PIN is set.

    Note: PIN codes are sensitive credentials. Exposed for tribe-admin
    auditing and inventory recovery; downstream tooling should not surface
    them to non-tribe players.
    """
    singular = _int(_prop(obj, "CurrentPinCode"))
    if singular:
        return singular
    raw = _prop(obj, "CurrentPinCodes")
    if isinstance(raw, list):
        for v in raw:
            i = _int(v)
            if i:
                return i
    elif isinstance(raw, dict):
        for k in sorted(k for k in raw if isinstance(k, int)):
            i = _int(raw[k])
            if i:
                return i
    elif raw:
        return _int(raw)
    return 0


def _harvest_levels(val: t.Any) -> list[int]:
    """Flatten ``HarvestResourceLevels`` into a list of ints.

    Returns ``[]`` (pruned by ``_compact``) when every level is zero.
    """
    if isinstance(val, list):
        out = [_int(v) for v in val]
    elif isinstance(val, dict):
        out = [_int(val[k]) for k in sorted(k for k in val if isinstance(k, int))]
    else:
        return []
    return out if any(out) else []


def _iso_pair(obj: t.Any, prop_name: str, save: t.Any) -> tuple[float, str | None]:
    """Return ``(seconds, iso)`` for an in-game-time property.

    ``seconds`` is the raw float (0.0 if missing/non-numeric); ``iso`` is the
    converted ISO 8601 datetime via :func:`_approx_real_datetime`, or
    ``None`` when the conversion can't be made (no anchor, zero value).
    """
    raw = _float(_prop(obj, prop_name))
    if not raw:
        return raw, None
    d = _approx_real_datetime(raw, save)
    return raw, d.isoformat() if d is not None else None


def _resolve(ref: t.Any, lookup: dict[t.Any, t.Any]) -> t.Any:
    if ref is None:
        return None
    if isinstance(ref, tuple) and len(ref) == 2:
        return lookup.get(ref[1])
    return lookup.get(ref)


def _world_objects(save: t.Any, getter: str, legacy_attr: str) -> list[t.Any]:
    """Return a category list from save, cached per save instance.

    Without caching, each export type re-walks ``save.objects`` and reapplies
    the per-category filter (tamed, wild, structures, players, ...). On a
    360k-object save that adds up to several extra full passes per
    ``export_all`` call. The cache is keyed by getter name so each category
    materializes exactly once and is reused across every subsequent export.
    """
    cache = getattr(save, "_world_objects_cache", None)
    if cache is None:
        cache = {}
        try:
            save._world_objects_cache = cache
        except (AttributeError, TypeError):
            cache = None  # save instance doesn't allow attribute write; bypass cache
    if cache is not None and getter in cache:
        return cache[getter]
    fn = getattr(save, getter, None)
    if callable(fn):
        result = list(fn())
    else:
        val = getattr(save, legacy_attr, None)
        result = list(val) if isinstance(val, list) else []
    if cache is not None:
        cache[getter] = result
    return result


def _collection(source: t.Any, attr: str, kind: type[t.Any]) -> list[t.Any]:
    if isinstance(source, kind):
        return [source]
    if isinstance(source, (list, tuple)):
        return list(source)
    val = getattr(source, attr, None)
    if isinstance(val, (list, tuple)):
        return list(val)
    return [] if val is None else [val]


def _status_for(obj: t.Any, lookup: dict[t.Any, t.Any]) -> t.Any:
    """Find a creature's status component."""
    comps = getattr(obj, "components", None)
    if isinstance(comps, dict):
        status = comps.get("status")
        if status is not None:
            return status
    return _resolve(_prop(obj, "MyCharacterStatusComponent"), lookup)


def _inventory_component(obj: t.Any, lookup: dict[t.Any, t.Any]) -> t.Any:
    inv = _resolve(_prop(obj, "MyInventoryComponent"), lookup)
    if inv is not None:
        return inv
    comps = getattr(obj, "components", None)
    if isinstance(comps, dict):
        return comps.get("inventory")
    return None


# Item properties already surfaced at top-level of an inventory entry or
# representing internal save plumbing we strip from the ``stats`` subdict.
# Stripping these is the difference between meaningful per-item stats and
# unbounded snake_case dumps of UE4 internals.
_ITEM_STATS_SKIP: frozenset[str] = frozenset({
    # Already surfaced at top level of inventory entry.
    # (ItemID is kept and combined into ``stats.id`` for unique tracking)
    "ItemQuantity",
    "bIsBlueprint",
    # Internal save plumbing / object refs.
    "OwnerInventory",
    "ItemCustomClass",
    "CustomItemDatas",       # cryopod blob, surfaced via dino_* keys
    "CustomItemData",
    "CustomItemName",
    "CustomItemDescription",
    # Internal timestamps / versioning, opaque to consumers.
    "LastAutoDurabilityDecreaseTime",
    "ItemVersion",
    "CreationTime",
    "LastUseTime",
    # UI / engine state flags. Not item state, not actionable downstream.
    "bAllowRemovalFromInventory",
    "bHideFromInventoryDisplay",
    "bHideFromRemoteInventoryDisplay",
    "bCanSlot",
    "bAllowEquppingItem",    # sic, ARK typo preserved in save format
    "bIsInitialItem",
    "bForcePreventGrinding",
    "bIsEngram",             # redundant with item class
    "bIsCustomRecipe",
    "bIsFoodRecipe",
    "bIsRepairing",
    "bIsEquipped",
    "bIsSlot",
    "bAllowRemovalFromSteamInventory",
    "bIsFromAllClustersInventory",
    "bFromSteamInventory",
    # Cloud / tribute internals.
    "ItemArchetype",         # blueprint path, redundant with itemId
    "SteamUserItemID",       # always empty array on cluster items
    "UploadEarliestValidTime",
    "ExpirationTimeUTC",     # tribute expiry, opaque UTC seconds
    "ClusterSpoilingTimeUTC",
    "CraftingSkill",         # 0 on uploaded items
    "ItemProfileVersion",    # internal versioning
    "bNetInfoFromClient",    # net replication flag
    "OwnerPlayerDataID",     # 0 on uploaded items
    "LastOwnerPlayer",       # -1 sentinel on uploaded items
    "ItemStatClampsMultiplier",
    "OwnerPlayerDataId",     # ASA casing variant of OwnerPlayerDataID
    # ASA cosmetic / cluster noise.
    "CustomCosmeticAuthVars",
    "CustomCosmeticModSkinReplacementID",
    "CustomCosmeticModSkinVariantID",
    "bDoApplyOriginalColorsWhenUnskinned",
    "bIsFromClubArk",
})

# Egg-genetic fields in ArkTributeItem are populated with garbage struct
# overlap bytes for non-egg items. Only surface them when the item is
# actually an egg.
_EGG_ONLY_FIELDS: frozenset[str] = frozenset({
    "egg_number_of_level_up_points_applied",
    "egg_tamed_ineffectiveness_modifier",
    "egg_color_set_indices",
    "egg_gender_override",
    "egg_dino_ancestors",
    "egg_dino_ancestors_male",
    "egg_random_mutations_female",
    "egg_random_mutations_male",
    "egg_number_mutations_applied",
    "egg_number_of_mutations_applied",  # "NumberOf" variant (matches EggNumberOfLevelUpPointsApplied naming)
    "egg_dino_gene_traits",
})


def _is_meaningful_value(value: t.Any) -> bool:
    """Filter no-op default values from item stat output.

    Empty containers and empty strings carry no information; surfacing them
    just adds JSON noise. NaN floats are treated as missing (ARK uses NaN
    for "no expiration / never spoils"). Numeric zeros are kept (a stat
    value of 0 is legitimate, e.g. unequipped saddle slot).
    """
    if value is None:
        return False
    if isinstance(value, (list, dict, str)) and len(value) == 0:
        return False
    if isinstance(value, float) and value != value:  # NaN
        return False
    if isinstance(value, str) and value == "Unknown":
        return False
    return True


# Per-key default sentinels. When a stat surfaces a value equal to its
# sentinel, that field carries no signal (skin -1 = no skin applied, etc).
# Drop the key entirely rather than spamming JSON output with no-ops.
_STAT_KEY_DEFAULTS: dict[str, t.Any] = {
    "skin": -1,
    "craft_queue": 0,
    "craft_at": 0.0,
    "custom_id": 0,
    "slot": 0,
    "temp_slot": 0,
    "loaded_ammo": 0,
    "skill_bonus": 0.0,
    "spoils_at": 0.0,
    "spoiled_at": 0.0,
    "rating": 0.0,
    "color_pre_skin": [0, 0, 0, 0, 0, 0],
    "drop_location": {"x": 0.0, "y": 0.0, "z": 0.0},
    "quality": 0,
    "item_durability": 0.0,
    "associated_dino_id": 0,
}


def _is_default(key: str, value: t.Any) -> bool:
    """True if ``value`` matches the documented no-signal sentinel for ``key``."""
    if key not in _STAT_KEY_DEFAULTS:
        return False
    default = _STAT_KEY_DEFAULTS[key]
    if isinstance(default, list) and isinstance(value, list):
        return len(value) == len(default) and all(
            a == b for a, b in zip(value, default)
        )
    if isinstance(default, dict) and isinstance(value, dict):
        # Vector structs are sometimes keyed X/Y/Z (ASA) instead of x/y/z;
        # compare case-insensitively so a zero drop_location still prunes.
        lowered = {str(k).lower(): v for k, v in value.items()}
        return all(lowered.get(k, 0) == v for k, v in default.items())
    return value == default


def _flatten_color_array(value: t.Any) -> dict[str, int]:
    """``color: [c0..c5]`` (or dict[idx → c]) → ``{c0, c1, ..., c5}``.

    Mirrors how tame exports surface region colors (``c0`` .. ``c5``).
    Non-zero entries only; all-zero color arrays return ``{}`` so the
    caller can skip emission.
    """
    out: dict[str, int] = {}
    iterable: t.Iterable[tuple[int, t.Any]]
    if isinstance(value, dict):
        iterable = ((int(k), v) for k, v in value.items() if isinstance(k, (int, str)) and str(k).lstrip("-").isdigit())
    elif isinstance(value, list):
        iterable = enumerate(value)
    else:
        return out
    for idx, v in iterable:
        if 0 <= idx < 6 and v:
            try:
                out[f"c{idx}"] = int(v)
            except (TypeError, ValueError):
                continue  # struct-valued color (LinearColor) etc; not a palette index
    return out

# ARK universal 8-slot ItemStatValues map. Each slot is raw uint16; the
# displayed percentage = raw * per-blueprint multiplier (in the item's UE
# blueprint, not the save). Slot semantics stable across all item classes;
# names disambiguated from top-level entries (e.g. ``durability_max`` for
# the multiplier slot vs ``durability`` for current condition 0-1).
_ITEM_STAT_SLOT_NAMES: tuple[str, ...] = (
    "gen_quality",       # rarely populated
    "armor",
    "durability_max",
    "damage",            # weapon damage %
    "clip_size",         # weapon clip multiplier (NOT currently-loaded ammo)
    "hypo",              # hypothermal insulation
    "weight",
    "hyper",             # hyperthermal insulation
)

# Snake_case property name → shorter consumer-facing name. Applied after
# pascal→snake conversion. Anything not in the table keeps its snake_case
# name so newly-added ASA props still surface automatically.
_STAT_NAME_ALIASES: dict[str, str] = {
    "item_rating": "rating",
    "item_quality_index": "quality",
    "saved_durability": "durability",
    "item_color_id": "color",
    "pre_skin_item_color_id": "color_pre_skin",
    "item_skin_template": "skin",
    "weapon_clip_ammo": "loaded_ammo",
    "crafter_character_name": "crafter",
    "crafter_tribe_name": "crafter_tribe",
    "crafted_skill_bonus": "skill_bonus",
    "custom_item_id": "custom_id",
    "last_spoiling_time": "spoiled_at",
    "next_spoiling_time": "spoils_at",
    "next_craft_completion_time": "craft_at",
    "slot_index": "slot",
    "temp_slot_index": "temp_slot",
    "accessory_slot_override": "accessory_slot",
    "original_item_drop_location": "drop_location",
    "chibi_xp": "chibi_xp",
}


def _combine_item_id(value: t.Any) -> str | None:
    """Combine ItemID struct ``{ItemID1, ItemID2}`` to single string.

    Uses explicit ``is None`` fallback (not ``or``) so a legitimate
    ``ItemID1 == 0`` is not silently replaced by an ``ItemID1_0`` variant
    key. Non-numeric / corrupt id components return ``None`` rather than
    raising and aborting the whole inventory export.
    """
    if not isinstance(value, dict):
        return None
    id1 = value.get("ItemID1")
    if id1 is None:
        id1 = value.get("ItemID1_0")
    id2 = value.get("ItemID2")
    if id2 is None:
        id2 = value.get("ItemID2_0")
    if id1 is None and id2 is None:
        return None
    try:
        return f"{int(id1 or 0)}_{int(id2 or 0)}"
    except (TypeError, ValueError):
        return None


def _normalize_stat_value(name: str, value: t.Any) -> t.Any:
    """Collapse single-index dicts. ItemStatValues handled separately."""
    if isinstance(value, dict) and len(value) == 1 and 0 in value:
        return value[0]
    if isinstance(value, dict) and len(value) == 1 and "0" in value:
        return value["0"]
    return value


def _apply_stat_aliases(
    stats: dict[str, t.Any],
    *,
    item_class: str = "",
) -> dict[str, t.Any]:
    """Flatten item_stat_values + item_id; apply short-name aliases.

    Filters egg_* fields when ``item_class`` isn't an egg (those fields
    are bit-leaked struct overlap garbage on non-egg items in ASA cloud
    tribute data). Also filters empty containers/strings universally.
    """
    is_egg = "Egg" in item_class
    out: dict[str, t.Any] = {}
    raw_slot_values = stats.pop("item_stat_values", None)
    item_id = stats.pop("item_id", None)
    combined_id = _combine_item_id(item_id) if item_id is not None else None
    if combined_id:
        out["id"] = combined_id
    dino_id1 = stats.pop("associated_dino_id1", None)
    dino_id2 = stats.pop("associated_dino_id2", None)
    combined_dino = _combine_dino_id(dino_id1, dino_id2) if (dino_id1 or dino_id2) else 0
    if combined_dino:
        out["associated_dino_id"] = combined_dino
    color_raw = stats.pop("item_color_id", None)
    if color_raw is not None:
        out.update(_flatten_color_array(color_raw))
    for key, val in stats.items():
        if key in _EGG_ONLY_FIELDS and not is_egg:
            continue
        if not _is_meaningful_value(val):
            continue
        alias = _STAT_NAME_ALIASES.get(key, key)
        if _is_default(alias, val):
            continue
        out[alias] = val
    out.update(_expand_stat_slots(raw_slot_values))
    return out


def _expand_stat_slots(raw_slot_values: t.Any) -> dict[str, t.Any]:
    """Map raw ItemStatValues to named slots, accepting either input shape.

    Two shapes occur in practice:

    - GameObject inventory path → a sparse ``{index: value}`` dict (see
      :func:`_indexed_property_map`, which preserves the index even for a
      single populated slot).
    - Cloud / uploaded path → a dense 8-element ``list`` indexed 0..7
      (``normalize_indexed_data`` collapses the indexed property to a list).

    Anything else (a bare scalar from an upstream single-entry collapse that
    lost its index) carries no recoverable slot and is ignored. Raw 0 means
    "no stat roll", so zero slots are skipped.
    """
    pairs: t.Iterable[tuple[t.Any, t.Any]]
    if isinstance(raw_slot_values, dict):
        pairs = raw_slot_values.items()
    elif isinstance(raw_slot_values, list):
        pairs = enumerate(raw_slot_values)
    else:
        return {}
    out: dict[str, t.Any] = {}
    for k, v in pairs:
        try:
            idx = int(k)
        except (TypeError, ValueError):
            continue
        if 0 <= idx < len(_ITEM_STAT_SLOT_NAMES) and v:
            out[_ITEM_STAT_SLOT_NAMES[idx]] = v
    return out

_PASCAL_SNAKE_RE_1 = re.compile(r"(.)([A-Z][a-z]+)")
_PASCAL_SNAKE_RE_2 = re.compile(r"([a-z0-9])([A-Z])")


def _pascal_to_snake(name: str) -> str:
    """``ItemStatValues`` → ``item_stat_values``, ``bIsBlueprint`` → ``b_is_blueprint``."""
    s = _PASCAL_SNAKE_RE_1.sub(r"\1_\2", name)
    return _PASCAL_SNAKE_RE_2.sub(r"\1_\2", s).lower()


def _indexed_property_map(item_obj: t.Any, prop_name: str) -> dict[int, t.Any]:
    """Read a multi-index property as ``{index: value}`` straight from the object.

    ``_serialize_properties`` collapses a single-entry non-Byte property group
    to a bare scalar, which destroys the slot index for indexed arrays such as
    ``ItemStatValues`` / ``ItemColorID`` (an item with only one populated stat
    slot would otherwise lose both the value and which slot it was). Reading the
    raw ``Property`` list keeps every index, mirroring :func:`_colors`.
    """
    getter = getattr(item_obj, "get_properties_by_name", None)
    if not callable(getter):
        return {}
    out: dict[int, t.Any] = {}
    for prop in getter(prop_name):
        idx = int(getattr(prop, "index", 0) or 0)
        val = getattr(prop, "value", None)
        if val is not None:
            out[idx] = val
    return out


def _item_stats_dict(item_obj: t.Any, item_class: str = "") -> dict[str, t.Any]:
    """Surface every parseable property on an inventory item as snake_case.

    Walks the GameObject's serialized property map (object refs already
    stripped by ``_serialize_properties``), converts each property name to
    snake_case, and drops a small denylist of fields that are either
    redundant with the top-level entry (qty, blueprint), internal plumbing
    (ItemID, OwnerInventory), or huge embedded blobs surfaced elsewhere
    (CustomItemDatas).

    Returns ``{}`` if the object cannot be introspected (synthetic / no
    properties).
    """
    serializer = getattr(item_obj, "_serialize_properties", None)
    if not callable(serializer):
        return {}
    try:
        raw = serializer()
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    pre: dict[str, t.Any] = {}
    for name, value in raw.items():
        if name in _ITEM_STATS_SKIP:
            continue
        snake = _pascal_to_snake(name)
        pre[snake] = _normalize_stat_value(snake, value)
    # ItemStatValues / ItemColorID are indexed UInt16 arrays. _serialize_properties
    # collapses a single populated slot to a bare scalar (losing the index), so
    # re-read them straight from the object to preserve {index: value}; a
    # single-stat saddle/weapon would otherwise drop its only roll.
    isv = _indexed_property_map(item_obj, "ItemStatValues")
    if isv:
        pre["item_stat_values"] = isv
    color = _indexed_property_map(item_obj, "ItemColorID")
    if color:
        pre["item_color_id"] = color
    return _apply_stat_aliases(pre, item_class=item_class)


def _inventory_items(obj: t.Any, lookup: dict[t.Any, t.Any]) -> list[dict[str, t.Any]]:
    inv = _inventory_component(obj, lookup)
    if inv is None:
        return []
    refs = _prop(inv, "InventoryItems")
    if not isinstance(refs, list):
        return []
    items: list[dict[str, t.Any]] = []
    for ref in refs:
        item_obj = _resolve(ref, lookup)
        if item_obj is None:
            continue
        class_name = str(getattr(item_obj, "class_name", "") or "")
        entry: dict[str, t.Any] = {
            "itemId": class_name,
            "qty": _int(_prop(item_obj, "ItemQuantity"), default=1) or 1,
            "blueprint": bool(_prop(item_obj, "bIsBlueprint", default=False)),
        }
        if _is_cryopod_class(class_name):
            cryo = _decode_inventory_cryopod(item_obj)
            if cryo is not None:
                props = cryo.creature_props
                id1 = props.get("DinoID1", props.get("DinoID1_0", 0))
                id2 = props.get("DinoID2", props.get("DinoID2_0", 0))
                dino_id = _combine_dino_id(id1, id2)
                if dino_id:
                    entry["dino_id"] = dino_id
                species_or_class = getattr(cryo, "species", "") or getattr(cryo, "class_name", "")
                if species_or_class:
                    entry["dino_creature"] = str(species_or_class)
                name = props.get("TamedName") or props.get("TamedName_0")
                if name:
                    entry["dino_name"] = str(name)
        entry.update(_item_stats_dict(item_obj, class_name))
        items.append(entry)
    return items


def _tribe_counts(save: t.Any) -> dict[int, dict[str, int]]:
    """Build tribe_id → {tames, structures} counts from a WorldSave.

    Returns an empty dict when ``save`` lacks WorldSave getters (e.g. when
    the caller passed a SimpleNamespace of tribe parsers without world data).
    """
    cached = getattr(save, "_tribe_counts", None)
    if isinstance(cached, dict):
        return cached
    if not callable(getattr(save, "get_tamed_creatures", None)):
        return {}
    counts: dict[int, dict[str, int]] = {}
    for obj in save.get_tamed_creatures():
        tid = _int(_prop(obj, "TargetingTeam"))
        if not tid:
            continue
        counts.setdefault(tid, {"tames": 0, "structures": 0})["tames"] += 1
    for obj in save.get_structures():
        tid = _int(_prop(obj, "TargetingTeam"))
        if not tid:
            continue
        counts.setdefault(tid, {"tames": 0, "structures": 0})["structures"] += 1
    try:
        save._tribe_counts = counts
    except (AttributeError, TypeError):
        pass
    return counts


def _tamed_dict(
    obj: t.Any,
    status: t.Any,
    lookup: dict[t.Any, t.Any],
    map_config: MapConfig | None,
    save: t.Any = None,
) -> dict[str, t.Any]:
    base_pts = _stat_array(status, "NumberOfLevelUpPointsApplied")
    tamed_pts = _stat_array(status, "NumberOfLevelUpPointsAppliedTamed")
    mut_pts = _stat_array(status, "NumberOfMutationsAppliedTamed")
    base_level = _int(_prop(status, "BaseCharacterLevel"), default=1) or 1
    extra_level = _int(_prop(status, "ExtraCharacterLevel"))
    dino_id = _combine_dino_id(_prop(obj, "DinoID1"), _prop(obj, "DinoID2"))
    colors = _colors(obj)
    is_female = bool(_prop(obj, "bIsFemale", default=False))
    targeting_team = _int(_prop(obj, "TargetingTeam"))
    baby = bool(_prop(obj, "bIsBaby", default=False))
    baby_age = _float(_prop(obj, "BabyAge"), default=1.0) if baby else 1.0
    father_id, father_name = _ancestor_parent(obj, "Male")
    mother_id, mother_name = _ancestor_parent(obj, "Female")
    tribe_name = _str(_prop(obj, "TribeName"))
    _, stasis_iso = _iso_pair(obj, "LastEnterStasisTime", save)
    _, baby_age_iso = _iso_pair(obj, "LastUpdatedBabyAgeAtTime", save)
    _, gestation_iso = _iso_pair(obj, "LastUpdatedGestationAtTime", save)
    _, cuddle_iso = _iso_pair(obj, "BabyNextCuddleTime", save)

    data: dict[str, t.Any] = {
        "id": dino_id,
        "tribeid": targeting_team,
        "tribe": tribe_name or None,
        "tamer": _str(_prop(obj, "TamerString")),
        "imprinter": _str(_prop(obj, "ImprinterName")),
        "imprint": _float(_prop(status, "DinoImprintingQuality")),
        "creature": getattr(obj, "class_name", "") or "",
        "name": _str(_prop(obj, "TamedName")),
        "sex": "Female" if is_female else "Male",
        "base": base_level,
        "lvl": base_level + extra_level,
        **_flat_stats(base_pts, "w"),
        **_flat_stats(tamed_pts, "t"),
        **{f"c{i}": colors[i] for i in range(6)},
        "mut-f": _int(_prop(obj, "RandomMutationsFemale")),
        "mut-m": _int(_prop(obj, "RandomMutationsMale")),
        "cryo": bool(_prop(obj, "IsInCryo", default=False)),
        "dinoid": str(dino_id),
        "isMating": bool(_prop(obj, "bEnableTamedMating", default=False)),
        "isNeutered": bool(_prop(obj, "bNeutered", default=False)),
        "isClone": bool(_prop(obj, "bIsClone", default=False))
            or bool(_prop(obj, "bIsCloneDino", default=False)),
        "tamedServer": _str(_prop(obj, "TamedOnServerName")),
        "uploadedServer": _str(_prop(obj, "UploadedFromServerName")),
        "maturation": str(int(baby_age * 100)),
        **_flat_stats(mut_pts, "m"),
        "traits": _traits(obj),
        "inventory": _inventory_items(obj, lookup),
        "father_id": father_id,
        "mother_id": mother_id,
        "father_name": father_name,
        "mother_name": mother_name,
        "level_added": extra_level,
        "experience": _int(_prop(status, "ExperiencePoints")),
        "wandering": bool(_prop(obj, "bEnableTamedWandering", default=False)),
        "tamed_at": (
            d.isoformat()
            if (d := _approx_real_datetime(_prop(obj, "TamedAtTime"), save)) is not None
            else None
        ),
        "last_ally_in_range": (
            d.isoformat()
            if (d := _approx_real_datetime(
                _prop(obj, "LastInAllyRangeTime")
                or _prop(obj, "LastInAllyRangeSerialized"),
                save,
            )) is not None
            else None
        ),
        "current_stats": _current_stats_dict(status),
        "imprinter_player_id": _int(_prop(obj, "ImprinterPlayerDataID")),
        "imprinter_net_id": _str(_prop(obj, "ImprinterPlayerUniqueNetId")),
        "taming_team_id": _int(_prop(obj, "TamingTeamID")),
        "owning_player_id": _int(_prop(obj, "OwningPlayerID")),
        "owning_player_name": _str(_prop(obj, "OwningPlayerName")),
        "aggression_level": _int(_prop(obj, "TamedAggressionLevel")),
        "ai_targeting_range": _float(_prop(obj, "TamedAITargetingRange")),
        "follow_stopping_distance": _float(_prop(obj, "FollowStoppingDistance")),
        "is_flying": bool(_prop(obj, "bIsFlying", default=False)),
        "is_turret_mode": bool(_prop(obj, "bIsInTurretMode", default=False)),
        "ignore_whistles": bool(_prop(obj, "bIgnoreAllWhistles", default=False)),
        "only_target_conscious": bool(_prop(obj, "bOnlyTargetConscious", default=False)),
        "attack_team_member_dinos": bool(_prop(obj, "bAttackTeamMemberDinos", default=False)),
        "next_cuddle_food": _str(_prop(obj, "BabyCuddleFood")),
        "next_cuddle_type": _int(_prop(obj, "BabyCuddleType")),
        "latest_uploaded_server": _str(_prop(obj, "LatestUploadedFromServerName")),
        "previous_uploaded_server": _str(_prop(obj, "PreviousUploadedFromServerName")),
        "saddle_structures": _saddle_structure_refs(_prop(obj, "SaddleStructures")),
        "harvest_resource_levels": _harvest_levels(_prop(obj, "HarvestResourceLevels")),
        "wild_spawn_region": _str(_prop(obj, "OriginalNPCVolumeName")),
        "downloaded_at": (
            d.isoformat()
            if (d := _approx_real_datetime(_prop(obj, "DinoDownloadedAtTime"), save)) is not None
            else None
        ),
        "original_created": (
            d.isoformat()
            if (d := _approx_real_datetime(_prop(obj, "OriginalCreationTime"), save)) is not None
            else None
        ),
        "next_mating_at": (
            d.isoformat()
            if (d := _approx_real_datetime(_prop(obj, "NextAllowedMatingTime"), save)) is not None
            else None
        ),
        "last_stasis": stasis_iso,
        "last_baby_age_update": baby_age_iso,
        "last_gestation_update": gestation_iso,
        "next_cuddle": cuddle_iso,
    }
    data.update(_gps_payload(obj, map_config, ndigits=2))
    return _compact(data, LEGACY_TAMED_KEYS)


def export_tamed(save: t.Any, map_config: MapConfig | None = None) -> list[dict[str, t.Any]]:
    """Emit ASV_Tamed records.

    Pre-conditions: ``save`` exposes ``get_tamed_creatures()`` (in-world
    tames) and ideally ``iter_cryopod_creatures()`` (creatures whose actor
    has been removed from the world and re-embedded inside a cryopod /
    soultrap / vivarium / dinoball item).

    Post-conditions: returned list combines (a) every in-world tame and
    (b) every cryopod-embedded tame, with the latter carrying ``cryo=True``
    and inheriting the cryopod item's world location for GPS fields.
    """
    objects = _world_objects(save, "get_tamed_creatures", "tamed_objects")
    lookup = _save_lookup(save)
    results: list[dict[str, t.Any]] = [
        _tamed_dict(obj, _status_for(obj, lookup), lookup, map_config, save)
        for obj in objects
    ]
    results.extend(_export_world_cryopods(save, map_config))
    return results


def _build_item_owner_lookup(
    save: t.Any, lookup: dict[t.Any, t.Any]
) -> dict[t.Any, dict[str, t.Any]]:
    """Map inventory-item id → owning container info.

    For every object that has an ``InventoryItems`` property (structures,
    player pawns, dino inventory components), walk its contained item refs
    and record the owner's tribe id + display names. Used to infer tribe
    affiliation for ASA cryopod creatures whose embedded property blocks
    we cannot decode, but whose containing cryopod item lives in a
    structure or player inventory we *can* read.
    """
    out: dict[t.Any, dict[str, t.Any]] = {}
    objects = getattr(save, "objects", None) or []
    iterable = objects.values() if isinstance(objects, dict) else objects
    # Walk every actor with a MyInventoryComponent ref (structures, player
    # pawns, dinos), resolve the inventory, then enumerate its items.
    # Walking from the actor side gives us TargetingTeam / TribeName /
    # PlayerName directly, no reverse lookup needed.
    for actor in iterable:
        inv_ref = _prop(actor, "MyInventoryComponent")
        if inv_ref is None:
            continue
        inv = _resolve(inv_ref, lookup)
        if inv is None:
            continue
        refs = _prop(inv, "InventoryItems")
        if not isinstance(refs, list) or not refs:
            continue
        tid = _int(_prop(actor, "TargetingTeam"))
        tribe_name = _str(_prop(actor, "TribeName")) or _str(_prop(actor, "OwnerName"))
        info = {
            "TargetingTeam": tid,
            "TribeName": tribe_name,
        }
        for ref in refs:
            item_obj = _resolve(ref, lookup)
            if item_obj is None:
                continue
            item_id = getattr(item_obj, "id", None)
            if item_id is None:
                continue
            if item_id not in out:
                out[item_id] = info
    return out


def _export_world_cryopods(
    save: t.Any,
    map_config: MapConfig | None,
) -> list[dict[str, t.Any]]:
    """Build ASV_Tamed records for cryopod-embedded creatures on the map.

    ARK strips the actor for any creature stuffed into a cryopod / soultrap
    / vivarium / dinoball and serialises a snapshot into the item's
    ``CustomItemDatas``. ``get_tamed_creatures()`` therefore misses them
    entirely. We walk ``iter_cryopod_creatures()`` (when available),
    decode each embedded blob, and produce ``ASV_Tamed`` entries with
    ``cryo=True`` and the cryopod item's location. When the embedded
    blob does not yield a tribe id (ASA, partial decode), we infer it
    from the cryopod item's containing inventory (structure or pawn).
    """
    iter_cryos = getattr(save, "iter_cryopod_creatures", None)
    if not callable(iter_cryos):
        return []
    lookup = _save_lookup(save)
    owner_lookup = _build_item_owner_lookup(save, lookup)
    out: list[dict[str, t.Any]] = []
    empty_lookup: dict[t.Any, t.Any] = {}
    for item_obj, cryo in iter_cryos():
        actor, status = _cryo_props_to_synthetic(cryo)
        # Inherit the cryopod's world location so GPS fields populate.
        actor.location = getattr(item_obj, "location", None)
        # Infer tribe/owner from containing inventory when the decoded
        # creature blob did not supply them (ASA partial decode path).
        item_id = getattr(item_obj, "id", None)
        owner_info = owner_lookup.get(item_id) if item_id is not None else None
        if owner_info is not None:
            for key, val in owner_info.items():
                if val and not cryo.creature_props.get(key):
                    cryo.creature_props[key] = val
        record = _tamed_dict(actor, status, empty_lookup, map_config, save)
        # The synthetic actor carries no IsInCryo property; force the legacy
        # flag so consumers can distinguish in-world tames from stored ones.
        record["cryo"] = True
        out.append(record)
    return out


class _SyntheticGameObject:
    """Lightweight GameObject stand-in for cryopod-blob-decoded creatures.

    Cluster-uploaded creatures live as serialized creature objects inside
    ``ArkTamedDinosData[].DinoData`` byte blobs. ``CryopodCreature`` already
    parses that blob into ``creature_props`` / ``status_props`` dicts. We
    wrap those in this adapter so the rest of the export pipeline can call
    ``get_property_value`` on them just like a real ``GameObject``.
    """

    __slots__ = ("class_name", "id", "guid", "names", "location", "properties",
                 "components", "is_item", "_props")

    def __init__(self, class_name: str, props: dict[str, t.Any]) -> None:
        self.class_name = class_name
        self.id = 0
        self.guid = ""
        self.names: list[str] = []
        self.location = None
        self.properties: list[t.Any] = []
        self.components: dict[str, t.Any] = {}
        self.is_item = False
        self._props = props

    def get_property_value(
        self,
        name: str,
        default: t.Any = None,
        index: int | None = None,
    ) -> t.Any:
        if index is None or index == 0:
            val = self._props.get(name, self._props.get(f"{name}_0"))
            if val is None:
                return default
            return val
        val = self._props.get(f"{name}_{index}")
        return default if val is None else val


def _cryo_props_to_synthetic(
    cryo: CryopodCreature,
    status_class: str = "DinoCharacterStatusComponent_BP_C",
) -> tuple[_SyntheticGameObject, _SyntheticGameObject]:
    """Build (actor, status) synthetic objects from a parsed cryopod blob."""
    actor = _SyntheticGameObject(cryo.class_name or "", cryo.creature_props)
    status = _SyntheticGameObject(status_class, cryo.status_props)
    return actor, status


def _cryo_tamed_record(
    cryo: CryopodCreature,
    map_config: MapConfig | None,
    empty_lookup: dict[t.Any, t.Any],
) -> dict[str, t.Any]:
    """Decode one cryopod blob into a tamed record flagged ``cryo=True``."""
    actor, status = _cryo_props_to_synthetic(cryo)
    record = _tamed_dict(actor, status, empty_lookup, map_config)
    record["cryo"] = True
    return record


def _append_unique_tame(
    out: list[dict[str, t.Any]],
    seen_ids: set[int],
    record: dict[str, t.Any],
) -> None:
    """Append ``record`` unless a tame with the same non-zero dino id is present.

    Cluster cryopods can land in either ``ArkTamedDinosData`` or ``ArkItems``;
    a creature present in both would otherwise be emitted twice. Records whose
    dino id is 0 (unresolved, common on ASA partial decodes) are never deduped
    so distinct unidentified tames are all preserved.
    """
    did = _int(record.get("dinoid"))
    if did and did in seen_ids:
        return
    if did:
        seen_ids.add(did)
    out.append(record)


def export_cluster_uploads(
    cluster_inventories: t.Iterable[CloudInventory],
    map_config: MapConfig | None = None,
) -> list[dict[str, t.Any]]:
    """Export cluster-uploaded creatures in ``ASV_Tamed`` shape.

    Each cluster cloud-inventory file carries an ``ArkTamedDinosData`` array;
    every entry has a ``DinoData`` byte blob containing the full creature +
    status-component object pair. We decode each blob via
    :class:`CryopodCreature` and run it through the standard tamed-export
    field map.

    Cryopodded creatures inside ``ArkItems`` (uploaded cryopods) are also
    included here so a cluster export captures every cluster-resident dino
    regardless of which array it landed in.

    Args:
        cluster_inventories: ``CloudInventory`` instances loaded from a
            cluster directory.
        map_config: Optional map config (cluster uploads carry no location
            so GPS keys will be zeros).

    Returns:
        List of tamed dictionaries with ``cryo=True`` (cluster tames are
        always stored in cryopods).
    """
    out: list[dict[str, t.Any]] = []
    seen_ids: set[int] = set()
    empty_lookup: dict[t.Any, t.Any] = {}
    for inv in cluster_inventories:
        my_ark_data = normalize_indexed_data(inv.get_property_value("MyArkData"))
        if not isinstance(my_ark_data, dict):
            continue
        dino_list = normalize_indexed_list(my_ark_data.get("ArkTamedDinosData"))
        for entry in dino_list:
            entry = normalize_indexed_data(entry)
            if not isinstance(entry, dict):
                continue
            dino_data = entry.get("DinoData")
            byte_arr: list[int] | None = None
            if isinstance(dino_data, list):
                byte_arr = dino_data
            elif isinstance(dino_data, dict):
                inner = normalize_indexed_list(dino_data.get("ByteArrays"))
                if inner and isinstance(inner[0], dict):
                    byte_arr = inner[0].get("Bytes")
            if not byte_arr:
                continue
            cryo = CryopodCreature.from_cryopod_bytes(byte_arr)
            if cryo is None:
                continue
            _append_unique_tame(out, seen_ids, _cryo_tamed_record(cryo, map_config, empty_lookup))
        # Cryopods uploaded as items (rare but present, especially in ASA
        # tribute transfers) embed a CryopodCreature in CustomItemDatas.
        for item in inv.uploaded_items:
            if _is_placeholder_item(item) or not item.is_cryopod:
                continue
            cryo = item.cryopod_creature
            if cryo is None:
                continue
            _append_unique_tame(out, seen_ids, _cryo_tamed_record(cryo, map_config, empty_lookup))
    return out


def _uploaded_item_dict(item: t.Any) -> dict[str, t.Any]:
    """Shape a single ``UploadedItem`` as an inventory-style entry.

    Mirrors ``_inventory_items``: ``itemId``/``qty``/``blueprint`` at top,
    all aliased stats flattened in. Cryopod items get ``dino_*`` keys.
    """
    blueprint = item.blueprint or ""
    class_name = blueprint.rsplit(".", 1)[-1] if "." in blueprint else (item.name or "")
    if not class_name:
        # ASA cluster items store the class via ``ItemCustomClass`` object ref
        # instead of ``ItemArchetype`` path. Use that as the itemId fallback.
        ark_tribute = normalize_indexed_data(item.raw_data.get("ArkTributeItem", {}))
        if isinstance(ark_tribute, dict):
            custom_class = ark_tribute.get("ItemCustomClass")
            if isinstance(custom_class, tuple) and len(custom_class) == 2:
                custom_class = custom_class[1]
            if isinstance(custom_class, str) and custom_class:
                class_name = custom_class.rsplit(".", 1)[-1] if "." in custom_class else custom_class
    entry: dict[str, t.Any] = {
        "itemId": class_name or item.name,
        "qty": item.quantity,
        "blueprint": item.is_blueprint,
    }
    if item.is_cryopod:
        cryo = item.cryopod_creature
        if cryo is not None:
            props = cryo.creature_props
            dino_id = _combine_dino_id(
                props.get("DinoID1", props.get("DinoID1_0", 0)),
                props.get("DinoID2", props.get("DinoID2_0", 0)),
            )
            if dino_id:
                entry["dino_id"] = dino_id
            species_or_class = cryo.species or cryo.class_name
            if species_or_class:
                entry["dino_creature"] = str(species_or_class)
            if cryo.name:
                entry["dino_name"] = cryo.name
    ark_tribute = normalize_indexed_data(item.raw_data.get("ArkTributeItem", {}))
    if isinstance(ark_tribute, dict):
        pre: dict[str, t.Any] = {}
        for name, value in ark_tribute.items():
            if name in _ITEM_STATS_SKIP:
                continue
            snake = _pascal_to_snake(name)
            pre[snake] = _normalize_stat_value(snake, value)
        entry.update(_apply_stat_aliases(pre, item_class=class_name))
    upload_time = item.upload_time
    if upload_time:
        # Key name matches the legacy ASV item schema (uploadedTime), which
        # downstream consumers use as the "is uploaded" discriminator.
        try:
            entry["uploadedTime"] = dt.datetime.fromtimestamp(
                float(upload_time), tz=dt.timezone.utc
            ).isoformat()
        except (OverflowError, OSError, ValueError, TypeError):
            entry["uploadedTime"] = upload_time
    return entry


def _is_placeholder_item(item: t.Any) -> bool:
    """ASA cluster files include empty placeholder slots (no class).

    Identified by: no blueprint path, no item name, no ItemCustomClass ref
    in the underlying ArkTributeItem. ``item.quantity`` is coerced to >=1
    even when the source ``ItemQuantity`` is 0, so it isn't a reliable
    signal here.
    """
    if item.blueprint or item.name:
        return False
    ark_tribute = normalize_indexed_data(item.raw_data.get("ArkTributeItem", {}))
    if isinstance(ark_tribute, dict):
        custom_class = ark_tribute.get("ItemCustomClass")
        if isinstance(custom_class, tuple) and len(custom_class) == 2:
            custom_class = custom_class[1]
        if custom_class:
            return False
    return True


def export_cluster_items(
    cluster_inventories: t.Iterable[CloudInventory],
) -> list[dict[str, t.Any]]:
    """Export every uploaded item across the supplied cloud inventories.

    Each item carries its snake_case stats flattened in at the top level
    (``itemId``/``qty``/``blueprint`` plus ``armor``/``durability_max``/
    ``damage``/``rating``/``crafter`` etc) surfacing the full
    ``ArkTributeItem`` payload. Cryopod items also include ``dino_*`` keys with the embedded
    creature's identifying info; the dino's full stats record is emitted
    by :func:`export_cluster_uploads`.
    """
    out: list[dict[str, t.Any]] = []
    for inv in cluster_inventories:
        for item in inv.uploaded_items:
            if _is_placeholder_item(item):
                continue
            out.append(_uploaded_item_dict(item))
    return out


def export_cloud_inventory(
    cloud: CloudInventory,
    map_config: MapConfig | None = None,
) -> dict[str, list[dict[str, t.Any]]]:
    """Inspect a single cloud-inventory file.

    Returns a dict with two ASV-shaped lists:

    - ``ASV_Tamed``: every dino in the file (both ``ArkTamedDinosData``
      entries and cryopod items in ``ArkItems``), shaped like a regular
      tamed record so consumers can reuse existing rendering.
    - ``ASV_Items``: every uploaded item, snake_case stats flattened in
      at the top level (see :func:`export_cluster_items`).

    Useful for inspecting a single user's cluster transfer file in
    isolation, without scanning a whole cluster directory.
    """
    return {
        _EXPORT_NAMES["tamed"]: export_cluster_uploads([cloud], map_config),
        "ASV_Items": export_cluster_items([cloud]),
    }


_NONTAMEABLE_CLASSES: frozenset[str] = frozenset({
    "Xenomorph_Character_BP_Female_C",  # Reaper Queen
})

_MEGA_ALPHA_RE = re.compile(r"Mega[A-Z]|Mega_|Alpha_")


def _is_tameable(class_name: str, obj: t.Any) -> bool:
    """Mirror C# ContentWildCreature.IsTameable rule."""
    if _prop(obj, "bForceDisablingTaming", default=False):
        return False
    if class_name in _NONTAMEABLE_CLASSES:
        return False
    return _MEGA_ALPHA_RE.search(class_name) is None


def _wild_dict(
    obj: t.Any,
    status: t.Any,
    map_config: MapConfig | None,
) -> dict[str, t.Any]:
    base_pts = _stat_array(status, "NumberOfLevelUpPointsApplied")
    base_level = _int(_prop(status, "BaseCharacterLevel"), default=1) or 1
    colors = _colors(obj)
    is_female = bool(_prop(obj, "bIsFemale", default=False))
    dino_id = _combine_dino_id(_prop(obj, "DinoID1"), _prop(obj, "DinoID2"))
    traits = _traits(obj)
    class_name = getattr(obj, "class_name", "") or ""
    tameable = _is_tameable(class_name, obj)

    data: dict[str, t.Any] = {
        "id": dino_id,
        "creature": class_name,
        "sex": "Female" if is_female else "Male",
        "lvl": base_level,
        **_flat_stats(base_pts),
        **{f"c{i}": colors[i] for i in range(6)},
        "dinoid": str(dino_id),
        "tameable": tameable,
        # Legacy emits the first trait as a singular ``trait``; the full
        # CreatureTraits list is exposed alongside as ``traits``.
        "trait": traits[0] if traits else "",
        "traits": traits,
        "current_stats": _current_stats_dict(status),
        "wild_spawn_region": _str(_prop(obj, "OriginalNPCVolumeName")),
    }
    data.update(_gps_payload(obj, map_config))
    return _compact(data, LEGACY_WILD_KEYS)


def export_wild(save: t.Any, map_config: MapConfig | None = None) -> list[dict[str, t.Any]]:
    objects = _world_objects(save, "get_wild_creatures", "wild_objects")
    lookup = _save_lookup(save)
    return [_wild_dict(obj, _status_for(obj, lookup), map_config) for obj in objects]


def _player_from_profile(
    profile: Profile,
    save: t.Any = None,
    pawn_status_by_id: dict[int, t.Any] | None = None,
) -> dict[str, t.Any]:
    stat_points = [_int(profile.get_stat(i)["added"]) for i in range(12)]
    gamertag = profile.player_name or ""
    character = profile.character_name or gamertag
    steam_id = profile.unique_id or ""
    active_dt = _approx_real_datetime(profile.last_login_time, save)

    # Live HP/stam/etc live on the player's in-world pawn's status component,
    # not in the profile. Resolve via PlayerDataID -> pawn -> status. Absent
    # when the player has no spawned body (never spawned / corpse cleared).
    status = None
    if pawn_status_by_id and profile.player_id:
        status = pawn_status_by_id.get(int(profile.player_id))

    out: dict[str, t.Any] = {
        "playerid": profile.player_id or 0,
        "steam": _str(gamertag),
        "name": _str(character),
        "tribeid": profile.tribe_id or 0,
        "tribe": profile.tribe_name or "",
        "sex": "Female" if profile.is_female is True else "Male",
        "lvl": profile.level,
        "lat": 0.0,
        "lon": 0.0,
        **_flat_stats(stat_points),
        "active": active_dt.isoformat() if active_dt is not None else None,
        "ccc": "0 0 0",
        "achievements": [],
        "inventory": [],
        "netAddress": "",
        "engram_points": profile.total_engram_points,
        "experience": _int(profile.experience),
        "current_stats": _current_stats_dict(status),
    }
    if steam_id:
        out["steamid"] = steam_id
        out["dataFile"] = f"{steam_id}.arkprofile"
    else:
        out["steamid"] = ""
        out["dataFile"] = ""
    return _compact(out, LEGACY_PLAYER_KEYS)


def _player_from_object(
    obj: t.Any,
    status: t.Any,
    lookup: dict[t.Any, t.Any] | None = None,
    map_config: MapConfig | None = None,
    save: t.Any = None,
) -> dict[str, t.Any]:
    base_level = _int(_prop(status, "BaseCharacterLevel"), default=1) or 1
    extra_level = _int(_prop(status, "ExtraCharacterLevel"))
    stat_points = _stat_array(status, "NumberOfLevelUpPointsApplied")
    player_id = _int(_prop(obj, "PlayerDataID")) or _int(_prop(obj, "LinkedPlayerDataID"))
    tribe_id = _int(_prop(obj, "TribeID")) or _int(_prop(obj, "TribeId")) or _int(_prop(obj, "TargetingTeam"))
    last_active_seconds = _float(
        _prop(obj, "SavedLastTimeHadController") or _prop(obj, "LastTimeHadController")
    )
    active_dt = _approx_real_datetime(last_active_seconds, save)
    gps = _gps_payload(obj, map_config, ndigits=2)
    inv_lookup = lookup if lookup is not None else {}
    _, died_iso = _iso_pair(obj, "LocalDiedAtTime", save)
    _, corpse_iso = _iso_pair(obj, "CorpseDestructionTime", save)
    body_colors_raw = _prop(obj, "BodyColors")
    body_colors: list[int] = []
    if isinstance(body_colors_raw, dict):
        for i in sorted(k for k in body_colors_raw if isinstance(k, int)):
            body_colors.append(_int(body_colors_raw.get(i)))
    elif isinstance(body_colors_raw, list):
        body_colors = [_int(v) for v in body_colors_raw]
    if not any(body_colors):
        body_colors = []
    data: dict[str, t.Any] = {
        "playerid": player_id,
        "steam": _str(_prop(obj, "PlatformProfileName")),
        "name": _str(_prop(obj, "PlayerName")),
        "tribeid": tribe_id,
        "tribe": _str(_prop(obj, "TribeName")),
        "sex": "Female" if _prop(obj, "bIsFemale", default=False) else "Male",
        "lvl": base_level + extra_level,
        "lat": gps["lat"],
        "lon": gps["lon"],
        **_flat_stats(stat_points),
        "active": active_dt.isoformat() if active_dt is not None else None,
        "ccc": gps["ccc"],
        "achievements": [],
        "inventory": _inventory_items(obj, inv_lookup),
        "netAddress": "",
        "steamid": "",
        "dataFile": "",
        "engram_points": _int(_prop(obj, "TotalEngramPoints")),
        "experience": _int(_prop(status, "ExperiencePoints")),
        "is_sleeping": bool(_prop(obj, "bIsSleeping", default=False)),
        "is_dead": bool(_prop(obj, "bIsDead", default=False)),
        "chibi_levels": _int(_prop(obj, "NumChibiLevelUps")),
        "ascensions_scorched": _int(_prop(obj, "NumAscensionsScorched")),
        "is_prone": bool(_prop(obj, "bIsProne", default=False)),
        "is_crouched": bool(_prop(obj, "bIsCrouched", default=False)),
        "hat_hidden": bool(_prop(obj, "bHatHidden", default=False)),
        "current_weapon": _ref_name(_prop(obj, "CurrentWeapon")),
        "seated_on_ref": _ref_name(_prop(obj, "SeatingStructure")),
        "original_hair_color": _int(_prop(obj, "OriginalHairColor")),
        "head_hair_growth": _float(_prop(obj, "PercentOfFullHeadHairGrowth")),
        "facial_hair_growth": _float(_prop(obj, "PercentOfFullFacialHairGrowth")),
        "body_colors": body_colors,
        "died_at": died_iso,
        "corpse_destruction": corpse_iso,
        "current_stats": _current_stats_dict(status),
    }
    return _compact(data, LEGACY_PLAYER_KEYS)


def _player_status_by_data_id(save: t.Any, lookup: dict[t.Any, t.Any]) -> dict[int, t.Any]:
    """Index ``MyCharacterStatusComponent`` per player by ``LinkedPlayerDataID``.

    Walks every ``PlayerPawnTest_*_C`` / ``PlayerCharacter_*`` in the world
    save, reads its ``LinkedPlayerDataID``, follows ``MyCharacterStatusComponent``
    via ``lookup``, and stores the resolved status object. Lets profile-based
    player exports surface live HP/stamina/food/etc. without legacy ASVPack
    having to do the same join.
    """
    out: dict[int, t.Any] = {}
    objects = getattr(save, "objects", None) or []
    for obj in objects:
        cn = str(getattr(obj, "class_name", "") or "")
        if "PlayerPawn" not in cn and "PlayerCharacter" not in cn:
            continue
        pid = _int(_prop(obj, "LinkedPlayerDataID"))
        if not pid:
            continue
        status = _status_for(obj, lookup)
        if status is not None:
            out[pid] = status
    return out


def _cluster_items_by_xuid(
    cluster_inventories: t.Iterable[CloudInventory],
) -> dict[str, list[dict[str, t.Any]]]:
    """Group uploaded items by cloud-file stem (= player's unique_id / xuid).

    Each cluster file is named after the owning player's Steam id (ASE) or
    platform UUID (ASA). That same stem names the player's ``.arkprofile``,
    so :func:`export_players` joins on the profile's source filename stem
    (see there) — a stable key on both platforms without cracking any
    in-file ownership data. (``Profile.unique_id`` equals the stem only on
    ASE; on ASA it is the numeric net id, not the UUID filename.)
    """
    out: dict[str, list[dict[str, t.Any]]] = {}
    for inv in cluster_inventories:
        if inv.source_path is None:
            continue
        xuid = inv.source_path.stem
        if not xuid:
            continue
        bucket = out.setdefault(xuid, [])
        for item in inv.uploaded_items:
            if _is_placeholder_item(item):
                continue
            entry = _uploaded_item_dict(item)
            entry["uploaded"] = True
            bucket.append(entry)
    return out


def export_players(
    save: t.Any,
    map_config: MapConfig | None = None,
    cluster_inventories: t.Iterable[CloudInventory] | None = None,
) -> list[dict[str, t.Any]]:
    profiles = _collection(save, "profiles", Profile)
    lookup = _save_lookup(save)
    pawn_status_by_id = _player_status_by_data_id(save, lookup)
    cluster_items = (
        _cluster_items_by_xuid(cluster_inventories) if cluster_inventories else {}
    )
    results: list[dict[str, t.Any]] = []
    for entry in profiles:
        record: dict[str, t.Any]
        # Keys to match against the cloud-file stem, in priority order.
        join_keys: list[str] = []
        if isinstance(entry, Profile):
            record = _player_from_profile(entry, save, pawn_status_by_id)
            # The cloud file and the .arkprofile for one player share a stem:
            # the Steam id on ASE, the hex platform UUID on ASA. The profile's
            # own source filename stem is therefore the reliable cross-platform
            # join key. ``unique_id`` only equals it on ASE (on ASA it is the
            # numeric net id, not the UUID filename), so it is a fallback.
            if entry.source_path is not None and entry.source_path.stem:
                join_keys.append(entry.source_path.stem)
            if entry.unique_id:
                join_keys.append(entry.unique_id)
        else:
            profile_obj = getattr(entry, "profile", None)
            if profile_obj is None and getattr(entry, "objects", None):
                profile_obj = entry.objects[0]
            if profile_obj is None:
                continue
            status_obj = None
            for o in getattr(entry, "objects", []) or []:
                cn = str(getattr(o, "class_name", ""))
                if "StatusComponent" in cn or "CharacterStatus" in cn:
                    status_obj = o
                    break
            record = _player_from_object(profile_obj, status_obj, lookup, map_config, save)
            sid = record.get("steamid")
            if sid:
                join_keys.append(str(sid))
        # Splice cluster-uploaded items into the player's inventory list,
        # tagged ``uploaded: true`` so consumers can distinguish them from
        # carried items.
        spliced = next((cluster_items[k] for k in join_keys if k in cluster_items), None)
        if spliced:
            inv_list = record.get("inventory")
            if not isinstance(inv_list, list):
                inv_list = []
                record["inventory"] = inv_list
            inv_list.extend(spliced)
        results.append(record)
    return results


def _strip_rich_color(msg: str) -> str:
    return _RICH_COLOR_RE.sub("", msg).strip()


def _parse_log(raw: str) -> dict[str, t.Any]:
    raw = raw.strip()
    m = _LOG_RE.match(raw)
    if m:
        day = int(m.group(1))
        time = m.group(2)
        clean = _strip_rich_color(m.group(3))
    else:
        day = 0
        time = ""
        clean = _strip_rich_color(raw)
    return {"day": day, "time": time, "message": raw, "clean_message": clean}


def _tribe_members_from_parser(
    tribe: Tribe,
    profile_index: dict[int, Profile] | None = None,
) -> list[dict[str, t.Any]]:
    """Legacy member shape: {ign, lvl, playerid, playername, steamid}.

    When ``profile_index`` (player_id → Profile) is supplied, fills ``lvl``
    and ``steamid`` from the matching ``.arkprofile``. Tribe files don't
    carry per-member level / platform id themselves; the join is the only
    way to enrich them.
    """
    out: list[dict[str, t.Any]] = []
    for m in tribe.get_members():
        pid = _int(m.get("player_id"))
        profile = profile_index.get(pid) if profile_index else None
        out.append({
            "ign": _str(m.get("name")),
            "lvl": int(profile.level) if profile is not None else 0,
            "playerid": str(pid),
            "playername": _str(m.get("name")),
            "steamid": (profile.unique_id or "") if profile is not None else "",
        })
    return out


def _tribe_active_iso(logs: t.Iterable[str], save: t.Any) -> str | None:
    """Derive ``active`` ISO datetime from the most recent tribe log entry.

    Tribe files don't carry an "active" timestamp directly. Each log entry
    is formatted ``Day N, HH:MM:SS: <message>`` (game-time). The most recent
    entry yields the highest game-second count, which combined with the
    save's anchor (``file_mtime + (max_log_seconds - game_time)``) gives a
    real wall-clock timestamp.

    Returns ``None`` when no parseable log entry is found or the save lacks
    conversion anchors.
    """
    max_seconds = 0
    for raw in logs:
        if not isinstance(raw, str):
            continue
        m = _LOG_RE.match(raw.strip())
        if not m:
            continue
        try:
            day = int(m.group(1))
        except (TypeError, ValueError):
            continue
        parts = m.group(2).split(":")
        if len(parts) < 2:
            continue
        try:
            h = int(parts[0])
            mi = int(parts[1])
            s = int(parts[2]) if len(parts) > 2 else 0
        except (TypeError, ValueError):
            continue
        sec = day * 86400 + h * 3600 + mi * 60 + s
        if sec > max_seconds:
            max_seconds = sec
    if not max_seconds:
        return None
    real = _approx_real_datetime(max_seconds, save)
    return real.isoformat() if real is not None else None


def _build_profile_index(save: t.Any) -> dict[int, Profile]:
    """Index ``save.profiles`` by player_id for tribe-member enrichment."""
    out: dict[int, Profile] = {}
    profiles = getattr(save, "profiles", None) or []
    for entry in profiles:
        if isinstance(entry, Profile) and entry.player_id:
            out[int(entry.player_id)] = entry
    return out


def _tribe_from_parser(
    tribe: Tribe,
    counts: dict[int, dict[str, int]],
    profile_index: dict[int, Profile] | None = None,
    save: t.Any = None,
) -> dict[str, t.Any]:
    tid = _int(tribe.tribe_id)
    c = counts.get(tid, {})
    data: dict[str, t.Any] = {
        "tribeid": tid,
        "tribe": tribe.name or "",
        "players": tribe.member_count,
        "members": _tribe_members_from_parser(tribe, profile_index),
        "tames": c.get("tames", 0),
        "uploadedTames": 0,
        "structures": c.get("structures", 0),
        "active": _tribe_active_iso(tribe.log_entries, save),
        "dataFile": f"{tid}.arktribe" if tid else "",
        "owner_id": tribe.owner_player_id or 0,
        "alliance_ids": tribe.alliance_ids,
    }
    return _compact(data, LEGACY_TRIBE_KEYS)


def _tribe_from_object(
    obj: t.Any,
    counts: dict[int, dict[str, int]],
    profile_index: dict[int, Profile] | None = None,
    save: t.Any = None,
) -> dict[str, t.Any]:
    tribe_id = _int(_prop(obj, "TribeID")) or _int(_prop(obj, "TribeId"))
    owner_id = (
        _int(_prop(obj, "OwnerPlayerDataID"))
        or _int(_prop(obj, "OwnerPlayerDataId"))
    )
    members: list[dict[str, t.Any]] = []
    i = 0
    while True:
        pid = _prop(obj, "MembersPlayerDataID", index=i)
        if pid is None:
            break
        name = _str(_prop(obj, "MembersPlayerName", index=i))
        pid_int = _int(pid)
        profile = profile_index.get(pid_int) if profile_index else None
        members.append({
            "ign": name,
            "lvl": int(profile.level) if profile is not None else 0,
            "playerid": str(pid_int),
            "playername": name,
            "steamid": (profile.unique_id or "") if profile is not None else "",
        })
        i += 1
    alliances: list[int] = []
    j = 0
    while True:
        val = _prop(obj, "TribeAlliances", index=j)
        if val is None:
            break
        alliances.append(_int(val))
        j += 1
    c = counts.get(tribe_id, {})
    data: dict[str, t.Any] = {
        "tribeid": tribe_id,
        "tribe": _str(_prop(obj, "TribeName")),
        "players": len(members),
        "members": members,
        "tames": c.get("tames", 0),
        "uploadedTames": 0,
        "structures": c.get("structures", 0),
        "active": _tribe_active_iso(_tribe_object_logs(obj), save),
        "dataFile": f"{tribe_id}.arktribe" if tribe_id else "",
        "owner_id": owner_id,
        "owner_name": _str(_prop(obj, "OwnerPlayerName")),
        "alliance_ids": alliances,
    }
    return _compact(data, LEGACY_TRIBE_KEYS)


def _tribe_object_logs(obj: t.Any) -> list[str]:
    """Read raw TribeLog entries off an in-world tribe GameObject."""
    log_val = _prop(obj, "TribeLog")
    if isinstance(log_val, list):
        return [e for e in log_val if isinstance(e, str) and e.strip()]
    out: list[str] = []
    k = 0
    while True:
        v = _prop(obj, "TribeLog", index=k)
        if v is None:
            break
        if isinstance(v, str) and v.strip():
            out.append(v)
        k += 1
    return out


def export_tribes(save: t.Any) -> list[dict[str, t.Any]]:
    tribes = _collection(save, "tribes", Tribe)
    counts = _tribe_counts(save)
    profile_index = _build_profile_index(save)
    results: list[dict[str, t.Any]] = []
    for entry in tribes:
        if isinstance(entry, Tribe):
            results.append(_tribe_from_parser(entry, counts, profile_index, save))
            continue
        tribe_obj = getattr(entry, "tribe", None)
        if tribe_obj is None and getattr(entry, "objects", None):
            tribe_obj = entry.objects[0]
        if tribe_obj is None:
            continue
        results.append(_tribe_from_object(tribe_obj, counts, profile_index, save))
    return results


def export_tribe_logs(save: t.Any) -> list[dict[str, t.Any]]:
    tribes = _collection(save, "tribes", Tribe)
    results: list[dict[str, t.Any]] = []
    for entry in tribes:
        if isinstance(entry, Tribe):
            results.append({
                "tribeid": entry.tribe_id or 0,
                "tribe": entry.name or "",
                "logs": list(entry.log_entries),
            })
            continue
        tribe_obj = getattr(entry, "tribe", None)
        if tribe_obj is None and getattr(entry, "objects", None):
            tribe_obj = entry.objects[0]
        if tribe_obj is None:
            continue
        tribe_id = _int(_prop(tribe_obj, "TribeID")) or _int(_prop(tribe_obj, "TribeId"))
        name = _str(_prop(tribe_obj, "TribeName"))
        log_val = _prop(tribe_obj, "TribeLog")
        raw_logs: list[str] = []
        if isinstance(log_val, list):
            raw_logs = [str(e) for e in log_val if isinstance(e, str) and e.strip()]
        else:
            k = 0
            while True:
                val = _prop(tribe_obj, "TribeLog", index=k)
                if val is None:
                    break
                if isinstance(val, str) and val.strip():
                    raw_logs.append(val)
                k += 1
        results.append({"tribeid": tribe_id, "tribe": name, "logs": raw_logs})
    return results


def _structure_created(obj: t.Any, save: t.Any) -> str | None:
    """Best-effort real-world creation timestamp as ISO 8601 with timezone.

    Returns ``None`` when ``OriginalCreationTime`` is missing or the save
    lacks the mtime / game-time anchors needed to convert from in-game
    seconds. The timezone is the local zone of the machine that loaded the
    save (legacy ASVExport also serializes in local time).
    """
    real_dt = _approx_real_datetime(_prop(obj, "OriginalCreationTime"), save)
    return real_dt.isoformat() if real_dt is not None else None


def _feeding_lists(obj: t.Any) -> tuple[list[str], list[str]]:
    """Return (inclusions, exclusions) class-name lists for feeding troughs.

    ASA feeding troughs carry a ``DinoFeedingListType`` (1 = inclusion,
    2 = exclusion) and a ``FeedingDinoList`` array of object refs. Mirrors
    legacy ContentStructure.cs ASA constructor.
    """
    list_type = _int(_prop(obj, "DinoFeedingListType"))
    if list_type not in (1, 2):
        return [], []
    raw = _prop(obj, "FeedingDinoList")
    if not isinstance(raw, list):
        return [], []
    classes: list[str] = []
    for entry in raw:
        if isinstance(entry, tuple) and len(entry) == 2:
            classes.append(str(entry[1]))
        elif entry:
            classes.append(str(entry))
    return (classes, []) if list_type == 1 else ([], classes)


def _structure_colors(obj: t.Any) -> list[int]:
    """6-slot paint color list from ``StructureColors``.

    Returns ``[]`` (will be pruned) when the structure carries no paint
    data or every slot is the unpainted sentinel ``0``. Painted structures
    return a length-6 list of indices.
    """
    raw = _prop(obj, "StructureColors")
    if not raw:
        return []
    if isinstance(raw, dict):
        out = [_int(raw.get(i)) for i in range(6)]
    elif isinstance(raw, list):
        out = [_int(raw[i]) if i < len(raw) else 0 for i in range(6)]
    else:
        return []
    return out if any(out) else []


def _structure_dict(
    obj: t.Any,
    save: t.Any,
    lookup: dict[t.Any, t.Any],
    map_config: MapConfig | None,
) -> dict[str, t.Any]:
    # Legacy uses BoxName for player-set labels; emit "" if it matches the
    # class name (legacy ContentPack.cs:1596 strips no-rename cases).
    class_name = getattr(obj, "class_name", "") or ""
    box_name = _str(_prop(obj, "BoxName"))
    if box_name == class_name:
        box_name = ""
    locked = bool(
        _prop(obj, "bIsPinLocked", default=False)
        or _prop(obj, "bIsLocked", default=False)
    )
    powered = bool(
        _prop(obj, "bIsPowered", default=False)
        or _prop(obj, "bHasFuel", default=False)
    )
    inclusions, exclusions = _feeding_lists(obj)
    _, activated_iso = _iso_pair(obj, "LastActivatedTime", save)
    _, deactivated_iso = _iso_pair(obj, "LastDeactivatedTime", save)
    _, fire_iso = _iso_pair(obj, "LastFireTime", save)
    _, reload_iso = _iso_pair(obj, "LastLongReloadStartTime", save)
    _, fuel_iso = _iso_pair(obj, "LastCheckedFuelTime", save)
    attached_dino_id = _combine_dino_id(
        _prop(obj, "AttachedToDinoID1"),
        _prop(obj, "AttachedToDinoID2"),
    ) or None
    data: dict[str, t.Any] = {
        "id": getattr(obj, "id", 0) or 0,
        "tribeid": _int(_prop(obj, "TargetingTeam")),
        "tribe": _str(_prop(obj, "OwnerName")),
        "struct": class_name,
        "name": box_name,
        "locked": locked,
        "created": _structure_created(obj, save),
        "inventory": _inventory_items(obj, lookup),
        "powered": powered,
        "switched_on": bool(_prop(obj, "bContainerActivated", default=False)),
        "decay_reset": bool(_prop(obj, "bHasResetDecayTime", default=False)),
        "last_ally_in_range": (
            d.isoformat()
            if (d := _approx_real_datetime(
                _prop(obj, "LastInAllyRangeTime")
                or _prop(obj, "LastInAllyRangeTimeSerialized")
                or _prop(obj, "LastInAllyRangeSerialized"),
                save,
            )) is not None
            else None
        ),
        "painting_id": _int(_prop(obj, "UniquePaintingId")),
        "feeding_inclusions": inclusions,
        "feeding_exclusions": exclusions,
        "health": _float(_prop(obj, "Health")),
        "max_health": _float(_prop(obj, "MaxHealth")),
        "owning_player_id": _int(_prop(obj, "OwningPlayerID")),
        "owning_player_name": _str(_prop(obj, "OwningPlayerName")),
        "colors": _structure_colors(obj),
        "current_item_count": _int(_prop(obj, "CurrentItemCount")),
        "max_item_count": _int(_prop(obj, "MaxItemCount")),
        "num_bullets": _int(_prop(obj, "NumBullets")),
        "range_setting": _int(_prop(obj, "RangeSetting")),
        "has_fuel": bool(_prop(obj, "bHasFuel", default=False)),
        "is_foundation": bool(_prop(obj, "bIsFoundation", default=False)),
        "placement_snapped": bool(_prop(obj, "bWasPlacementSnapped", default=False)),
        "variant": _int(_prop(obj, "CurrentVariant")),
        "selected_resource_class": _ref_name(_prop(obj, "SelectedResourceClass")),
        "resource_count": _int(_prop(obj, "ResourceCount")),
        "dedicated_storage_version": _int(_prop(obj, "SavedDedicatedStorageVersion")),
        "painting_ref": _ref_name(_prop(obj, "PaintingComponent")),
        "saddle_dino_ref": _ref_name(_prop(obj, "SaddleDino")),
        "attached_dino_id": attached_dino_id,
        "linked_structures": _ref_list(_prop(obj, "LinkedStructures")),
        "last_activated": activated_iso,
        "last_deactivated": deactivated_iso,
        "last_fire": fire_iso,
        "last_reload": reload_iso,
        "last_fuel_check": fuel_iso,
        "pin_code": _pin_code(obj),
    }
    data.update(_gps_payload(obj, map_config, ndigits=2))
    return _compact(data, LEGACY_STRUCT_KEYS)


def export_structures(save: t.Any, map_config: MapConfig | None = None) -> list[dict[str, t.Any]]:
    objects = _world_objects(save, "get_structures", "structure_objects")
    lookup = _save_lookup(save)
    return [_structure_dict(obj, save, lookup, map_config) for obj in objects]


# Mirrors C# ContentContainer.cs:846. Order matters: first match wins.
_MAP_STRUCT_RULES: tuple[tuple[str, str, str], ...] = (
    ("TributeTerminal_", "ASV_Terminal", "startswith"),
    ("CityTerminal_", "ASV_Terminal", "contains"),
    ("PowerNodeCharge", "ASV_ChargeNode", "startswith"),
    ("BeaverDam_C", "ASV_BeaverDam", "startswith"),
    ("DeinonychusNest_C", "ASV_DeinoNest", "startswith"),
    ("RockDrakeNest_C", "ASV_DrakeNest", "startswith"),
    ("CherufeNest_C", "ASV_MagmaNest", "startswith"),
    ("WyvernNest_", "ASV_WyvernNest", "startswith"),
    ("OilVein_", "ASV_OilVein", "startswith"),
    ("WaterVein_", "ASV_WaterVein", "startswith"),
    ("GasVein_", "ASV_GasVein", "startswith"),
    ("ArtifactCrate_", "ASV_Artifact", "startswith"),
    ("Structure_PlantSpeciesZ_PlayerGrown", "ASV_PlantSpeciesZ", "startswith"),
    ("BeeHive_C", "ASV_BeeHive", "startswith"),
)


def _asv_map_struct_label(class_name: str) -> str | None:
    for pattern, label, kind in _MAP_STRUCT_RULES:
        if kind == "startswith":
            if class_name.startswith(pattern):
                return label
        elif pattern in class_name:
            return label
    return None


def export_map_structures(
    save: t.Any,
    map_config: MapConfig | None = None,
) -> list[dict[str, t.Any]]:
    objects = getattr(save, "objects", None) or []
    all_objs = list(objects.values()) if isinstance(objects, dict) else list(objects)
    lookup = _save_lookup(save)
    results: list[dict[str, t.Any]] = []
    for obj in all_objs:
        cn = getattr(obj, "class_name", "") or ""
        label = _asv_map_struct_label(cn)
        if label is None:
            continue
        loc = getattr(obj, "location", None)
        if loc is None:
            continue
        if _prop(obj, "TargetingTeam") is not None:
            continue
        data: dict[str, t.Any] = {
            "struct": label,
            "inventory": _inventory_items(obj, lookup),
        }
        data.update(_gps_payload(obj, map_config))
        results.append(data)
    return results


# Legacy ASVExport.exe filenames. Single canonical schema.
_EXPORT_NAMES: dict[str, str] = {
    "tamed": "ASV_Tamed",
    "wild": "ASV_Wild",
    "players": "ASV_Players",
    "tribes": "ASV_Tribes",
    "structures": "ASV_Structures",
    "tribe_logs": "ASV_TribeLogs",
    "map_structures": "ASV_MapStructures",
}


def _wrap_with_meta(
    data: list[dict[str, t.Any]],
    save: t.Any,
    map_config: MapConfig | None = None,
) -> dict[str, t.Any]:
    """Wrap a payload in legacy ``{map, day, time, data}`` envelope."""
    map_name = getattr(map_config, "name", "") if map_config is not None else ""
    day = 0
    time_str = "00:00"
    game_time = _float(getattr(save, "game_time", 0.0))
    if game_time:
        day = int(game_time // 86400)
        rem = int(game_time % 86400)
        time_str = f"{rem // 3600:02d}:{(rem % 3600) // 60:02d}"
    return {"map": map_name, "day": day, "time": time_str, "data": data}


def _load_cluster_inventories(
    cluster: str | Path | t.Iterable[CloudInventory] | None,
) -> list[CloudInventory]:
    """Resolve the ``cluster`` argument for :func:`export_all`.

    Accepts ``None`` (returns ``[]``), a directory path containing
    cluster files (loads every readable file), or any iterable of
    already-loaded :class:`CloudInventory` instances.
    """
    if cluster is None:
        return []
    if isinstance(cluster, (str, Path)):
        root = Path(cluster)
        if not root.is_dir():
            return []
        loaded: list[CloudInventory] = []
        for entry in root.iterdir():
            if not entry.is_file() or entry.stat().st_size == 0:
                continue
            try:
                loaded.append(CloudInventory.load(entry))
            except (OSError, ValueError, Exception):  # noqa: BLE001
                continue
        return loaded
    return [inv for inv in cluster if isinstance(inv, CloudInventory)]


def export_all(
    save: t.Any,
    map_config: MapConfig | None = None,
    cluster: str | Path | t.Iterable[CloudInventory] | None = None,
) -> dict[str, list[dict[str, t.Any]]]:
    """Run every exporter and return a dict keyed by ASV filename stems.

    With ``cluster`` set (a directory path or an iterable of
    :class:`CloudInventory` instances) the tamed export is automatically
    spliced with cluster-uploaded tames via :func:`export_cluster_uploads`,
    matching the legacy ASVExport behaviour when invoked with a cluster
    directory.

    Note: returns flat lists per type (not the legacy ``{map, day, time, data}``
    envelope). ``export_to_files`` adds the envelope when writing.
    """
    tamed = export_tamed(save, map_config)
    cluster_invs = _load_cluster_inventories(cluster)
    if cluster_invs:
        tamed = tamed + export_cluster_uploads(cluster_invs, map_config)
    return {
        _EXPORT_NAMES["tamed"]: tamed,
        _EXPORT_NAMES["wild"]: export_wild(save, map_config),
        _EXPORT_NAMES["players"]: export_players(save, map_config, cluster_invs or None),
        _EXPORT_NAMES["tribes"]: export_tribes(save),
        _EXPORT_NAMES["structures"]: export_structures(save, map_config),
        _EXPORT_NAMES["tribe_logs"]: export_tribe_logs(save),
        _EXPORT_NAMES["map_structures"]: export_map_structures(save, map_config),
    }


def export_to_files(
    save: t.Any,
    output_dir: str | Path,
    map_config: MapConfig | None = None,
    wrap: bool = True,
    cluster: str | Path | t.Iterable[CloudInventory] | None = None,
    compact: bool = False,
) -> list[Path]:
    """Write every export to ``<output_dir>/<ASV_Name>.json``.

    With ``wrap=True`` (default) each file mirrors the legacy ASVExport.exe
    ``{"map":..., "day":..., "time":..., "data":[...]}`` envelope. Set
    ``wrap=False`` to write the flat list returned by the exporter functions.

    Passing ``cluster`` (a directory path or pre-loaded ``CloudInventory``
    instances) folds cluster-uploaded tames into ``ASV_Tamed.json``.

    With ``compact=True`` the JSON is serialized without indentation or
    inter-element spaces. Roughly halves output size on large maps and cuts
    serialization time meaningfully. Default ``False`` preserves the
    human-readable ``indent=2`` format for diff-friendly output.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    if compact:
        dump_kwargs: dict[str, t.Any] = {"separators": (",", ":"), "default": str}
    else:
        dump_kwargs = {"indent": 2, "default": str}
    for name, data in export_all(save, map_config, cluster=cluster).items():
        payload: t.Any = _wrap_with_meta(data, save, map_config) if wrap else data
        path = out / f"{name}.json"
        path.write_text(json.dumps(payload, **dump_kwargs), encoding="utf-8")
        created.append(path)
    return created
